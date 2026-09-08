#include <sando/ampl_centering.hpp>

#include <cassert>
#include <cmath>
#include <limits>
#include <map>

namespace {

using namespace sando_ampl;
using sando_ampl::detail::CenteredModel;

double evaluate(const ExpressionSnapshot& expression,
                const std::map<std::uint64_t, double>& values) {
  long double result = expression.constant;
  for (const auto& term : expression.linear) result += static_cast<long double>(term.coefficient) * values.at(term.variable);
  for (const auto& term : expression.quadratic)
    result += static_cast<long double>(term.coefficient) * values.at(term.first) * values.at(term.second);
  return static_cast<double>(result);
}

bool same(const ExpressionSnapshot& first, const ExpressionSnapshot& second) {
  if (first.constant != second.constant || first.linear.size() != second.linear.size() || first.quadratic.size() != second.quadratic.size()) return false;
  for (std::size_t i = 0; i < first.linear.size(); ++i)
    if (first.linear[i].variable != second.linear[i].variable || first.linear[i].coefficient != second.linear[i].coefficient) return false;
  for (std::size_t i = 0; i < first.quadratic.size(); ++i)
    if (first.quadratic[i].first != second.quadratic[i].first || first.quadratic[i].second != second.quadratic[i].second || first.quadratic[i].coefficient != second.quadratic[i].coefficient) return false;
  return true;
}

bool same(const ModelSnapshot& first, const ModelSnapshot& second) {
  if (first.name != second.name || first.revision != second.revision || first.objective_sense != second.objective_sense ||
      !same(first.objective, second.objective) || first.variables.size() != second.variables.size() || first.constraints.size() != second.constraints.size()) return false;
  for (std::size_t i = 0; i < first.variables.size(); ++i) {
    const auto& a = first.variables[i]; const auto& b = second.variables[i];
    if (a.id != b.id || a.name != b.name || a.lb != b.lb || a.ub != b.ub || a.objective != b.objective || a.type != b.type) return false;
  }
  for (std::size_t i = 0; i < first.constraints.size(); ++i) {
    const auto& a = first.constraints[i]; const auto& b = second.constraints[i];
    if (a.id != b.id || a.name != b.name || a.sense != b.sense || a.rhs != b.rhs || a.quadratic != b.quadratic ||
        a.indicator != b.indicator || a.indicator_variable != b.indicator_variable || a.indicator_value != b.indicator_value || !same(a.expression, b.expression)) return false;
  }
  return true;
}

ModelSnapshot model() {
  ModelSnapshot result;
  result.name = "center-test";
  result.variables = {{1, "x", -4., 5., 0., GRB_CONTINUOUS}, {2, "y", -3., 6., 0., GRB_CONTINUOUS}, {3, "trigger", 0., 1., 0., GRB_BINARY}};
  result.objective = {7., {{1, 1.111111111111111}, {2, -2.222222222222222}, {3, 3.}},
                      {{1, 1, 1.23456789}, {2, 2, 4.987654321}, {1, 2, .3333333333333333}, {2, 1, .1111111111111111}}};
  result.constraints.push_back({10, "quadratic", {1., {{1, 2.}, {2, -1.}, {3, .5}}, {{1, 1, .5}, {1, 2, .7}}}, GRB_LESS_EQUAL, 9., true, false, 0, 0});
  result.constraints.push_back({11, "indicator", {-.5, {{1, 1.}, {2, .4}}, {}}, GRB_GREATER_EQUAL, 0., false, true, 3, 1});
  return result;
}

}  // namespace

int main() {
  const auto original = model();
  const auto before = original;
  const CenteredModel centered = sando_ampl::detail::centerContinuousObjective(original);
  assert(same(original, before));
  assert(centered.offsets.size() == 2);
  assert(centered.offsets.at(1) != 0.0 || centered.offsets.at(2) != 0.0);
  assert(centered.snapshot.variables.size() == original.variables.size());
  assert(centered.snapshot.constraints.size() == original.constraints.size());
  assert(centered.snapshot.constraints[0].expression.quadratic.size() == original.constraints[0].expression.quadratic.size());
  for (std::size_t i = 0; i < original.constraints[0].expression.quadratic.size(); ++i)
    assert(centered.snapshot.constraints[0].expression.quadratic[i].first == original.constraints[0].expression.quadratic[i].first &&
           centered.snapshot.constraints[0].expression.quadratic[i].second == original.constraints[0].expression.quadratic[i].second &&
           centered.snapshot.constraints[0].expression.quadratic[i].coefficient == original.constraints[0].expression.quadratic[i].coefficient);
  assert(centered.snapshot.constraints[1].indicator_variable == 3 && centered.snapshot.constraints[1].indicator_value == 1);

  for (const auto& variable : original.variables) {
    const auto& shifted = centered.snapshot.variables[&variable - original.variables.data()];
    const double offset = centered.offsets.count(variable.id) ? centered.offsets.at(variable.id) : 0.0;
    assert(std::abs(shifted.lb - (variable.lb - offset)) < 1e-12);
    assert(std::abs(shifted.ub - (variable.ub - offset)) < 1e-12);
  }
  const std::map<std::uint64_t, double> points[] = {{{1, -1.3}, {2, 1.2}, {3, 0.}}, {{1, 2.4}, {2, -2.2}, {3, 1.}}, {{1, .25}, {2, 3.5}, {3, 0.}}};
  for (const auto& point : points) {
    auto shifted = point;
    for (const auto& [id, value] : centered.offsets) shifted[id] -= value;
    assert(std::abs(evaluate(original.objective, point) - evaluate(centered.snapshot.objective, shifted)) < 1e-10);
    for (std::size_t i = 0; i < original.constraints.size(); ++i)
      assert(std::abs(evaluate(original.constraints[i].expression, point) - evaluate(centered.snapshot.constraints[i].expression, shifted)) < 1e-10);
  }

  auto non_spd = original;
  non_spd.objective.quadratic = {{1, 1, -1.}};
  const auto non_spd_result = sando_ampl::detail::centerContinuousObjective(non_spd);
  assert(non_spd_result.offsets.empty() && same(non_spd_result.snapshot, non_spd));
  auto integer_q = original;
  integer_q.objective.quadratic.push_back({3, 3, 1.});
  const auto integer_result = sando_ampl::detail::centerContinuousObjective(integer_q);
  assert(integer_result.offsets.empty() && same(integer_result.snapshot, integer_q));
  auto collapsed = original;
  collapsed.variables[0].lb = -1.0;
  collapsed.variables[0].ub = 1.0;
  collapsed.objective = {0.0, {{1, -2e20}}, {{1, 1, 1.0}}};
  const auto collapsed_result = sando_ampl::detail::centerContinuousObjective(collapsed);
  assert(collapsed_result.offsets.empty() && same(collapsed_result.snapshot, collapsed));

  auto nonfinite = original;
  nonfinite.objective.linear[0].coefficient = std::numeric_limits<double>::quiet_NaN();
  const auto nonfinite_result = sando_ampl::detail::centerContinuousObjective(nonfinite);
  assert(nonfinite_result.offsets.empty());
  assert(std::isnan(nonfinite_result.snapshot.objective.linear[0].coefficient));
  auto restored_nonfinite = nonfinite_result.snapshot;
  restored_nonfinite.objective.linear[0].coefficient = original.objective.linear[0].coefficient;
  assert(same(restored_nonfinite, original));
  return 0;
}
