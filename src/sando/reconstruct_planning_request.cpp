#include <sando/reconstruct_planning_request.hpp>
#include <sando/gurobi_solver.hpp>
#include <sando/segment_time.hpp>
#include "hgp/hgp_manager.hpp"

#include <decomp_util/ellipsoid_decomp.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <memory>
#include <stdexcept>
#include <string>
#include <thread>

namespace sando_learning {
namespace {

[[noreturn]] void fail(const std::string& message) { throw std::invalid_argument(message); }

void requireSupported(const FrozenPlanningObservation& observation) {
  validateFrozenObservation(observation);
  if (observation.n != 5) fail("reconstruction currently requires n=5");
  if (observation.planner != "SANDO") fail("reconstruction currently requires SANDO");
  if (observation.norm != "Linf") fail("reconstruction currently requires Linf");
}

vec_Vecf<3> toPath(const std::vector<std::array<double, 3>>& points) {
  vec_Vecf<3> out;
  out.reserve(points.size());
  for (const auto& point : points) out.emplace_back(point[0], point[1], point[2]);
  return out;
}

vec_Vec3f toCloud(const std::vector<std::array<double, 3>>& points) {
  vec_Vec3f out;
  out.reserve(points.size());
  for (const auto& point : points) out.emplace_back(point[0], point[1], point[2]);
  return out;
}

std::vector<Veci<3>> voxelIndices(const FrozenPlanningObservation& observation) {
  std::vector<Veci<3>> out;
  const auto& classified = observation.visible_map;
  const double res = observation.factor_hgp * observation.res;
  out.reserve(classified.points.size());
  if (classified.voxel_indices.size() == classified.points.size()) {
    for (const auto& idx : classified.voxel_indices) {
      Veci<3> voxel;
      voxel << idx[0], idx[1], idx[2];
      out.push_back(voxel);
    }
    return out;
  }
  for (const auto& point : classified.points) {
    Veci<3> voxel;
    voxel << static_cast<int>(std::llround(point[0] / res)),
        static_cast<int>(std::llround(point[1] / res)),
        static_cast<int>(std::llround(point[2] / res));
    out.push_back(voxel);
  }
  return out;
}

RobotState stateFrom9(const std::array<double, 9>& value) {
  RobotState state;
  state.setPos(value[0], value[1], value[2]);
  state.setVel(value[3], value[4], value[5]);
  state.setAccel(value[6], value[7], value[8]);
  return state;
}

int countValidAssignments(const PlanningInstance& instance) {
  try {
    return static_cast<int>(enumerateAssignments(instance).size());
  } catch (const std::exception&) {
    int count = 0;
    for (const auto& layer : instance.valid_mask)
      for (bool valid : layer)
        if (valid) ++count;
    return count;
  }
}

std::string classifyStatus(bool rebuild_ok, bool solver_error, bool solved, int status) {
  if (!rebuild_ok) return "rebuild_error";
  if (solver_error) return "numerical_error";
  if (solved && status == sando_ampl::GRB_OPTIMAL) return "optimal";
  if (status == sando_ampl::GRB_INFEASIBLE || status == sando_ampl::GRB_INF_OR_UNBD)
    return "infeasible";
  if (status == sando_ampl::GRB_NUMERIC) return "numerical_error";
  return "timeout_or_unknown";
}

Parameters makeParameters(const FrozenPlanningObservation& observation) {
  Parameters par{};
  par.num_N = observation.n;
  par.num_P = std::max(1, static_cast<int>(observation.global_path.size()) - 1);
  par.dc = observation.dc;
  par.dynamic_constraint_type = observation.norm;
  par.v_max = observation.v_max;
  par.a_max = observation.a_max;
  par.j_max = observation.j_max;
  par.jerk_smooth_weight = observation.jerk_smooth_weight;
  par.environment_assumption = observation.environment_assumption;
  par.sim_env = observation.sim_env;
  par.res = observation.res;
  par.factor_hgp = observation.factor_hgp;
  par.x_min = observation.map_bounds[0];
  par.x_max = observation.map_bounds[1];
  par.y_min = observation.map_bounds[2];
  par.y_max = observation.map_bounds[3];
  par.z_min = observation.z_min;
  par.z_max = observation.z_max;
  par.drone_radius = observation.drone_radius;
  par.sfc_size = observation.sfc_size;
  par.use_shrinked_box = observation.use_shrinked_box;
  par.shrinked_box_size = observation.shrinked_box_size;
  par.obst_max_vel = observation.obst_max_vel;
  par.obst_position_error = observation.obst_position_error;
  par.inflate_unknown_boundary = observation.inflate_unknown_boundary;
  par.using_variable_elimination = true;
  par.max_gurobi_comp_time_sec = 30.0;
  par.horizon = sando_time::horizonDuration(
      observation.n, observation.initial_dt, observation.dc, 2.5);
  par.factor_initial = 1.0;
  par.factor_final = 2.5;
  par.factor_constant_step_size = 0.25;
  par.max_dist_vertexes = 2.0;
  par.w_max = 1.0;
  par.w_max_yawing = 1.0;
  par.debug_verbose = false;
  return par;
}

struct PreparedProblem {
  ReconstructedGeometry geometry;
  std::unique_ptr<SolverGurobi> solver;
};

PreparedProblem prepare(const FrozenPlanningObservation& observation, double factor) {
  requireSupported(observation);
  if (!std::isfinite(factor) || factor <= 0.0) fail("invalid factor");

  PreparedProblem prepared;
  auto& geometry = prepared.geometry;
  geometry.factor = factor;
  geometry.d0 = sando_time::baseDuration(observation.initial_dt, observation.dc);
  geometry.segment_dt =
      sando_time::segmentDuration(observation.initial_dt, observation.dc, factor);
  geometry.T = sando_time::horizonDuration(
      observation.n, observation.initial_dt, observation.dc, factor);
  geometry.layer_end_times.reserve(static_cast<std::size_t>(observation.n));
  for (int i = 0; i < observation.n; ++i)
    geometry.layer_end_times.push_back((static_cast<double>(i) + 1.0) * geometry.segment_dt);

  const Parameters par = makeParameters(observation);
  HGPManager hgp;
  hgp.setParameters(par);
  EllipsoidDecomp3D ellip;

  const auto path = toPath(observation.global_path);
  const auto base = toCloud(observation.visible_map.points);
  const auto obst_pos = toPath(observation.obst_pos);
  const auto obst_bbox = toPath(observation.obst_bbox);
  const auto classes = observation.visible_map.classes;
  const auto voxels = voxelIndices(observation);
  const std::vector<std::uint8_t>* class_ptr = classes.empty() ? nullptr : &classes;
  const std::vector<Veci<3>>* voxel_ptr =
      (class_ptr && voxels.size() == classes.size()) ? &voxels : nullptr;

  prepared.solver = std::make_unique<SolverGurobi>();
  const int cores = std::max(1, static_cast<int>(std::thread::hardware_concurrency()));
  prepared.solver->setPlannerName("SANDO");
  prepared.solver->setGurobiThreads(cores);
  prepared.solver->initializeSolver(par);
  prepared.solver->setX0(stateFrom9(observation.start));
  prepared.solver->setXf(stateFrom9(observation.goal));
  prepared.solver->setT0(observation.A_time);
  prepared.solver->setInitialDt(observation.initial_dt);

  const bool spatial = observation.environment_assumption == "static" ||
                       observation.environment_assumption == "dynamic_worst_case";
  const auto started = std::chrono::steady_clock::now();
  bool ok = false;
  if (spatial) {
    const std::size_t P = path.size() >= 2 ? path.size() - 1 : 0;
    std::vector<double> seg_end_times;
    if (observation.environment_assumption == "dynamic_worst_case")
      seg_end_times.assign(P, geometry.T);
    else {
      seg_end_times.reserve(P);
      for (std::size_t i = 0; i < P; ++i)
        seg_end_times.push_back((static_cast<double>(i) + 1.0) * geometry.segment_dt);
    }
    std::vector<LinearConstraint3D> constraints;
    vec_E<Polyhedron<3>> poly_out;
    ok = hgp.cvxEllipsoidDecomp(ellip, path, base, obst_pos, obst_bbox, seg_end_times, constraints,
                                poly_out, class_ptr, voxel_ptr);
    if (ok) prepared.solver->setPolytopes(constraints);
  } else {
    std::vector<std::vector<LinearConstraint3D>> layered;
    std::vector<vec_E<Polyhedron<3>>> poly_out;
    ok = hgp.cvxEllipsoidDecompTimeLayered(ellip, path, base, obst_pos, obst_bbox,
                                           geometry.layer_end_times, layered, poly_out, class_ptr,
                                           voxel_ptr);
    if (ok) prepared.solver->setPolytopesTimeLayered(layered);
  }
  geometry.cvx_decomp_ms =
      std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();
  if (!ok) {
    geometry.ok = false;
    geometry.error = "corridor decomposition failed";
    return prepared;
  }
  geometry.instance = prepared.solver->getPlanningGeometry(factor);
  geometry.valid_assignment_count = countValidAssignments(geometry.instance);
  geometry.ok = true;
  return prepared;
}

nlohmann::json coefficientJson(const PlanningInstance& instance, const Values& values) {
  nlohmann::json axes = nlohmann::json::array();
  const auto recovered = recoverCoefficients(instance, values);
  for (const auto& axis : recovered) axes.push_back(axis);
  return axes;
}

}  // namespace

Parameters parametersFromObservation(const FrozenPlanningObservation& observation) {
  requireSupported(observation);
  return makeParameters(observation);
}

ReconstructedGeometry buildGeometryForFactor(
    const FrozenPlanningObservation& observation, double factor) {
  return prepare(observation, factor).geometry;
}

ReconstructedSolve solveReconstructedRequest(
    const FrozenPlanningObservation& observation, double factor) {
  const auto wall_started = std::chrono::steady_clock::now();
  ReconstructedSolve result;
  PreparedProblem prepared;
  try {
    prepared = prepare(observation, factor);
  } catch (const std::exception& error) {
    result.status = "rebuild_error";
    result.error = error.what();
    result.wall_ms = std::chrono::duration<double, std::milli>(
                         std::chrono::steady_clock::now() - wall_started)
                         .count();
    return result;
  }
  result.geometry = prepared.geometry;
  if (!prepared.geometry.ok || !prepared.solver) {
    result.status = "rebuild_error";
    result.error = prepared.geometry.error;
    result.wall_ms = std::chrono::duration<double, std::milli>(
                         std::chrono::steady_clock::now() - wall_started)
                         .count();
    return result;
  }

  bool error = false;
  double backend_ms = 0.0;
  bool solved = false;
  try {
    result.attempt_count = 1;
    solved = prepared.solver->generateNewTrajectory(error, backend_ms, factor);
  } catch (const std::exception& exception) {
    result.status = "numerical_error";
    result.error = exception.what();
    result.backend_ms = backend_ms;
    result.wall_ms = std::chrono::duration<double, std::milli>(
                         std::chrono::steady_clock::now() - wall_started)
                         .count();
    return result;
  }
  result.backend_ms = backend_ms;

  int status = sando_ampl::GRB_INTERRUPTED;
  try {
    const auto instance = prepared.solver->getPlanningInstance(factor);
    result.geometry.instance = instance;
    result.geometry.valid_assignment_count = countValidAssignments(instance);
    if (instance.outcome.contains("status") && instance.outcome["status"].is_number_integer())
      status = instance.outcome["status"].get<int>();
    result.objective = instance.outcome.value("objective", nlohmann::json(nullptr));
    result.residuals = instance.outcome.value("residuals", nlohmann::json(nullptr));
    result.assignment = prepared.solver->getLastAssignment();
    if (solved && instance.outcome.contains("solution_values") &&
        instance.outcome["solution_values"].is_object()) {
      Values values;
      for (auto it = instance.outcome["solution_values"].begin();
           it != instance.outcome["solution_values"].end(); ++it)
        values[static_cast<std::uint64_t>(std::stoull(it.key()))] = it.value().get<double>();
      result.coefficients = coefficientJson(instance, values);
    }
  } catch (const std::exception& exception) {
    if (result.error.empty()) result.error = exception.what();
  }

  result.status = classifyStatus(true, error, solved, status);
  result.wall_ms = std::chrono::duration<double, std::milli>(
                       std::chrono::steady_clock::now() - wall_started)
                       .count();
  return result;
}

nlohmann::json reconstructedSolveToJson(const ReconstructedSolve& result) {
  nlohmann::json corridor = nlohmann::json::object();
  const auto& instance = result.geometry.instance;
  int plane_count = 0;
  for (const auto& layer : instance.corridors)
    for (const auto& corridor_item : layer)
      plane_count += static_cast<int>(corridor_item.planes.size());
  corridor["N"] = instance.n;
  corridor["P"] = instance.corridors.empty() ? 0 : instance.corridors.front().size();
  corridor["plane_count"] = plane_count;
  corridor["valid_assignment_count"] = result.geometry.valid_assignment_count;
  return {{"kind", "sando_reconstructed_request"},
          {"schema_version", 1},
          {"factor", result.geometry.factor},
          {"d0", result.geometry.d0},
          {"segment_dt", result.geometry.segment_dt},
          {"T", result.geometry.T},
          {"layer_end_times", result.geometry.layer_end_times},
          {"status", result.status},
          {"solver_kind", result.solver_kind},
          {"attempt_count", result.attempt_count},
          {"objective", result.objective},
          {"residuals", result.residuals},
          {"assignment", result.assignment},
          {"coefficients", result.coefficients},
          {"wall_ms", result.wall_ms},
          {"backend_ms", result.backend_ms},
          {"cvx_decomp_ms", result.geometry.cvx_decomp_ms},
          {"corridor", corridor},
          {"error", result.error}};
}

}  // namespace sando_learning
