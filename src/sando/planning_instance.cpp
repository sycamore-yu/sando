#include <sando/planning_instance.hpp>

#include <sando/segment_time.hpp>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <set>
#include <stdexcept>

namespace sando_learning {
namespace {

using json = nlohmann::json;
using sando_ampl::ConstraintSnapshot;
using sando_ampl::ExpressionSnapshot;
using sando_ampl::LinearTerm;
using sando_ampl::ModelSnapshot;
using sando_ampl::QuadraticTerm;
using sando_ampl::VariableSnapshot;

[[noreturn]] void fail(const std::string& message) { throw std::invalid_argument(message); }

void finite(double value, const char* what) {
  if (!std::isfinite(value)) fail(std::string("non-finite ") + what);
}

template <typename T>
T get(const json& object, const char* key) {
  try {
    return object.at(key).get<T>();
  } catch (const json::exception& error) {
    fail(std::string("invalid field '") + key + "': " + error.what());
  }
}

void require_object(const json& value, const char* what) {
  if (!value.is_object()) fail(std::string(what) + " must be an object");
}

void require_array(const json& value, const char* what) {
  if (!value.is_array()) fail(std::string(what) + " must be an array");
}

void finite_json(const json& value) {
  if (value.is_number_float()) {
    if (!std::isfinite(value.get<double>())) fail("outcome contains a non-finite number");
  } else if (value.is_array()) {
    for (const auto& child : value) finite_json(child);
  } else if (value.is_object()) {
    for (const auto& [key, child] : value.items()) finite_json(child);
  }
}

template <typename T, std::size_t N>
std::array<T, N> array_from_json(const json& value, const char* what) {
  require_array(value, what);
  if (value.size() != N) fail(std::string(what) + " has the wrong length");
  std::array<T, N> result{};
  for (std::size_t i = 0; i < N; ++i) result[i] = value.at(i).get<T>();
  return result;
}

template <typename T, std::size_t N>
json array_to_json(const std::array<T, N>& value) {
  json result = json::array();
  for (const auto& entry : value) result.push_back(entry);
  return result;
}

json expression_to_json(const ExpressionSnapshot& expression) {
  json result{{"constant", expression.constant}, {"linear", json::array()}, {"quadratic", json::array()}};
  for (const auto& term : expression.linear)
    result["linear"].push_back({{"variable", term.variable}, {"coefficient", term.coefficient}});
  for (const auto& term : expression.quadratic)
    result["quadratic"].push_back({{"first", term.first}, {"second", term.second}, {"coefficient", term.coefficient}});
  return result;
}

ExpressionSnapshot expression_from_json(const json& value) {
  require_object(value, "expression");
  ExpressionSnapshot result;
  result.constant = get<double>(value, "constant");
  finite(result.constant, "expression constant");
  const auto& linear = value.at("linear");
  const auto& quadratic = value.at("quadratic");
  require_array(linear, "expression linear");
  require_array(quadratic, "expression quadratic");
  for (const auto& term : linear) {
    require_object(term, "linear term");
    LinearTerm parsed{get<std::uint64_t>(term, "variable"), get<double>(term, "coefficient")};
    if (!parsed.variable) fail("linear term has a zero variable id");
    finite(parsed.coefficient, "linear coefficient");
    result.linear.push_back(parsed);
  }
  for (const auto& term : quadratic) {
    require_object(term, "quadratic term");
    QuadraticTerm parsed{get<std::uint64_t>(term, "first"), get<std::uint64_t>(term, "second"), get<double>(term, "coefficient")};
    if (!parsed.first || !parsed.second) fail("quadratic term has a zero variable id");
    finite(parsed.coefficient, "quadratic coefficient");
    result.quadratic.push_back(parsed);
  }
  return result;
}

json model_to_json_impl(const ModelSnapshot& model) {
  json result{{"name", model.name}, {"variables", json::array()}, {"constraints", json::array()},
              {"objective", expression_to_json(model.objective)}, {"objective_sense", model.objective_sense},
              {"revision", model.revision}};
  for (const auto& variable : model.variables) {
    result["variables"].push_back({{"id", variable.id}, {"name", variable.name}, {"lb", variable.lb},
                                   {"ub", variable.ub}, {"objective", variable.objective}, {"type", std::string(1, variable.type)}});
  }
  for (const auto& constraint : model.constraints) {
    result["constraints"].push_back({{"id", constraint.id}, {"name", constraint.name},
                                      {"expression", expression_to_json(constraint.expression)},
                                      {"sense", constraint.sense}, {"rhs", constraint.rhs},
                                      {"quadratic", constraint.quadratic}, {"indicator", constraint.indicator},
                                      {"indicator_variable", constraint.indicator_variable},
                                      {"indicator_value", constraint.indicator_value}});
  }
  return result;
}

ModelSnapshot model_from_json_impl(const json& value) {
  require_object(value, "model");
  ModelSnapshot result;
  result.name = get<std::string>(value, "name");
  result.objective = expression_from_json(value.at("objective"));
  result.objective_sense = get<int>(value, "objective_sense");
  result.revision = get<std::uint64_t>(value, "revision");
  const auto& variables = value.at("variables");
  const auto& constraints = value.at("constraints");
  require_array(variables, "model variables");
  require_array(constraints, "model constraints");
  for (const auto& item : variables) {
    require_object(item, "variable");
    const auto type = get<std::string>(item, "type");
    if (type.size() != 1) fail("variable type must be one character");
    VariableSnapshot variable{get<std::uint64_t>(item, "id"), get<std::string>(item, "name"),
                              get<double>(item, "lb"), get<double>(item, "ub"),
                              get<double>(item, "objective"), type.front()};
    result.variables.push_back(std::move(variable));
  }
  for (const auto& item : constraints) {
    require_object(item, "constraint");
    ConstraintSnapshot constraint;
    constraint.id = get<std::uint64_t>(item, "id");
    constraint.name = get<std::string>(item, "name");
    constraint.expression = expression_from_json(item.at("expression"));
    constraint.sense = get<int>(item, "sense");
    constraint.rhs = get<double>(item, "rhs");
    constraint.quadratic = get<bool>(item, "quadratic");
    constraint.indicator = get<bool>(item, "indicator");
    constraint.indicator_variable = get<std::uint64_t>(item, "indicator_variable");
    constraint.indicator_value = get<int>(item, "indicator_value");
    result.constraints.push_back(std::move(constraint));
  }
  return result;
}

void validate_expression(const ExpressionSnapshot& expression, const std::set<std::uint64_t>& ids,
                         const char* what) {
  finite(expression.constant, what);
  for (const auto& term : expression.linear) {
    if (!term.variable || !ids.count(term.variable)) fail(std::string(what) + " references an unknown variable");
    finite(term.coefficient, what);
  }
  for (const auto& term : expression.quadratic) {
    if (!term.first || !term.second || !ids.count(term.first) || !ids.count(term.second))
      fail(std::string(what) + " references an unknown quadratic variable");
    finite(term.coefficient, what);
  }
}

void validate_model(const ModelSnapshot& model) {
  if (model.objective_sense != sando_ampl::GRB_MINIMIZE && model.objective_sense != sando_ampl::GRB_MAXIMIZE)
    fail("invalid model objective sense");
  std::set<std::uint64_t> variable_ids;
  for (const auto& variable : model.variables) {
    if (!variable.id || !variable_ids.insert(variable.id).second) fail("duplicate or zero variable id");
    if (variable.type != sando_ampl::GRB_CONTINUOUS && variable.type != sando_ampl::GRB_BINARY && variable.type != sando_ampl::GRB_INTEGER)
      fail("invalid variable type");
    finite(variable.lb, "variable lower bound");
    finite(variable.ub, "variable upper bound");
    finite(variable.objective, "variable objective");
    if (variable.lb > variable.ub) fail("variable lower bound exceeds upper bound");
    if (variable.type == sando_ampl::GRB_BINARY && (variable.lb < 0.0 || variable.ub > 1.0)) fail("binary bounds outside [0,1]");
  }
  validate_expression(model.objective, variable_ids, "objective");
  std::set<std::uint64_t> constraint_ids;
  for (const auto& constraint : model.constraints) {
    if (!constraint.id || !constraint_ids.insert(constraint.id).second || variable_ids.count(constraint.id)) fail("duplicate or zero constraint id");
    if (constraint.sense != sando_ampl::GRB_LESS_EQUAL && constraint.sense != sando_ampl::GRB_EQUAL && constraint.sense != sando_ampl::GRB_GREATER_EQUAL)
      fail("invalid constraint sense");
    finite(constraint.rhs, "constraint right hand side");
    validate_expression(constraint.expression, variable_ids, "constraint");
    if (constraint.indicator) {
      if (constraint.quadratic) fail("indicator cannot be quadratic");
      const auto found = std::find_if(model.variables.begin(), model.variables.end(), [&](const auto& v) { return v.id == constraint.indicator_variable; });
      if (found == model.variables.end() || found->type != sando_ampl::GRB_BINARY || (constraint.indicator_value != 0 && constraint.indicator_value != 1))
        fail("invalid indicator variable or value");
      if (!constraint.indicator_variable) fail("indicator has zero variable id");
    }
    if (!constraint.quadratic && !constraint.expression.quadratic.empty()) fail("quadratic terms in linear constraint");
  }
}

void validate_geometry(const PlanningInstance& instance) {
  if (instance.schema_version != 1) fail("unsupported planning instance schema version");
  if (instance.n != 5 || instance.norm != "Linf" || instance.planner != "SANDO") fail("unsupported planner stage");
  finite(instance.factor, "factor");
  finite(instance.initial_dt, "initial_dt");
  finite(instance.dc, "dc");
  finite(instance.segment_dt, "segment_dt");
  const double expected_dt = sando_time::segmentDuration(instance.initial_dt, instance.dc, instance.factor);
  if (std::abs(instance.segment_dt - expected_dt) > kResidualTolerance * std::max(1.0, std::abs(expected_dt))) fail("segment_dt does not match segmentDuration");
  finite(instance.planning_start_time, "planning_start_time");
  finite(instance.observation_time, "observation_time");
  finite(instance.t0, "t0");
  for (const auto value : instance.start) finite(value, "start state");
  for (const auto value : instance.goal) finite(value, "goal state");
  for (std::size_t i = 0; i < instance.map_bounds.size(); i += 2) {
    finite(instance.map_bounds[i], "map bound");
    finite(instance.map_bounds[i + 1], "map bound");
    if (instance.map_bounds[i] > instance.map_bounds[i + 1]) fail("map bounds are unordered");
  }
  if (instance.corridors.size() != static_cast<std::size_t>(instance.n) || instance.valid_mask.size() != instance.corridors.size() || instance.assignment_variables.size() != instance.corridors.size())
    fail("corridor arrays must have N layers");
  std::size_t choices = 0;
  for (int t = 0; t < instance.n; ++t) {
    const auto& layer = instance.corridors[t];
    if (layer.empty() || layer.size() > 3 || instance.valid_mask[t].size() != layer.size() || instance.assignment_variables[t].size() != layer.size()) fail("each layer must have P=1..3 matching choices");
    if (!choices) choices = layer.size();
    if (choices != layer.size()) fail("corridor choice count must be consistent across time");
    for (std::size_t p = 0; p < layer.size(); ++p) {
      const bool nonempty = !layer[p].planes.empty();
      if (instance.valid_mask[t][p] != nonempty) fail("valid_mask must exactly match nonempty corridors");
      for (const auto& plane : layer[p].planes) {
        for (const auto value : plane) finite(value, "corridor plane");
        const double normal = std::hypot(std::hypot(plane[0], plane[1]), plane[2]);
        if (!std::isfinite(normal) || !(normal > 0.0)) fail("corridor plane normal is zero or non-finite");
      }
    }
  }
}

ExpressionSnapshot substitute(const ExpressionSnapshot& source, const Values& fixed) {
  ExpressionSnapshot result;
  result.constant = source.constant;
  for (const auto& term : source.linear) {
    const auto found = fixed.find(term.variable);
    if (found == fixed.end()) result.linear.push_back(term);
    else result.constant += term.coefficient * found->second;
  }
  for (const auto& term : source.quadratic) {
    const auto first = fixed.find(term.first);
    const auto second = fixed.find(term.second);
    if (first != fixed.end() && second != fixed.end()) result.constant += term.coefficient * first->second * second->second;
    else if (first != fixed.end()) result.linear.push_back({term.second, term.coefficient * first->second});
    else if (second != fixed.end()) result.linear.push_back({term.first, term.coefficient * second->second});
    else result.quadratic.push_back(term);
  }
  return result;
}

double constraint_residual(const ConstraintSnapshot& constraint, double value) {
  if (constraint.sense == sando_ampl::GRB_LESS_EQUAL) return std::max(0.0, value - constraint.rhs);
  if (constraint.sense == sando_ampl::GRB_GREATER_EQUAL) return std::max(0.0, constraint.rhs - value);
  return std::abs(value - constraint.rhs);
}

}  // namespace

void validateInstance(const PlanningInstance& instance, bool require_model) {
  try {
    validate_geometry(instance);
    finite(instance.runtime.time_limit, "runtime time limit");
    if (instance.runtime.time_limit < 0.0) fail("runtime time limit is negative");
    finite_json(instance.outcome);
    if (require_model) {
      validate_model(instance.model);
      std::set<std::uint64_t> model_ids;
      for (const auto& variable : instance.model.variables) model_ids.insert(variable.id);
      if (instance.assignment_variables.empty()) fail("assignment mapping is missing");
      std::set<std::uint64_t> mapped;
      for (const auto& layer : instance.assignment_variables)
        for (const auto id : layer) {
          if (!id || !model_ids.count(id)) fail("assignment mapping references unknown variable");
          if (!mapped.insert(id).second) fail("assignment mapping contains duplicate variable ids");
          const auto variable = std::find_if(instance.model.variables.begin(), instance.model.variables.end(), [&](const auto& v) { return v.id == id; });
          if (variable->type != sando_ampl::GRB_BINARY) fail("assignment variables must be binary");
        }
      for (const auto& variable : instance.model.variables)
        if ((variable.type == sando_ampl::GRB_BINARY || variable.type == sando_ampl::GRB_INTEGER) && !mapped.count(variable.id)) fail("integer variable missing from assignment mapping");
      for (const auto& axis : instance.coefficients) {
        if (axis.size() != static_cast<std::size_t>(4 * instance.n)) fail("coefficient count must be 4N");
        for (const auto& expression : axis) {
          if (!expression.quadratic.empty()) fail("coefficient snapshots must be linear");
          validate_expression(expression, model_ids, "coefficient");
        }
      }
    }
  } catch (const std::invalid_argument&) {
    throw;
  } catch (const std::exception& error) {
    fail(error.what());
  }
}

std::vector<Assignment> enumerateAssignments(const PlanningInstance& instance) {
  validateInstance(instance, false);
  std::vector<Assignment> result(1);
  for (const auto& layer : instance.valid_mask) {
    std::vector<Assignment> next;
    for (const auto& partial : result)
      for (std::size_t p = 0; p < layer.size(); ++p)
        if (layer[p]) {
          auto candidate = partial;
          candidate.push_back(static_cast<int>(p));
          next.push_back(std::move(candidate));
        }
    result = std::move(next);
    if (result.empty()) break;
  }
  return result;
}

void validateAssignment(const PlanningInstance& instance, const Assignment& assignment) {
  validateInstance(instance, false);
  if (assignment.size() != static_cast<std::size_t>(instance.n)) fail("assignment must have N entries");
  for (int t = 0; t < instance.n; ++t) {
    const int p = assignment[t];
    if (p < 0 || static_cast<std::size_t>(p) >= instance.valid_mask[t].size() || !instance.valid_mask[t][p]) fail("assignment selects an invalid corridor");
  }
}

sando_ampl::ModelSnapshot fixIntegers(const ModelSnapshot& input, const Values& fixed) {
  validate_model(input);
  std::set<std::uint64_t> integer_ids;
  std::map<std::uint64_t, double> normalized;
  for (const auto& variable : input.variables)
    if (variable.type == sando_ampl::GRB_BINARY || variable.type == sando_ampl::GRB_INTEGER) integer_ids.insert(variable.id);
  if (fixed.size() != integer_ids.size()) fail("all integer variables must be fixed exactly once");
  for (const auto& [id, value] : fixed) {
    if (!integer_ids.count(id)) fail("fixed values contain an unknown or continuous variable");
    finite(value, "fixed integer value");
    const auto variable = std::find_if(input.variables.begin(), input.variables.end(), [&](const auto& v) { return v.id == id; });
    if (std::abs(value - std::round(value)) > kResidualTolerance || value < variable->lb - kResidualTolerance || value > variable->ub + kResidualTolerance) fail("fixed integer value is invalid");
    if (variable->type == sando_ampl::GRB_BINARY && (std::round(value) < 0 || std::round(value) > 1)) fail("fixed binary value is invalid");
    normalized[id] = std::round(value);
  }
  ModelSnapshot result = input;
  result.variables.erase(std::remove_if(result.variables.begin(), result.variables.end(), [&](const auto& variable) { return integer_ids.count(variable.id); }), result.variables.end());
  result.objective = substitute(input.objective, normalized);
  result.constraints.clear();
  for (const auto& original : input.constraints) {
    if (original.indicator) {
      const auto trigger = normalized.find(original.indicator_variable);
      if (trigger == normalized.end()) fail("indicator variable was not fixed");
      if (trigger->second != original.indicator_value) continue;
    }
    auto constraint = original;
    constraint.expression = substitute(original.expression, normalized);
    constraint.indicator = false;
    constraint.indicator_variable = 0;
    constraint.indicator_value = 0;
    constraint.quadratic = !constraint.expression.quadratic.empty();
    if (constraint.quadratic) fail("quadratic constraint remains after integer substitution");
    result.constraints.push_back(std::move(constraint));
  }
  validate_model(result);
  for (const auto& constraint : result.constraints)
    if (constraint.indicator || constraint.quadratic || !constraint.expression.quadratic.empty()) fail("fixed model still contains unsupported constraint");
  return result;
}

sando_ampl::ModelSnapshot fixAssignment(const PlanningInstance& instance, const Assignment& assignment) {
  validateInstance(instance, true);
  validateAssignment(instance, assignment);
  Values fixed;
  for (int t = 0; t < instance.n; ++t)
    for (std::size_t p = 0; p < instance.assignment_variables[t].size(); ++p)
      fixed[instance.assignment_variables[t][p]] = (static_cast<int>(p) == assignment[t]) ? 1.0 : 0.0;
  return fixIntegers(instance.model, fixed);
}

double evaluate(const ExpressionSnapshot& expression, const Values& values) {
  long double result = expression.constant;
  finite(expression.constant, "expression constant");
  for (const auto& term : expression.linear) {
    const auto value = values.find(term.variable);
    if (value == values.end()) fail("missing value for expression variable");
    finite(value->second, "expression value");
    finite(term.coefficient, "expression coefficient");
    result += static_cast<long double>(term.coefficient) * value->second;
  }
  for (const auto& term : expression.quadratic) {
    const auto first = values.find(term.first);
    const auto second = values.find(term.second);
    if (first == values.end() || second == values.end()) fail("missing value for quadratic variable");
    finite(first->second, "expression value");
    finite(second->second, "expression value");
    finite(term.coefficient, "quadratic coefficient");
    result += static_cast<long double>(term.coefficient) * first->second * second->second;
  }
  if (!std::isfinite(result)) fail("non-finite expression result");
  const double converted = static_cast<double>(result);
  if (!std::isfinite(converted)) fail("expression result overflows double");
  return converted;
}

Residuals checkResiduals(const ModelSnapshot& model, const Values& values, std::optional<double> objective) {
  Residuals result;
  try {
    validate_model(model);
    std::set<std::uint64_t> ids;
    for (const auto& variable : model.variables) ids.insert(variable.id);
    for (const auto& [id, value] : values) {
      if (!ids.count(id)) fail("solution contains an unknown variable");
      finite(value, "solution value");
    }
    for (const auto& variable : model.variables) {
      const auto found = values.find(variable.id);
      if (found == values.end()) fail("solution is missing a variable");
      result.bounds = std::max(result.bounds, std::max(variable.lb - found->second, found->second - variable.ub));
      if (variable.type == sando_ampl::GRB_BINARY || variable.type == sando_ampl::GRB_INTEGER)
        result.integrality = std::max(result.integrality, std::abs(found->second - std::round(found->second)));
    }
    result.bounds = std::max(0.0, result.bounds);
    for (const auto& constraint : model.constraints) {
      if (constraint.indicator) {
        const auto indicator = values.find(constraint.indicator_variable);
        if (indicator == values.end()) fail("solution is missing an indicator variable");
        if (std::abs(indicator->second - std::round(indicator->second)) > kResidualTolerance) result.integrality = std::max(result.integrality, std::abs(indicator->second - std::round(indicator->second)));
        if (std::round(indicator->second) != constraint.indicator_value) continue;
      }
      result.constraints = std::max(result.constraints, constraint_residual(constraint, evaluate(constraint.expression, values)));
    }
    finite(result.bounds, "bound residual");
    finite(result.constraints, "constraint residual");
    finite(result.integrality, "integrality residual");
    const double actual_objective = evaluate(model.objective, values);
    if (objective.has_value()) {
      finite(*objective, "expected objective");
      result.objective = std::abs(actual_objective - *objective) / std::max(1.0, std::abs(*objective));
    }
    result.valid = result.bounds <= kResidualTolerance && result.constraints <= kResidualTolerance && result.integrality <= kResidualTolerance && result.objective <= kResidualTolerance;
    if (!result.valid) result.reason = "residual exceeds tolerance";
  } catch (const std::exception& error) {
    result.valid = false;
    result.reason = error.what();
  }
  return result;
}

Assignment recoverAssignment(const PlanningInstance& instance, const Values& values) {
  validateInstance(instance, true);
  Assignment result;
  for (int t = 0; t < instance.n; ++t) {
    int selected = -1;
    for (std::size_t p = 0; p < instance.assignment_variables[t].size(); ++p) {
      const auto found = values.find(instance.assignment_variables[t][p]);
      if (found == values.end()) fail("solution is missing an assignment variable");
      finite(found->second, "assignment value");
      if (std::abs(found->second - std::round(found->second)) > kResidualTolerance) fail("assignment value is not integral");
      if (instance.valid_mask[t][p] && std::round(found->second) == 1 && selected < 0) selected = static_cast<int>(p);
    }
    if (selected < 0) fail("solution has no active valid corridor");
    result.push_back(selected);
  }
  return result;
}

std::array<std::vector<double>, 3> recoverCoefficients(const PlanningInstance& instance, const Values& values) {
  validateInstance(instance, true);
  std::array<std::vector<double>, 3> result;
  for (std::size_t axis = 0; axis < result.size(); ++axis) {
    result[axis].reserve(instance.coefficients[axis].size());
    for (const auto& expression : instance.coefficients[axis]) result[axis].push_back(evaluate(expression, values));
  }
  return result;
}

nlohmann::json toJson(const PlanningInstance& instance) {
  validateInstance(instance, true);
  json result{{"schema_version", instance.schema_version}, {"n", instance.n}, {"norm", instance.norm}, {"planner", instance.planner},
              {"scene_id", instance.scene_id}, {"episode_id", instance.episode_id}, {"request_id", instance.request_id}, {"factor_id", instance.factor_id}, {"source_id", instance.source_id}, {"config_id", instance.config_id},
              {"factor", instance.factor}, {"initial_dt", instance.initial_dt}, {"dc", instance.dc}, {"segment_dt", instance.segment_dt},
              {"planning_start_time", instance.planning_start_time}, {"observation_time", instance.observation_time}, {"t0", instance.t0},
              {"start", array_to_json(instance.start)}, {"goal", array_to_json(instance.goal)}, {"map_bounds", array_to_json(instance.map_bounds)},
              {"corridors", json::array()}, {"valid_mask", json::array()}, {"assignment_variables", json::array()},
              {"coefficients", json::array()}, {"model", model_to_json_impl(instance.model)},
              {"runtime", {{"output_flag", instance.runtime.output_flag}, {"log_to_console", instance.runtime.log_to_console}, {"threads", instance.runtime.threads}, {"time_limit", instance.runtime.time_limit}}}, {"outcome", instance.outcome}};
  for (const auto& layer : instance.corridors) {
    json encoded_layer = json::array();
    for (const auto& corridor : layer) {
      json planes = json::array();
      for (const auto& plane : corridor.planes) planes.push_back(array_to_json(plane));
      encoded_layer.push_back({{"planes", std::move(planes)}});
    }
    result["corridors"].push_back(std::move(encoded_layer));
  }
  for (const auto& layer : instance.valid_mask) result["valid_mask"].push_back(layer);
  for (const auto& layer : instance.assignment_variables) result["assignment_variables"].push_back(layer);
  for (const auto& axis : instance.coefficients) {
    json encoded = json::array();
    for (const auto& expression : axis) encoded.push_back(expression_to_json(expression));
    result["coefficients"].push_back(std::move(encoded));
  }
  return result;
}

PlanningInstance fromJson(const nlohmann::json& value) {
  try {
    require_object(value, "planning instance");
    PlanningInstance result;
    result.schema_version = get<int>(value, "schema_version");
    result.n = get<int>(value, "n");
    result.norm = get<std::string>(value, "norm");
    result.planner = get<std::string>(value, "planner");
    result.scene_id = get<std::string>(value, "scene_id");
    result.episode_id = get<std::string>(value, "episode_id");
    result.request_id = get<std::string>(value, "request_id");
    result.factor_id = get<std::string>(value, "factor_id");
    result.source_id = get<std::string>(value, "source_id");
    result.config_id = get<std::string>(value, "config_id");
    result.factor = get<double>(value, "factor");
    result.initial_dt = get<double>(value, "initial_dt");
    result.dc = get<double>(value, "dc");
    result.segment_dt = get<double>(value, "segment_dt");
    result.planning_start_time = get<double>(value, "planning_start_time");
    result.observation_time = get<double>(value, "observation_time");
    result.t0 = get<double>(value, "t0");
    result.start = array_from_json<double, 9>(value.at("start"), "start");
    result.goal = array_from_json<double, 9>(value.at("goal"), "goal");
    result.map_bounds = array_from_json<double, 6>(value.at("map_bounds"), "map_bounds");
    const auto& corridors = value.at("corridors");
    const auto& masks = value.at("valid_mask");
    const auto& assignments = value.at("assignment_variables");
    const auto& coefficients = value.at("coefficients");
    require_array(corridors, "corridors"); require_array(masks, "valid_mask"); require_array(assignments, "assignment_variables"); require_array(coefficients, "coefficients");
    for (const auto& layer : corridors) {
      require_array(layer, "corridor layer");
      std::vector<Corridor> parsed;
      for (const auto& corridor : layer) {
        require_object(corridor, "corridor");
        std::vector<std::array<double, 4>> planes;
        const auto& encoded_planes = corridor.at("planes"); require_array(encoded_planes, "corridor planes");
        for (const auto& plane : encoded_planes) planes.push_back(array_from_json<double, 4>(plane, "corridor plane"));
        parsed.push_back({std::move(planes)});
      }
      result.corridors.push_back(std::move(parsed));
    }
    for (const auto& layer : masks) { require_array(layer, "mask layer"); result.valid_mask.push_back(layer.get<std::vector<bool>>()); }
    for (const auto& layer : assignments) { require_array(layer, "assignment layer"); result.assignment_variables.push_back(layer.get<std::vector<std::uint64_t>>()); }
    if (coefficients.size() != 3) fail("coefficients must have three axes");
    for (std::size_t axis = 0; axis < 3; ++axis) { require_array(coefficients[axis], "coefficient axis"); for (const auto& expression : coefficients[axis]) result.coefficients[axis].push_back(expression_from_json(expression)); }
    const auto& runtime = value.at("runtime"); require_object(runtime, "runtime");
    result.runtime.output_flag = get<int>(runtime, "output_flag"); result.runtime.log_to_console = get<int>(runtime, "log_to_console"); result.runtime.threads = get<int>(runtime, "threads"); result.runtime.time_limit = get<double>(runtime, "time_limit");
    result.model = model_from_json_impl(value.at("model"));
    result.outcome = value.at("outcome");
    validateInstance(result, true);
    return result;
  } catch (const std::invalid_argument&) { throw; }
  catch (const std::exception& error) { fail(error.what()); }
}

nlohmann::json modelToJson(const ModelSnapshot& model) { validate_model(model); return model_to_json_impl(model); }
sando_ampl::ModelSnapshot modelFromJson(const nlohmann::json& value) {
  try {
    auto model = model_from_json_impl(value);
    validate_model(model);
    return model;
  } catch (const std::invalid_argument&) {
    throw;
  } catch (const std::exception& error) {
    fail(error.what());
  }
}
nlohmann::json residualsToJson(const Residuals& residuals) { return {{"valid", residuals.valid}, {"bounds", residuals.bounds}, {"constraints", residuals.constraints}, {"integrality", residuals.integrality}, {"objective", residuals.objective}, {"reason", residuals.reason}}; }

}  // namespace sando_learning
