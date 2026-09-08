#include <sando/planning_instance.hpp>
#include <sando/segment_time.hpp>

#include <cassert>
#include <cmath>
#include <memory>
#include <limits>
#include <stdexcept>

namespace {
using namespace sando_ampl;
using namespace sando_learning;

template <class F>
bool throws(F&& function) {
  try {
    function();
  } catch (const std::invalid_argument&) {
    return true;
  }
  return false;
}

PlanningInstance make_instance() {
  PlanningInstance instance;
  instance.scene_id = "scene";
  instance.episode_id = "episode";
  instance.request_id = "request";
  instance.factor_id = "factor";
  instance.source_id = "source";
  instance.config_id = "config";
  instance.factor = 1.5;
  instance.initial_dt = .1;
  instance.dc = .05;
  instance.segment_dt = sando_time::segmentDuration(instance.initial_dt, instance.dc, instance.factor);
  instance.planning_start_time = 10.;
  instance.observation_time = 10.1;
  instance.t0 = 10.1;
  instance.start = {0., 0., 1., 0., 0., 0., 0., 0., 0.};
  instance.goal = {1., 1., 2., 0., 0., 0., 0., 0., 0.};
  instance.map_bounds = {-2., 2., -2., 2., 0., 4.};
  instance.corridors.resize(5);
  instance.valid_mask.resize(5);
  instance.assignment_variables.resize(5);
  for (int t = 0; t < 5; ++t) {
    instance.corridors[t] = {{{{{1., 0., 0., 2.}}}, {{{0., 1., 0., 2.}}}}};
    instance.valid_mask[t] = {true, true};
    instance.assignment_variables[t] = {static_cast<std::uint64_t>(t * 2 + 1), static_cast<std::uint64_t>(t * 2 + 2)};
  }

  for (int id = 1; id <= 10; ++id)
    instance.model.variables.push_back({static_cast<std::uint64_t>(id), "s", 0., 1., 0., GRB_BINARY});
  instance.model.variables.push_back({11, "x", -2., 2., 0., GRB_CONTINUOUS});
  instance.model.objective = {0., {{11, 1.}, {1, 2.}}, {{11, 11, 1.}, {1, 11, 3.}}};
  instance.model.constraints.push_back(
      {100, "mixed", ExpressionSnapshot{0., {{1, 1.}}, {{1, 11, 1.}}}, GRB_LESS_EQUAL, 1., true, false, 0, 0});
  instance.model.constraints.push_back(
      {101, "active", ExpressionSnapshot{0., {{11, 1.}}, {}}, GRB_GREATER_EQUAL, 0., false, true, 1, 1});
  instance.model.constraints.push_back(
      {102, "inactive", ExpressionSnapshot{0., {{11, 1.}}, {}}, GRB_LESS_EQUAL, 2., false, true, 2, 1});
  for (auto& axis : instance.coefficients) {
    for (int i = 0; i < 20; ++i) axis.push_back({static_cast<double>(i), {{11, 1.}}, {}});
  }
  instance.runtime.threads = 2;
  instance.runtime.time_limit = 30.;
  instance.outcome = {{"status", "optimal"}, {"runtime", 1.25}};
  return instance;
}

}  // namespace

int main() {
  auto instance = make_instance();
  validateInstance(instance);

  const auto encoded = toJson(instance);
  const auto decoded = fromJson(encoded);
  assert(toJson(decoded) == encoded);
  assert(modelToJson(instance.model) == encoded.at("model"));
  assert(modelFromJson(encoded.at("model")).constraints.size() == 3);

  const auto assignments = enumerateAssignments(instance);
  assert(assignments.size() == 32);
  assert(assignments.front() == Assignment(5, 0));
  assert(throws([&] { validateAssignment(instance, {0, 1}); }));

  const auto fixed = fixAssignment(instance, {0, 1, 0, 1, 0});
  assert(fixed.variables.size() == 1 && fixed.variables.front().id == 11);
  assert(fixed.constraints.size() == 2);  // mixed became linear; inactive indicator was removed.
  assert(fixed.constraints.front().expression.quadratic.empty());
  assert(fixed.objective.quadratic.size() == 1);
  Values continuous{{11, 0.}};
  assert(checkResiduals(fixed, continuous, 2.).valid);
  assert(!checkResiduals(fixed, Values{}, 0.).valid);
  assert(std::abs(evaluate(instance.model.objective, Values{{1, 1.}, {2, 0.}, {3, 1.}, {4, 0.}, {5, 1.}, {6, 0.}, {7, 1.}, {8, 0.}, {9, 1.}, {10, 0.}, {11, 0.}}) - 2.) < 1e-12);

  Values integer_solution;
  for (int id = 1; id <= 10; ++id) integer_solution[id] = (id % 2) ? 1. : 0.;
  integer_solution[11] = 0.;
  assert(recoverAssignment(instance, integer_solution) == Assignment(5, 0));
  assert(recoverCoefficients(instance, integer_solution)[0].size() == 20);
  assert(!checkResiduals(instance.model, Values{{11, 0.}}, std::nullopt).valid);
  assert(throws([&] { fixIntegers(instance.model, Values{{1, 1.}}); }));
  assert(throws([&] { fixIntegers(instance.model, Values{{1, 1.}, {2, 0.}, {3, 1.}, {4, 0.}, {5, 1.}, {6, 0.}, {7, 1.}, {8, 0.}, {9, 1.}, {10, 0.}, {11, 0.}}); }));
  assert(throws([&] { evaluate({0., {{11, 1.}}, {}}, Values{}); }));

  auto invalid = instance;
  invalid.corridors[0][0].planes.clear();
  invalid.corridors[0][1].planes.clear();
  invalid.valid_mask[0][0] = false;
  invalid.valid_mask[0][1] = false;
  validateInstance(invalid, false);
  assert(enumerateAssignments(invalid).empty());
  invalid.segment_dt += 1.;
  assert(throws([&] { validateInstance(invalid, false); }));
  invalid = instance;
  invalid.corridors[0][0].planes[0][0] = std::numeric_limits<double>::infinity();
  assert(throws([&] { toJson(invalid); }));
  auto malformed_json = encoded;
  malformed_json["schema_version"] = 99;
  assert(throws([&] { fromJson(malformed_json); }));
  invalid = instance;
  invalid.assignment_variables[0][0] = invalid.assignment_variables[0][1];
  assert(throws([&] { fixAssignment(invalid, Assignment(5, 0)); }));
  invalid = instance;
  invalid.model.constraints.front().expression.quadratic.push_back({11, 11, 1.});
  assert(throws([&] { fixAssignment(invalid, Assignment(5, 0)); }));
  assert(throws([&] { evaluate({0., {{11, 1e308}}, {}}, Values{{11, 1e308}}); }));
  assert(!checkResiduals(fixed, Values{{11, std::numeric_limits<double>::quiet_NaN()}}).valid);
  assert(!checkResiduals(fixed, Values{{11, 0.}}, 3.).valid);
  auto zero_indicator = instance;
  zero_indicator.model.constraints[1].indicator_value = 0;
  const auto zero_fixed = fixAssignment(zero_indicator, Assignment(5, 1));
  assert(zero_fixed.constraints.size() == 3);
  assert(!checkResiduals(zero_fixed, Values{{11, -1.}}).valid);
  return 0;
}
