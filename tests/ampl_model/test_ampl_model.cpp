#include <cassert>
#include <fstream>
#include <sstream>
#include <utility>
#include <sando/ampl_model.hpp>

namespace sando_ampl {
class TestRuntime final : public Runtime {
 public:
  int calls{};
  bool fail{};
  bool throw_on_solve{};
  RuntimeResult solve(
      const ModelSnapshot& model, GRBCallback* callback, const RuntimeParameters&) override {
    ++calls;
    if (callback) callback->callback();
    if (throw_on_solve) throw GRBException("runtime exploded", 9001);
    if (fail) return {GRB_INFEASIBLE, 0.0, 0.01, {}};
    RuntimeResult result{GRB_OPTIMAL, 7.0, 0.02, {}};
    for (const auto& variable : model.variables) result.values[variable.id] = variable.lb;
    return result;
  }
};
static std::shared_ptr<TestRuntime> runtime = std::make_shared<TestRuntime>();
std::shared_ptr<Runtime> createRuntime() { return runtime; }
}  // namespace sando_ampl

template <class F>
static bool throws_grb(F&& action) {
  try {
    std::forward<F>(action)();
  } catch (const sando_ampl::GRBException&) {
    return true;
  }
  return false;
}

int main() {
  using namespace sando_ampl;
  GRBModel model;
  auto x = model.addVar(0.0, 1.0, 0.0, GRB_CONTINUOUS, "x");
  auto y = model.addVar(-2.0, 2.0, 0.0, GRB_CONTINUOUS, "y");
  GRBLinExpr affine = 2.0 * x - 3.0 * y + 4.0;
  auto product = affine * (x + y);
  model.addQConstr(product <= 10.0, "q");
  model.setObjective(product, GRB_MINIMIZE);
  model.optimize();
  assert(x.getValue() == 0.0 && y.getValue() == -2.0);
  assert(product.getValue() == -20.0);
  assert(model.get(GRB_DoubleAttr_ObjVal) == 7.0);

  model.remove(x);
  bool stale = false;
  try {
    (void)y.getValue();
  } catch (const GRBException&) {
    stale = true;
  }
  assert(stale);
  auto replacement = model.addVar(0.0, 1.0, 0.0, GRB_CONTINUOUS, "x");
  bool replacement_stale = false;
  try {
    (void)replacement.getValue();
  } catch (const GRBException&) {
    replacement_stale = true;
  }
  assert(replacement_stale);

  GRBModel other;
  auto other_x = other.addVar(0.0, 1.0, 0.0, GRB_CONTINUOUS, "other");
  bool crossed = false;
  try {
    model.addConstr(GRBLinExpr(other_x) <= 1.0);
  } catch (const GRBException&) {
    crossed = true;
  }
  assert(crossed);

  runtime->fail = true;
  bool failed = false;
  try {
    model.optimize();
  } catch (...) {
    failed = true;
  }
  assert(!failed);
  bool no_result = false;
  try {
    (void)replacement.getValue();
  } catch (const GRBException&) {
    no_result = true;
  }
  assert(no_result);
  assert(throws_grb([&] { (void)model.get(GRB_DoubleAttr_ObjVal); }));
  runtime->fail = false;
  model.optimize();
  assert(replacement.getValue() == 0.0);

  const std::string path = "/tmp/sando_ampl_model.mod";
  model.exportModel(path);
  std::ifstream input(path);
  std::stringstream text;
  text << input.rdbuf();
  assert(text.str().find(" * v_") != std::string::npos);

  // Scalar expressions are model-independent and evaluate without a solve.
  assert(GRBLinExpr(3.5).getValue() == 3.5);
  assert((GRBQuadExpr(2.25)).getValue() == 2.25);

  // A handle or expression from another model cannot cross any model boundary.
  GRBModel first;
  GRBModel second;
  auto first_x = first.addVar(0, 1, 0, GRB_CONTINUOUS, "first_x");
  auto second_x = second.addVar(0, 1, 0, GRB_CONTINUOUS, "second_x");
  assert(throws_grb([&] { first.remove(second_x); }));
  assert(throws_grb([&] { first.addConstr(GRBLinExpr(second_x) <= 1); }));
  assert(throws_grb([&] { first.addGenConstrIndicator(second_x, 0, GRBLinExpr(first_x) <= 1); }));
  assert(throws_grb([&] { first.setObjective(GRBLinExpr(second_x)); }));
  auto first_binary = first.addVar(0, 1, 0, GRB_BINARY, "first_binary");
  assert(
      throws_grb([&] { first.addGenConstrIndicator(first_binary, 1, GRBLinExpr(second_x) <= 1); }));

  // Mixed linear/quadratic arithmetic preserves provenance and rejects crossings.
  auto mixed = GRBLinExpr(first_x) * GRBLinExpr(first_x);
  mixed = mixed + GRBLinExpr(first_x) - GRBQuadExpr(1.0);
  assert(throws_grb([&] { (void)(mixed + GRBLinExpr(second_x)); }));

  // A nonzero addVar objective is represented in the snapshot and survives updates.
  auto objective_var = first.addVar(-1, 4, 2.5, GRB_CONTINUOUS, "objective_var");
  auto objective_snapshot = first.snapshot();
  assert(objective_snapshot.objective.linear.size() == 1);
  assert(objective_snapshot.objective.linear[0].coefficient == 2.5);

  // Repeated add/remove leaves no stale records in the bounded snapshot.
  for (int i = 0; i < 32; ++i) {
    auto temporary = first.addVar(0, 1, 0, GRB_CONTINUOUS, "temporary");
    first.remove(temporary);
  }
  assert(first.snapshot().variables.size() == 3);  // first_x, first_binary, objective_var
  for (int i = 0; i < 32; ++i) {
    auto temporary = first.addConstr(GRBLinExpr(first_x) <= 1, "temporary_constraint");
    first.remove(temporary);
  }
  assert(first.snapshot().constraints.empty());

  // Removing an indicator variable removes its indicator constraint and its terms.
  auto indicator =
      first.addGenConstrIndicator(first_binary, 1, GRBLinExpr(first_x) <= 1, "indicator");
  assert(first.snapshot().constraints.size() == 1);
  first.remove(first_binary);
  first.remove(indicator);
  first.update();
  auto after_indicator_remove = first.snapshot();
  assert(after_indicator_remove.variables.size() == 2);
  assert(after_indicator_remove.constraints.empty());
  assert(after_indicator_remove.objective.linear.size() == 1);
  assert(after_indicator_remove.objective.linear[0].coefficient == 2.5);
  (void)indicator;
  auto recreated_binary = first.addVar(0, 1, 0, GRB_BINARY, "recreated_binary");
  auto recreated_indicator = first.addGenConstrIndicator(
      recreated_binary, 1, GRBLinExpr(first_x) <= 1, "recreated_indicator");
  first.optimize();
  assert(recreated_binary.getValue() == 0);
  first.remove(recreated_binary);
  first.remove(recreated_indicator);
  first.update();
  assert(first.snapshot().variables.size() == 2);
  assert(first.snapshot().constraints.empty());

  // Expired model handles and expressions fail deterministically, while constants remain valid.
  GRBVar expired_var;
  GRBLinExpr expired_expression;
  {
    GRBModel temporary_model;
    expired_var = temporary_model.addVar(0, 1, 0, GRB_CONTINUOUS, "expired");
    expired_expression = GRBLinExpr(expired_var) + 1;
  }
  assert(throws_grb([&] { (void)expired_var.getValue(); }));
  assert(throws_grb([&] { (void)expired_expression.getValue(); }));
  assert(throws_grb([&] { second.addConstr(expired_expression <= 1); }));
  assert(GRBLinExpr(8.0).getValue() == 8.0);

  // A failed or throwing solve invalidates all previous solution and objective values.
  auto throwing_runtime = std::make_shared<TestRuntime>();
  GRBModel throwing_model(throwing_runtime);
  auto throwing_x = throwing_model.addVar(0, 1, 0, GRB_CONTINUOUS, "throwing_x");
  throwing_model.optimize();
  assert(throwing_x.getValue() == 0);
  assert(throwing_model.get(GRB_DoubleAttr_ObjVal) == 7);
  throwing_runtime->throw_on_solve = true;
  assert(throws_grb([&] { throwing_model.optimize(); }));
  assert(throws_grb([&] { (void)throwing_x.getValue(); }));
  assert(throws_grb([&] { (void)throwing_model.get(GRB_DoubleAttr_ObjVal); }));

  return 0;
}
