#include <sando/gurobi_solver.hpp>
#include <sando/planning_instance.hpp>

#include <Eigen/Core>

#include <algorithm>
#include <cmath>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using sando_learning::Assignment;
using sando_learning::PlanningInstance;
using sando_learning::Values;
using sando_ampl::ModelSnapshot;
using sando_ampl::RuntimeResult;

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

Parameters parameters() {
  Parameters p{};
  p.num_N = 5;
  p.num_P = 2;
  p.dc = 1.0;
  p.dynamic_constraint_type = "Linf";
  p.using_variable_elimination = true;
  p.x_min = -2.0; p.x_max = 5.0;
  p.y_min = -3.0; p.y_max = 4.0;
  p.z_min = -1.0; p.z_max = 4.0;
  p.v_max = 20.0; p.a_max = 40.0; p.j_max = 100.0;
  p.factor_initial = 1.0; p.factor_final = 1.0; p.factor_constant_step_size = 1.0;
  p.max_gurobi_comp_time_sec = 30.0;
  p.jerk_smooth_weight = 1.0;
  p.debug_verbose = false;
  p.horizon = 5.0;
  p.use_dynamic_factor = false;
  return p;
}

LinearConstraint3D corridor(double shift) {
  Eigen::Matrix<double, 6, 3> a;
  a << 1, 0, 0, -1, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 1, 0, 0, -1;
  Eigen::Matrix<double, 6, 1> b;
  b << 5.0 + shift, 2.0 - shift, 4.0, 3.0, 4.0, 1.0;
  return LinearConstraint3D(a, b);
}

LinearConstraint3D corridor_excluding_start() {
  auto result = corridor(0.0);
  // The first segment starts at x=0; this valid-looking corridor requires
  // 1 <= x <= 2 and therefore makes assignment[0] == 1 infeasible.
  result.b_(0) = 2.0;
  result.b_(1) = -1.0;
  return result;
}

struct Fixture {
  SolverGurobi solver;
  RobotState start, goal;

  Fixture() {
    solver.setPlannerName("SANDO");
    solver.initializeSolver(parameters());
    start.setPos(0.0, 0.0, 1.0);
    goal.setPos(3.0, 1.0, 2.0);
    solver.setX0(start);
    solver.setXf(goal);
    solver.setT0(0.0);
    solver.setInitialDt(1.0);
    std::vector<std::vector<LinearConstraint3D>> layers(5);
    for (int t = 0; t < 5; ++t) {
      layers[t].push_back(corridor(0.0));
      layers[t].push_back(t == 0 ? corridor_excluding_start() : corridor(0.1));
    }
    solver.setPolytopesTimeLayered(layers);
  }
};

Values solution_values(const PlanningInstance& instance) {
  Values values;
  const auto& encoded = instance.outcome.at("solution_values");
  for (const auto& [id, value] : encoded.items()) values[std::stoull(id)] = value.get<double>();
  return values;
}

RuntimeResult solve_snapshot(const ModelSnapshot& model, const PlanningInstance& source) {
  auto runtime = sando_ampl::createRuntime();
  require(runtime != nullptr, "AMPLS runtime is unavailable");
  return runtime->solve(model, nullptr, source.runtime);
}

void check_runtime_solution(const ModelSnapshot& model, const RuntimeResult& result) {
  require(result.status == sando_ampl::GRB_OPTIMAL, "fixed snapshot was not optimal");
  const auto residuals = sando_learning::checkResiduals(model, result.values, result.objective);
  require(residuals.valid, "fixed snapshot solution has residual violations: " + residuals.reason);
}

}  // namespace

