#include <sando/frozen_planning_observation.hpp>
#include <sando/instance_reservoir.hpp>
#include <sando/segment_time.hpp>

#include <cassert>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>

namespace {
using namespace sando_learning;
using sando_ampl::GRB_BINARY;

FrozenPlanningObservation makeObservation(const std::string& request_id) {
  FrozenPlanningObservation observation;
  observation.observation_id = request_id;
  observation.request_id = request_id;
  observation.source_id = "source";
  observation.config_id = "config";
  observation.scene_id = "scene";
  observation.episode_id = "episode";
  observation.start = {0., 0., 1., 0.1, 0., 0., 0., 0., 0.};
  observation.goal = {2., 0., 1., 0., 0., 0., 0., 0., 0.};
  observation.A_time = 1.1;
  observation.planning_start_time = 1.0;
  observation.observation_time = 0.9;
  observation.n = 5;
  observation.initial_dt = 0.1;
  observation.dc = 0.05;
  observation.v_max = 3;
  observation.a_max = 5;
  observation.j_max = 8;
  observation.jerk_smooth_weight = 1;
  observation.environment_assumption = "dynamic";
  observation.sim_env = "gazebo";
  observation.res = 0.15;
  observation.factor_hgp = 1.0;
  observation.map_origin = {-3., -3., 0.};
  observation.map_dim = {40, 40, 20};
  observation.z_min = 0;
  observation.z_max = 5;
  observation.drone_radius = 0.3;
  observation.sfc_size = {2.0, 2.0, 1.5};
  observation.obst_max_vel = 1.0;
  observation.map_bounds = {-10, 10, -10, 10, 0, 5};
  observation.global_path = {{0., 0., 1.}, {2., 0., 1.}};
  observation.obst_pos = {{1.0, 0.2, 1.0}};
  observation.obst_bbox = {{0.4, 0.4, 1.0}};
  observation.visible_map.points = {{0.15, 0.0, 1.0}, {0.30, 0.0, 1.0}};
  observation.visible_map.classes = {kMapClassOccupied, kMapClassUnknown};
  observation.visible_map.voxel_indices = {{21, 20, 6}, {22, 20, 6}};
  return observation;
}

PlanningInstance makeInstance(const std::string& request_id) {
  PlanningInstance instance;
  instance.scene_id = "scene";
  instance.episode_id = "episode";
  instance.request_id = request_id;
  instance.source_id = "source";
  instance.config_id = "config";
  instance.factor = 1.5;
  instance.initial_dt = .1;
  instance.dc = .05;
  instance.segment_dt = sando_time::segmentDuration(instance.initial_dt, instance.dc, instance.factor);
  instance.start = {0., 0., 1., 0., 0., 0., 0., 0., 0.};
  instance.goal = {1., 1., 2., 0., 0., 0., 0., 0., 0.};
  instance.map_bounds = {-2., 2., -2., 2., 0., 4.};
  instance.corridors.resize(5);
  instance.valid_mask.resize(5);
  instance.assignment_variables.resize(5);
  for (int t = 0; t < 5; ++t) {
    instance.corridors[t] = {{{{{1., 0., 0., 2.}}}, {{{0., 1., 0., 2.}}}}};
    instance.valid_mask[t] = {true, true};
    instance.assignment_variables[t] = {static_cast<std::uint64_t>(t * 2 + 1),
                                        static_cast<std::uint64_t>(t * 2 + 2)};
  }
  for (int id = 1; id <= 10; ++id)
    instance.model.variables.push_back({static_cast<std::uint64_t>(id), "s", 0., 1., 0., GRB_BINARY});
  for (auto& axis : instance.coefficients)
    for (int i = 0; i < 20; ++i) axis.push_back({static_cast<double>(i), {}, {}});
  instance.runtime.time_limit = 30.;
  return instance;
}

}  // namespace

int main() {
  auto observation = makeObservation("7");
  const auto encoded = frozenObservationToJson(observation);
  const auto decoded = frozenObservationFromJson(encoded);
  assert(decoded.visible_map.classes[1] == kMapClassUnknown);
  assert(mapContentSha256(decoded) == encoded.at("map_sha256").get<std::string>());
  assert(observationContentSha256(decoded) == encoded.at("observation_sha256").get<std::string>());
  const auto reference = frozenObservationReference(decoded);
  assert(reference.at("obst_pos").at(0).at(0) == 1.0);
  assert(reference.at("visible_map").at("kind") == "request_observation");
  assert(reference.at("visible_map").at("point_count") == 2);

  auto mutated = observation;
  mutated.visible_map.classes[1] = kMapClassOccupied;
  assert(mapContentSha256(mutated) != mapContentSha256(observation));

  bool failed = false;
  try {
    auto bad = observation;
    bad.visible_map.classes.push_back(0);
    validateFrozenObservation(bad);
  } catch (const std::invalid_argument&) {
    failed = true;
  }
  assert(failed);

  const auto root = std::filesystem::temp_directory_path() /
                    ("sando_obs_" + std::to_string(
                        std::chrono::steady_clock::now().time_since_epoch().count()));
  std::filesystem::create_directories(root);
  try {
    InstanceReservoir reservoir(root / "instances.jsonl", 2, 7,
                                {{"scene_id", "scene"},
                                 {"episode_id", "episode"},
                                 {"source_id", "source"},
                                 {"config_id", "config"}});
    auto first = makeInstance("1");
    auto second = makeInstance("2");
    auto third = makeInstance("3");
    reservoir.ingest(first, frozenObservationToJson(makeObservation("1")));
    reservoir.ingest(second, frozenObservationToJson(makeObservation("2")));
    reservoir.ingest(third, frozenObservationToJson(makeObservation("3")));
    reservoir.flush();
    const auto obs_dir = reservoir.observationDir();
    std::size_t files = 0;
    for (const auto& entry : std::filesystem::directory_iterator(obs_dir)) {
      if (!entry.is_regular_file()) continue;
      ++files;
      std::ifstream in(entry.path());
      const auto loaded = frozenObservationFromJson(nlohmann::json::parse(in));
      assert(loaded.request_id == entry.path().stem().string());
    }
    assert(files == reservoir.retained());
    std::ifstream lines(root / "instances.jsonl");
    std::string line;
    while (std::getline(lines, line)) {
      if (line.empty()) continue;
      const auto instance = fromJson(nlohmann::json::parse(line));
      assert(!instance.outcome.contains("visible_map") || instance.outcome["visible_map"].is_null());
    }
    std::filesystem::remove_all(root);
    return 0;
  } catch (...) {
    std::filesystem::remove_all(root);
    throw;
  }
}
