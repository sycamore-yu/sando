#pragma once

#include <nlohmann/json.hpp>

#include <array>
#include <cstdint>
#include <string>
#include <vector>

namespace sando_learning {

// Occupied/unknown labels for the exact point list consumed by corridor
// decomposition.  0 = occupied, 1 = unknown.  Other values are rejected.
constexpr std::uint8_t kMapClassOccupied = 0;
constexpr std::uint8_t kMapClassUnknown = 1;

struct ClassifiedMap {
  std::vector<std::array<double, 3>> points;
  std::vector<std::uint8_t> classes;
  std::vector<std::array<int, 3>> voxel_indices;
};

struct FrozenPlanningObservation {
  int schema_version{1};
  std::string kind{"sando_frozen_planning_observation"};
  std::string observation_id;
  std::string source_id, config_id, scene_id, episode_id, request_id;
  std::array<double, 9> start{}, goal{};
  double A_time{0.0};
  double planning_start_time{0.0};
  double observation_time{0.0};
  int n{5};
  double initial_dt{0.0};
  double dc{0.0};
  double v_max{0.0};
  double a_max{0.0};
  double j_max{0.0};
  double jerk_smooth_weight{0.0};
  std::string environment_assumption;
  std::string sim_env;
  std::string norm{"Linf"};
  std::string planner{"SANDO"};
  double res{0.0};
  double factor_hgp{0.0};
  std::array<double, 3> map_origin{};
  std::array<int, 3> map_dim{};
  double z_min{0.0};
  double z_max{0.0};
  double drone_radius{0.0};
  std::vector<double> sfc_size;
  bool use_shrinked_box{false};
  double shrinked_box_size{0.0};
  double obst_max_vel{0.0};
  double obst_position_error{0.0};
  bool inflate_unknown_boundary{true};
  std::array<double, 6> map_bounds{};
  std::vector<std::array<double, 3>> global_path;
  std::vector<std::array<double, 3>> obst_pos;
  std::vector<std::array<double, 3>> obst_bbox;
  ClassifiedMap visible_map;
};

void validateFrozenObservation(const FrozenPlanningObservation& observation);
std::string sha256Hex(const std::string& text);
std::string mapContentSha256(const FrozenPlanningObservation& observation);
std::string observationContentSha256(const FrozenPlanningObservation& observation);
nlohmann::json frozenObservationToJson(const FrozenPlanningObservation& observation);
FrozenPlanningObservation frozenObservationFromJson(const nlohmann::json& value);
nlohmann::json frozenObservationReference(const FrozenPlanningObservation& observation);

}  // namespace sando_learning