int main() {
  try {
    Fixture original_fixture;
    bool error = false;
    double milliseconds = 0.0;
    require(original_fixture.solver.generateNewTrajectory(error, milliseconds, 1.0) && !error,
            "original MIQP did not solve to optimality");
    const PlanningInstance instance = original_fixture.solver.getPlanningInstance(1.0);
    sando_learning::validateInstance(instance);
    const Values original_values = solution_values(instance);
    const auto original_residuals = sando_learning::checkResiduals(
        instance.model, original_values, instance.outcome.at("objective").get<double>());
    require(original_residuals.valid, "original solution failed snapshot residual check");
    const Assignment chosen = sando_learning::recoverAssignment(instance, original_values);
    require(chosen.size() == 5, "original solution assignment has wrong length");
    const auto roundtrip = sando_learning::fromJson(sando_learning::toJson(instance));
    const auto replay = solve_snapshot(roundtrip.model, roundtrip);
    check_runtime_solution(roundtrip.model, replay);
    const auto recovered = sando_learning::recoverCoefficients(instance, original_values);
    PieceWisePol trajectory;
    original_fixture.solver.getPieceWisePol(trajectory);
    for (int axis = 0; axis < 3; ++axis) {
      const auto& coefficients = axis == 0 ? trajectory.coeff_x :
                                 axis == 1 ? trajectory.coeff_y : trajectory.coeff_z;
      for (int t = 0; t < 5; ++t)
        for (int c = 0; c < 4; ++c)
          require(std::abs(recovered[axis][4*t+c] - coefficients[t](c)) <= 2e-6,
                  "recovered coefficient differs from production trajectory");
    }

    // The fixed online branch must agree with fixing the original MIQP
    // snapshot, including the objective value at the returned point.
    Fixture fixed_fixture;
    error = false;
    require(fixed_fixture.solver.generateNewTrajectory(error, milliseconds, 1.0, false, &chosen) && !error,
            "fixed online assignment did not solve");
    require(std::abs(fixed_fixture.solver.getObjectiveValue() - instance.outcome.at("objective").get<double>()) <=
                2e-6 * std::max(1.0, std::abs(instance.outcome.at("objective").get<double>())),
            "fixed online objective differs from original optimum");
    require(fixed_fixture.solver.getLastAssignment() == chosen, "last assignment was not retained");
    const auto direct_instance = fixed_fixture.solver.getPlanningInstance(1.0);
    for (const auto& variable : direct_instance.model.variables)
      require(variable.type != sando_ampl::GRB_BINARY && variable.type != sando_ampl::GRB_INTEGER,
              "direct fixed model retained an integer variable");
    for (const auto& constraint : direct_instance.model.constraints)
      require(!constraint.indicator && !constraint.quadratic,
              "direct fixed model retained a non-linear or indicator constraint");

    const auto fixed_snapshot = sando_learning::fixAssignment(instance, chosen);
    Values all_integer_values;
    for (int t = 0; t < instance.n; ++t)
      for (std::size_t p = 0; p < instance.assignment_variables[t].size(); ++p)
        all_integer_values[instance.assignment_variables[t][p]] =
            original_values.at(instance.assignment_variables[t][p]);
    const auto fully_fixed_snapshot = sando_learning::fixIntegers(instance.model, all_integer_values);
    require(fully_fixed_snapshot.variables.size() == fixed_snapshot.variables.size() &&
                fully_fixed_snapshot.constraints.size() >= fixed_snapshot.constraints.size(),
            "full integer fixing and assignment fixing differ");
    const RuntimeResult fixed_result = solve_snapshot(fixed_snapshot, instance);
    check_runtime_solution(fixed_snapshot, fixed_result);
    const auto fully_fixed_result = solve_snapshot(fully_fixed_snapshot, instance);
    check_runtime_solution(fully_fixed_snapshot, fully_fixed_result);
    require(std::abs(fully_fixed_result.objective - instance.outcome.at("objective").get<double>()) <=
                2e-6 * std::max(1.0, std::abs(fully_fixed_result.objective)),
            "complete original integer solution changed optimal objective");
    require(std::abs(fixed_result.objective - fixed_fixture.solver.getObjectiveValue()) <=
                2e-6 * std::max(1.0, std::abs(fixed_result.objective)),
            "offline and online fixed objectives differ");

    // Enumerate all 2^5 choices and ensure at least one fixed QP reaches the
    // proven original MIQP optimum.
    const auto assignments = sando_learning::enumerateAssignments(instance);
    require(assignments.size() == 32, "expected 2^5 valid assignments");
    double best = std::numeric_limits<double>::infinity();
    for (const auto& assignment : assignments) {
      const auto model = sando_learning::fixAssignment(instance, assignment);
      const auto result = solve_snapshot(model, instance);
      require(result.status == sando_ampl::GRB_OPTIMAL ||
                  result.status == sando_ampl::GRB_INFEASIBLE,
              "enumeration contains an unknown candidate status");
      if (result.status == sando_ampl::GRB_INFEASIBLE) continue;
      check_runtime_solution(model, result);
      best = std::min(best, result.objective);
    }
    require(std::isfinite(best), "no enumerated fixed QP was feasible");
    require(std::abs(best - instance.outcome.at("objective").get<double>()) <=
                2e-6 * std::max(1.0, std::abs(best)),
            "best enumerated QP differs from original MIQP optimum");
    const Assignment impossible{1, 0, 0, 0, 0};
    const auto impossible_result = solve_snapshot(sando_learning::fixAssignment(instance, impossible), instance);
    require(impossible_result.status != sando_ampl::GRB_OPTIMAL,
            "assignment selecting the excluded first corridor unexpectedly solved");
    Fixture impossible_online;
    error = false;
    require(!impossible_online.solver.generateNewTrajectory(error, milliseconds, 1.0, false, &impossible) && !error,
            "online assignment selecting the excluded first corridor unexpectedly solved");

    // An infeasible optimization still exposes the current model for
    // diagnostics, while carrying no fabricated solution or objective.
    Fixture failed_fixture;
    std::vector<std::vector<LinearConstraint3D>> empty_layers(5);
    for (auto& layer : empty_layers) {
      Eigen::MatrixXd a(0, 3);
      Eigen::VectorXd b(0);
      layer.emplace_back(a, b);
    }
    failed_fixture.solver.setPolytopesTimeLayered(empty_layers);
    error = false;
    require(!failed_fixture.solver.generateNewTrajectory(error, milliseconds, 1.0) && !error,
            "infeasible fixture unexpectedly solved");
    const auto failed_instance = failed_fixture.solver.getPlanningInstance(1.0);
    require(failed_instance.outcome.at("status").get<int>() != sando_ampl::GRB_OPTIMAL,
            "failed solve reported optimal status");
    require(failed_instance.outcome.at("solution_values").empty(),
            "failed solve exposed fabricated solution values");

    // Invalid inputs are rejected before model mutation.
    Fixture malformed;
    Assignment empty;
    require(!malformed.solver.generateNewTrajectory(error, milliseconds, 1.0, false, &empty),
            "empty assignment unexpectedly accepted");
    Assignment wrong_size{0, 1};
    require(!malformed.solver.generateNewTrajectory(error, milliseconds, 1.0, false, &wrong_size),
            "wrong-size assignment unexpectedly accepted");
    for (const double bad_factor : {0.0, -1.0, std::numeric_limits<double>::quiet_NaN(),
                                    std::numeric_limits<double>::infinity()}) {
      require(!malformed.solver.generateNewTrajectory(error, milliseconds, bad_factor),
              "invalid factor unexpectedly accepted");
    }
    Fixture nonfinite;
    std::vector<std::vector<LinearConstraint3D>> bad_layers(5);
    for (auto& layer : bad_layers) {
      Eigen::Matrix<double, 1, 3> a;
      a << std::numeric_limits<double>::quiet_NaN(), 0.0, 0.0;
      Eigen::Matrix<double, 1, 1> b;
      b << 1.0;
      layer.emplace_back(a, b);
      layer.emplace_back(corridor(0.0));
    }
    nonfinite.solver.setPolytopesTimeLayered(bad_layers);
    Assignment valid_choice(5, 1);
    require(!nonfinite.solver.generateNewTrajectory(error, milliseconds, 1.0, false, &valid_choice),
            "nonfinite corridor unexpectedly accepted");
    // A cancellation after a successful solve must invalidate the previous
    // capture rather than exposing it to the next learner sample.
    original_fixture.solver.resetToNominalState();
    bool reset_rejected = false;
    try { (void)original_fixture.solver.getPlanningInstance(1.0); }
    catch (const std::exception&) { reset_rejected = true; }
    require(reset_rejected, "new request exposed the previous request's model");
    original_fixture.solver.stopExecution();
    require(!original_fixture.solver.generateNewTrajectory(error, milliseconds, 1.0),
            "cancelled solve unexpectedly accepted");
    bool getter_rejected = false;
    try { (void)original_fixture.solver.getPlanningInstance(1.0); }
    catch (const std::exception&) { getter_rejected = true; }
    require(getter_rejected, "cancelled solve exposed a stale planning instance");
    std::cout << "assignment_probe PASS\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "assignment_probe FAIL: " << error.what() << '\n';
    return 1;
  }
}
