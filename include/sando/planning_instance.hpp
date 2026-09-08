#pragma once

#include <sando/ampl_model.hpp>
#include <nlohmann/json.hpp>

#include <array>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace sando_learning {

using Assignment = std::vector<int>;
using Values = std::map<std::uint64_t, double>;

struct Corridor {
  // Every row is [normal_x, normal_y, normal_z, upper_bound]; empty means invalid.
  std::vector<std::array<double, 4>> planes;
};

struct PlanningInstance {
  int schema_version{1};
  int n{5};
  std::string norm{"Linf"};
  std::string planner{"SANDO"};
  std::string scene_id, episode_id, request_id, factor_id, source_id, config_id;
  double factor{}, initial_dt{}, dc{}, segment_dt{};
  double planning_start_time{}, observation_time{}, t0{};
  // Position, velocity, acceleration; each in x,y,z order.
  std::array<double, 9> start{}, goal{};
  // xmin,xmax,ymin,ymax,zmin,zmax.
  std::array<double, 6> map_bounds{};
  std::vector<std::vector<Corridor>> corridors;
  std::vector<std::vector<bool>> valid_mask;
  std::vector<std::vector<std::uint64_t>> assignment_variables;
  // Cubic coefficients a,b,c,d per segment, one flattened vector per axis.
  std::array<std::vector<sando_ampl::ExpressionSnapshot>, 3> coefficients;
  sando_ampl::ModelSnapshot model;
  sando_ampl::RuntimeParameters runtime;
  nlohmann::json outcome = nlohmann::json::object();
};

struct Residuals {
  bool valid{false};
  double bounds{}, constraints{}, integrality{}, objective{};
  std::string reason;
};

// The production adapter's existing absolute feasibility tolerance.
constexpr double kResidualTolerance = 2e-6;

void validateInstance(const PlanningInstance&, bool require_model = true);
std::vector<Assignment> enumerateAssignments(const PlanningInstance&);
void validateAssignment(const PlanningInstance&, const Assignment&);
sando_ampl::ModelSnapshot fixIntegers(const sando_ampl::ModelSnapshot&, const Values&);
sando_ampl::ModelSnapshot fixAssignment(const PlanningInstance&, const Assignment&);
double evaluate(const sando_ampl::ExpressionSnapshot&, const Values&);
Residuals checkResiduals(const sando_ampl::ModelSnapshot&, const Values&,
                         std::optional<double> objective = std::nullopt);
Assignment recoverAssignment(const PlanningInstance&, const Values&);
std::array<std::vector<double>, 3> recoverCoefficients(const PlanningInstance&, const Values&);
nlohmann::json toJson(const PlanningInstance&);
PlanningInstance fromJson(const nlohmann::json&);
nlohmann::json modelToJson(const sando_ampl::ModelSnapshot&);
sando_ampl::ModelSnapshot modelFromJson(const nlohmann::json&);
nlohmann::json residualsToJson(const Residuals&);

}  // namespace sando_learning
