#include <sando/ampl_centering.hpp>

#include <Eigen/Cholesky>
#include <Eigen/Core>

#include <cmath>
#include <cstddef>
#include <limits>
#include <map>
#include <set>
#include <utility>
#include <vector>

namespace sando_ampl::detail {
namespace {

using OffsetMap = std::map<std::uint64_t, double>;
using LongLinear = std::map<std::uint64_t, long double>;

CenteredModel identity(const ModelSnapshot& original) { return {original, {}}; }

bool finite(double value) { return std::isfinite(value); }

bool finiteExpression(const ExpressionSnapshot& expression) {
  if (!finite(expression.constant)) return false;
  for (const auto& term : expression.linear)
    if (!term.variable || !finite(term.coefficient)) return false;
  for (const auto& term : expression.quadratic)
    if (!term.first || !term.second || !finite(term.coefficient)) return false;
  return true;
}

long double offset(const OffsetMap& offsets, std::uint64_t id) {
  const auto found = offsets.find(id);
  return found == offsets.end() ? 0.0L : static_cast<long double>(found->second);
}

bool rounded(double value) { return std::isfinite(value); }

bool assignDouble(long double value, double& result) {
  result = static_cast<double>(value);
  return rounded(result);
}

bool transformExpression(const ExpressionSnapshot& source, const OffsetMap& offsets,
                         ExpressionSnapshot& result) {
  long double constant = static_cast<long double>(source.constant);
  LongLinear linear;
  for (const auto& term : source.linear) {
    const long double shift = offset(offsets, term.variable);
    constant += static_cast<long double>(term.coefficient) * shift;
    linear[term.variable] += static_cast<long double>(term.coefficient);
  }
  for (const auto& term : source.quadratic) {
    const long double first_shift = offset(offsets, term.first);
    const long double second_shift = offset(offsets, term.second);
    const long double coefficient = static_cast<long double>(term.coefficient);
    constant += coefficient * first_shift * second_shift;
    linear[term.first] += coefficient * second_shift;
    linear[term.second] += coefficient * first_shift;
  }
  result = {};
  if (!assignDouble(constant, result.constant)) return false;
  for (const auto& [id, coefficient] : linear) {
    double value{};
    if (!assignDouble(coefficient, value)) return false;
    if (value != 0.0) result.linear.push_back({id, value});
  }
  // The quadratic part is unchanged by an affine translation.
  result.quadratic = source.quadratic;
  return true;
}

}  // namespace

CenteredModel centerContinuousObjective(const ModelSnapshot& original) {
  std::map<std::uint64_t, VariableSnapshot> variables;
  for (const auto& variable : original.variables) {
    if (!variable.id || variables.count(variable.id) || !finite(variable.lb) ||
        !finite(variable.ub) || !finite(variable.objective))
      return identity(original);
    variables.emplace(variable.id, variable);
  }
  if (!finiteExpression(original.objective)) return identity(original);
  for (const auto& constraint : original.constraints)
    if (!finite(constraint.rhs) || !finiteExpression(constraint.expression)) return identity(original);

  std::set<std::uint64_t> quadratic_ids;
  for (const auto& term : original.objective.quadratic) {
    const auto first = variables.find(term.first);
    const auto second = variables.find(term.second);
    if (first == variables.end() || second == variables.end() ||
        first->second.type != GRB_CONTINUOUS || second->second.type != GRB_CONTINUOUS)
      return identity(original);
    quadratic_ids.insert(term.first);
    quadratic_ids.insert(term.second);
  }
  if (quadratic_ids.empty()) return identity(original);

  const std::size_t dimension = quadratic_ids.size();
  std::vector<std::uint64_t> ids(quadratic_ids.begin(), quadratic_ids.end());
  std::map<std::uint64_t, Eigen::Index> index;
  for (Eigen::Index i = 0; i < static_cast<Eigen::Index>(ids.size()); ++i) index[ids[i]] = i;
  Eigen::Matrix<long double, Eigen::Dynamic, Eigen::Dynamic> h(
      static_cast<Eigen::Index>(dimension), static_cast<Eigen::Index>(dimension));
  h.setZero();
  for (const auto& term : original.objective.quadratic) {
    const Eigen::Index first = index.at(term.first);
    const Eigen::Index second = index.at(term.second);
    const long double coefficient = static_cast<long double>(term.coefficient);
    if (first == second) h(first, second) += 2.0L * coefficient;
    else {
      h(first, second) += coefficient;
      h(second, first) += coefficient;
    }
  }
  if (!h.allFinite()) return identity(original);
  Eigen::LLT<Eigen::Matrix<long double, Eigen::Dynamic, Eigen::Dynamic>> llt(h);
  if (llt.info() != Eigen::Success || !llt.matrixL().toDenseMatrix().allFinite()) return identity(original);

  LongLinear objective_linear;
  for (const auto& term : original.objective.linear)
    if (index.count(term.variable)) objective_linear[term.variable] += term.coefficient;
  Eigen::Matrix<long double, Eigen::Dynamic, 1> rhs(static_cast<Eigen::Index>(dimension));
  for (Eigen::Index i = 0; i < static_cast<Eigen::Index>(dimension); ++i)
    rhs(i) = -objective_linear[ids[static_cast<std::size_t>(i)]];
  const Eigen::Matrix<long double, Eigen::Dynamic, 1> solution = llt.solve(rhs);
  if (llt.info() != Eigen::Success || !solution.allFinite()) return identity(original);

  OffsetMap offsets;
  for (Eigen::Index i = 0; i < static_cast<Eigen::Index>(dimension); ++i) {
    const double rounded_offset = static_cast<double>(solution(i));
    if (!rounded(rounded_offset)) return identity(original);
    offsets[ids[static_cast<std::size_t>(i)]] = rounded_offset;
  }

  ModelSnapshot centered = original;
  for (auto& variable : centered.variables) {
    const long double shift = offset(offsets, variable.id);
    const double original_lb = variable.lb;
    const double original_ub = variable.ub;
    if (!assignDouble(static_cast<long double>(original_lb) - shift, variable.lb) ||
        !assignDouble(static_cast<long double>(original_ub) - shift, variable.ub) ||
        (original_lb < original_ub && variable.lb >= variable.ub))
      return identity(original);
  }
  if (!transformExpression(original.objective, offsets, centered.objective)) return identity(original);
  for (std::size_t i = 0; i < original.constraints.size(); ++i)
    if (!transformExpression(original.constraints[i].expression, offsets,
                             centered.constraints[i].expression))
      return identity(original);
  return {std::move(centered), std::move(offsets)};
}

}  // namespace sando_ampl::detail
