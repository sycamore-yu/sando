// Regression: empty classification (classes/voxel_indices nullptr) must match the
// pre-classification HGP entry (default args). That nullptr branch is the live-map
// path in obstacle_to_vec when map_util_for_planning_ is set.
//
// Online planLocalTrajectory calls cvxEllipsoidDecomp / TimeLayered without class
// args (defaults stay null) — see sando.cpp planLocalTrajectory.

#include <hgp/hgp_manager.hpp>
#include <sando/gurobi_solver.hpp>
#include <sando/planning_instance.hpp>
#include <sando/segment_time.hpp>

#include <decomp_util/ellipsoid_decomp.h>

#include <cmath>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void require(bool value, const std::string& message) {
  if (!value) throw std::runtime_error(message);
}

Parameters tinyParams() {
  Parameters p{};
  p.num_N = 5;
  p.num_P = 1;
  p.dc = 1.0;
  p.dynamic_constraint_type = "Linf";
  p.using_variable_elimination = true;
  p.x_min = -2.0;
  p.x_max = 5.0;
  p.y_min = -3.0;
  p.y_max = 4.0;
  p.z_min = -1.0;
  p.z_max = 4.0;
  p.v_max = 20.0;
  p.a_max = 40.0;
  p.j_max = 100.0;
  p.factor_initial = 1.0;
  p.factor_final = 1.0;
  p.factor_constant_step_size = 1.0;
  p.max_gurobi_comp_time_sec = 30.0;
  p.jerk_smooth_weight = 1.0;
  p.horizon = 10.0;
  p.res = 0.3;
  p.factor_hgp = 1.0;
  p.drone_radius = 0.2;
  p.sfc_size = {4.0, 4.0, 4.0};
  p.obst_max_vel = 1.0;
  p.obst_position_error = 0.0;
  p.inflate_unknown_boundary = true;
  p.environment_assumption = "dynamic";
  p.debug_verbose = false;
  return p;
}

bool sameConstraint(const LinearConstraint3D& a, const LinearConstraint3D& b) {
  if (a.A_.rows() != b.A_.rows() || a.A_.cols() != b.A_.cols()) return false;
  if (a.b_.size() != b.b_.size()) return false;
  for (int r = 0; r < a.A_.rows(); ++r) {
    for (int c = 0; c < a.A_.cols(); ++c)
      if (std::abs(a.A_(r, c) - b.A_(r, c)) > 1e-9) return false;
    if (std::abs(a.b_(r) - b.b_(r)) > 1e-9) return false;
  }
  return true;
}

bool sameLayers(const std::vector<std::vector<LinearConstraint3D>>& left,
                const std::vector<std::vector<LinearConstraint3D>>& right) {
  if (left.size() != right.size()) return false;
  for (std::size_t n = 0; n < left.size(); ++n) {
    if (left[n].size() != right[n].size()) return false;
    for (std::size_t p = 0; p < left[n].size(); ++p)
      if (!sameConstraint(left[n][p], right[n][p])) return false;
  }
  return true;
}

int hyperplaneCount(const std::vector<std::vector<LinearConstraint3D>>& layers) {
  int count = 0;
  for (const auto& layer : layers)
    for (const auto& c : layer) count += static_cast<int>(c.A_.rows());
  return count;
}

int polyhedronCount(const std::vector<vec_E<Polyhedron<3>>>& polys) {
  int count = 0;
  for (const auto& layer : polys) count += static_cast<int>(layer.size());
  return count;
}

bool sameCloud(const vec_Vec3f& a, const vec_Vec3f& b) {
  if (a.size() != b.size()) return false;
  for (std::size_t i = 0; i < a.size(); ++i)
    if ((a[i] - b[i]).norm() > 1e-9) return false;
  return true;
}

struct DecompResult {
  std::vector<std::vector<LinearConstraint3D>> layers;
  std::vector<vec_E<Polyhedron<3>>> polys;
};

DecompResult runDecomp(HGPManager& hgp, EllipsoidDecomp3D& ellip, const vec_Vecf<3>& path,
                       const vec_Vec3f& base, const vec_Vecf<3>& obst_pos,
                       const vec_Vecf<3>& obst_bbox, const std::vector<double>& times,
                       bool pass_explicit_null) {
  DecompResult out;
  bool ok = false;
  if (pass_explicit_null) {
    ok = hgp.cvxEllipsoidDecompTimeLayered(ellip, path, base, obst_pos, obst_bbox, times,
                                           out.layers, out.polys, nullptr, nullptr);
  } else {
    // Legacy entry: omit classification args (defaults are nullptr).
    ok = hgp.cvxEllipsoidDecompTimeLayered(ellip, path, base, obst_pos, obst_bbox, times,
                                           out.layers, out.polys);
  }
  require(ok, pass_explicit_null ? "explicit-null decomp failed" : "legacy-default decomp failed");
  return out;
}

struct SolveOutcome {
  int valid_assignments{0};
  double objective{0.0};
  bool optimal{false};
};

