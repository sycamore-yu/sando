#include <sando/frozen_planning_observation.hpp>
#include <sando/reconstruct_planning_request.hpp>
#include <sando/segment_time.hpp>

#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {
using namespace sando_learning;

void require(bool value, const std::string& message) {
  if (!value) throw std::runtime_error(message);
}

FrozenPlanningObservation emptyObservation() {
  FrozenPlanningObservation observation;
  observation.observation_id = "reconstruct-empty";
  observation.request_id = "reconstruct-empty";
  observation.source_id = "source";
  observation.config_id = "config";
  observation.scene_id = "scene";
  observation.episode_id = "episode";
  observation.start = {0., 0., 1., 0., 0., 0., 0., 0., 0.};
  observation.goal = {3., 1., 2., 0., 0., 0., 0., 0., 0.};
  observation.A_time = 0.0;
  observation.n = 5;
  observation.initial_dt = 1.0;
  observation.dc = 1.0;
  observation.v_max = 20;
  observation.a_max = 40;
  observation.j_max = 100;
  observation.jerk_smooth_weight = 1;
  observation.environment_assumption = "dynamic";
  observation.sim_env = "fake_sim";
  observation.norm = "Linf";
  observation.planner = "SANDO";
  observation.res = 0.3;
  observation.factor_hgp = 1.0;
  observation.map_origin = {-2., -3., -1.};
  observation.map_dim = {24, 24, 18};
  observation.z_min = -1;
  observation.z_max = 4;
  observation.drone_radius = 0.2;
  observation.sfc_size = {4.0, 4.0, 4.0};
  observation.obst_max_vel = 1.0;
  observation.map_bounds = {-2., 5., -3., 4., -1., 4.};
  observation.global_path = {{0., 0., 1.}, {3., 1., 2.}};
  return observation;
}

bool sameCorridors(const PlanningInstance& left, const PlanningInstance& right) {
  if (left.corridors.size() != right.corridors.size()) return false;
  for (std::size_t t = 0; t < left.corridors.size(); ++t) {
    if (left.corridors[t].size() != right.corridors[t].size()) return false;
    for (std::size_t p = 0; p < left.corridors[t].size(); ++p) {
      const auto& a = left.corridors[t][p].planes;
      const auto& b = right.corridors[t][p].planes;
      if (a.size() != b.size()) return false;
      for (std::size_t r = 0; r < a.size(); ++r)
        for (int k = 0; k < 4; ++k)
          if (std::abs(a[r][k] - b[r][k]) > 1e-9) return false;
    }
  }
  return true;
}

}  // namespace

int main() {
  try {
    const auto observation = emptyObservation();
    const auto first = solveReconstructedRequest(observation, 1.0);
    require(first.geometry.ok, "empty-map reconstruction failed: " + first.error);
    require(std::abs(first.geometry.segment_dt - 2.0) < 1e-12, "f=1.0 segment_dt mismatch");
    require(std::abs(first.geometry.T - 10.0) < 1e-12, "f=1.0 horizon mismatch");
    require(first.status == "optimal", "empty-map f=1.0 was not optimal: " + first.status + " " + first.error);
    require(first.solver_kind == "miqp", "reconstruction did not use original MIQP");
    require(first.attempt_count == 1, "original MIQP attempt count was not 1");
    require(first.objective.is_number(), "optimal solve lost the objective");
    require(first.residuals.is_object() && first.residuals.value("valid", false),
            "optimal solve failed residual check");

    const auto first_again = solveReconstructedRequest(observation, 1.0);
    require(first_again.status == first.status, "original-f ressolve status changed");
    require(first.objective.is_number() && first_again.objective.is_number(),
            "original-f ressolve lost the objective");
    require(std::abs(first_again.objective.get<double>() - first.objective.get<double>()) <=
                1e-8 * std::max(1.0, std::abs(first.objective.get<double>())),
            "original-f ressolve objective mismatch");
    require(sameCorridors(first.geometry.instance, first_again.geometry.instance),
            "original-f ressolve rebuilt different corridors");

    const auto second = buildGeometryForFactor(observation, 1.0);
    require(second.ok, "second geometry rebuild failed");
    require(sameCorridors(first.geometry.instance, second.instance),
            "same observation/factor rebuilt different corridors");

    const auto off_grid = solveReconstructedRequest(observation, 1.37);
    const double expected_dt = sando_time::segmentDuration(1.0, 1.0, 1.37);
    require(std::abs(off_grid.geometry.segment_dt - expected_dt) < 1e-12, "f=1.37 segment_dt mismatch");
    require(off_grid.geometry.layer_end_times.size() == 5, "f=1.37 layer count mismatch");
    require(off_grid.status == "optimal" || off_grid.status == "infeasible" ||
                off_grid.status == "timeout_or_unknown" || off_grid.status == "numerical_error",
            "f=1.37 did not produce a solver status: " + off_grid.status + " " + off_grid.error);
    require(off_grid.status != "rebuild_error", "f=1.37 failed to rebuild corridors");
    require(off_grid.status == "optimal", "empty-map f=1.37 was not optimal: " + off_grid.status);

    auto occupied = observation;
    occupied.visible_map.points = {{1.5, 1.2, 1.5}};
    occupied.visible_map.classes = {kMapClassOccupied};
    occupied.visible_map.voxel_indices = {{12, 14, 8}};
    auto unknown = occupied;
    unknown.visible_map.classes = {kMapClassUnknown};
    const auto occupied_geom = buildGeometryForFactor(occupied, 1.0);
    const auto unknown_geom = buildGeometryForFactor(unknown, 1.0);
    require(occupied_geom.ok && unknown_geom.ok, "classified map reconstruction failed");
    require(!sameCorridors(occupied_geom.instance, unknown_geom.instance),
            "occupied vs unknown classes produced identical corridors");

    auto obst_a = observation;
    obst_a.obst_pos = {{1.5, 1.2, 1.5}};
    obst_a.obst_bbox = {{0.3, 0.3, 0.3}};
    auto obst_b = obst_a;
    obst_b.obst_pos = {{8.0, 8.0, 1.5}};
    const auto geom_a = buildGeometryForFactor(obst_a, 1.0);
    const auto geom_b = buildGeometryForFactor(obst_b, 1.0);
    require(geom_a.ok && geom_b.ok, "request obst reconstruction failed");
    require(!sameCorridors(geom_a.instance, geom_b.instance),
            "request obst_pos did not change reconstructed corridors");

    auto bad = observation;
    bad.n = 6;
    bool rejected = false;
    try {
      buildGeometryForFactor(bad, 1.0);
    } catch (const std::invalid_argument&) {
      rejected = true;
    }
    require(rejected, "n=6 reconstruction was not rejected");

    std::cout << "reconstruct_request_probe passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "reconstruct_request_probe: " << error.what() << '\n';
    return 1;
  }
}