SolveOutcome solveLayers(const Parameters& par, const std::vector<std::vector<LinearConstraint3D>>& layers) {
  SolverGurobi solver;
  solver.setPlannerName("SANDO");
  solver.initializeSolver(par);
  RobotState start, goal;
  start.setPos(0.0, 0.0, 1.0);
  goal.setPos(3.0, 1.0, 2.0);
  solver.setX0(start);
  solver.setXf(goal);
  solver.setT0(0.0);
  solver.setInitialDt(1.0);
  solver.setPolytopesTimeLayered(layers);

  const double factor = 1.0;
  auto geometry = solver.getPlanningGeometry(factor);
  SolveOutcome out;
  out.valid_assignments = static_cast<int>(sando_learning::enumerateAssignments(geometry).size());

  bool error = false;
  double milliseconds = 0.0;
  out.optimal = solver.generateNewTrajectory(error, milliseconds, factor) && !error;
  require(out.optimal, "tiny instance MIQP was not optimal");
  out.objective = solver.getObjectiveValue();
  return out;
}

}  // namespace

int main() {
  try {
    const Parameters par = tinyParams();
    HGPManager hgp;
    hgp.setParameters(par);
    // Install planning map so classes=nullptr takes the live-map branch in obstacle_to_vec.
    hgp.setupHGPPlanner("JPS", false, par.res, par.v_max, par.a_max, par.j_max, 1000, 10000, 0.0, 0.0,
                        100.0, 0.0, 0, 0.5, 0.0);

    vec_Vecf<3> path;
    path.emplace_back(0.0, 0.0, 1.0);
    path.emplace_back(3.0, 1.0, 2.0);

    // Nearby static cloud + one dynamic obstacle (same map/path/time for both entries).
    vec_Vec3f base;
    base.emplace_back(1.5, 0.4, 1.4);
    base.emplace_back(1.8, 0.6, 1.5);
    vec_Vecf<3> obst_pos;
    obst_pos.emplace_back(1.2, 1.0, 1.5);
    vec_Vecf<3> obst_bbox;
    obst_bbox.emplace_back(0.3, 0.3, 0.3);

    const double segment_dt = sando_time::segmentDuration(1.0, par.dc, 1.0);
    std::vector<double> times;
    times.reserve(static_cast<std::size_t>(par.num_N));
    for (int i = 0; i < par.num_N; ++i) times.push_back((i + 1) * segment_dt);

    // obstacle_to_vec stability on the live-map (null-class) path.
    vec_Vec3f inflated_a = base;
    vec_Vec3f inflated_b = base;
    hgp.obstacle_to_vec(inflated_a, obst_pos, obst_bbox, times.back(), nullptr, nullptr);
    hgp.obstacle_to_vec(inflated_b, obst_pos, obst_bbox, times.back(), nullptr, nullptr);
    require(sameCloud(inflated_a, inflated_b), "null-class obstacle_to_vec not deterministic");
    require(inflated_a.size() > base.size(), "null-class live-map path did not inflate obstacles");

    EllipsoidDecomp3D ellip_legacy;
    EllipsoidDecomp3D ellip_null;
    EllipsoidDecomp3D ellip_null2;
    const auto legacy = runDecomp(hgp, ellip_legacy, path, base, obst_pos, obst_bbox, times, false);
    const auto explicit_null =
        runDecomp(hgp, ellip_null, path, base, obst_pos, obst_bbox, times, true);
    const auto explicit_null_again =
        runDecomp(hgp, ellip_null2, path, base, obst_pos, obst_bbox, times, true);

    require(polyhedronCount(legacy.polys) == polyhedronCount(explicit_null.polys),
            "polyhedron count mismatch: legacy vs explicit nullptr");
    require(hyperplaneCount(legacy.layers) == hyperplaneCount(explicit_null.layers),
            "hyperplane count mismatch: legacy vs explicit nullptr");
    require(sameLayers(legacy.layers, explicit_null.layers),
            "constraint mismatch: legacy default args vs explicit nullptr");
    require(sameLayers(explicit_null.layers, explicit_null_again.layers),
            "explicit-nullptr decomp not deterministic across consecutive calls");

    const auto solve_legacy = solveLayers(par, legacy.layers);
    const auto solve_null = solveLayers(par, explicit_null.layers);
    require(solve_legacy.valid_assignments == solve_null.valid_assignments,
            "valid assignment count mismatch");
    require(std::abs(solve_legacy.objective - solve_null.objective) <=
                1e-8 * std::max(1.0, std::abs(solve_legacy.objective)),
            "final objective mismatch");

    std::cout << "null_class_decomp_probe passed"
              << " polys=" << polyhedronCount(legacy.polys)
              << " planes=" << hyperplaneCount(legacy.layers)
              << " assignments=" << solve_legacy.valid_assignments
              << " objective=" << solve_legacy.objective << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "null_class_decomp_probe: " << error.what() << '\n';
    return 1;
  }
}
