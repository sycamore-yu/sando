#include <sando/planning_instance.hpp>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

#ifndef SANDO_NUMERIC_FOCUS_FIXTURE
#define SANDO_NUMERIC_FOCUS_FIXTURE "tests/ampls/fixtures/translated_trajectory.json"
#endif

namespace {

using json = nlohmann::json;
using sando_learning::Assignment;
using sando_learning::PlanningInstance;
using sando_learning::Values;

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

bool close_scaled(double first, double second) {
  return std::isfinite(first) && std::isfinite(second) &&
         std::abs(first - second) <= 2e-6 * std::max({1.0, std::abs(first), std::abs(second)});
}

PlanningInstance load_instance(const std::string& path) {
  std::ifstream stream(path);
  require(static_cast<bool>(stream), "cannot open fixture: " + path);
  json encoded;
  stream >> encoded;
  auto instance = sando_learning::fromJson(encoded);
  require(instance.runtime.time_limit == 1.0, "fixture must use a one second time limit");
  return instance;
}

double parse_anchor(const char* value) {
  std::size_t consumed = 0;
  const double result = std::stod(value, &consumed);
  require(consumed == std::string(value).size() && std::isfinite(result),
          "expected QP objective must be a finite number");
  return result;
}

Values lift(const PlanningInstance& instance, const Assignment& assignment,
            const Values& continuous) {
  Values result = continuous;
  for (int t = 0; t < instance.n; ++t) {
    for (std::size_t p = 0; p < instance.assignment_variables[t].size(); ++p) {
      result[instance.assignment_variables[t][p]] =
          static_cast<int>(p) == assignment[t] ? 1.0 : 0.0;
    }
  }
  return result;
}

}  // namespace

void run_case(const std::string& fixture, double expected_qp_objective,
              sando_ampl::Runtime& original_runtime,
              sando_ampl::Runtime& fixed_runtime) {
  const auto instance = load_instance(fixture);
  const Assignment assignment{0, 0, 0, 0, 0};

  const auto original = original_runtime.solve(instance.model, nullptr, instance.runtime);
  require(original.status == sando_ampl::GRB_OPTIMAL,
          "original MIQP did not reach OPTIMAL (status " + std::to_string(original.status) + ")");
  const auto original_residuals = sando_learning::checkResiduals(
      instance.model, original.values, original.objective);
  require(original_residuals.valid, "original MIQP residual check failed: " + original_residuals.reason);

  const auto fixed_model = sando_learning::fixAssignment(instance, assignment);
  const auto fixed = fixed_runtime.solve(fixed_model, nullptr, instance.runtime);
  require(fixed.status == sando_ampl::GRB_OPTIMAL,
          "fixed QP did not reach OPTIMAL (status " + std::to_string(fixed.status) + ")");
  const auto fixed_residuals = sando_learning::checkResiduals(
      fixed_model, fixed.values, fixed.objective);
  require(fixed_residuals.valid, "fixed QP residual check failed: " + fixed_residuals.reason);

  const auto lifted = lift(instance, assignment, fixed.values);
  const auto lifted_residuals = sando_learning::checkResiduals(
      instance.model, lifted, fixed.objective);
  require(lifted_residuals.valid, "lifted QP residual check failed: " + lifted_residuals.reason);

  require(close_scaled(fixed.objective, expected_qp_objective),
          "fixed QP objective moved from independent reference: " +
              std::to_string(fixed.objective));
  require(close_scaled(original.objective, fixed.objective),
          "original MIQP and fixed QP objectives disagree: " +
              std::to_string(original.objective) + " vs " + std::to_string(fixed.objective));
  require(close_scaled(sando_learning::evaluate(instance.model.objective, lifted), fixed.objective),
          "lifted objective disagrees with fixed QP objective");

  std::cout << "numeric focus probe passed: original=" << original.objective
            << " fixed=" << fixed.objective << '\n';
}

int main(int argc, char** argv) {
  try {
    require(argc == 1 || argc == 2 || argc == 3 || argc == 5,
            "usage: numeric_focus_probe [fixture [expected_qp]] [fixture expected_qp]");
    auto original_runtime = sando_ampl::createRuntime();
    auto fixed_runtime = sando_ampl::createRuntime();
    require(static_cast<bool>(original_runtime) && static_cast<bool>(fixed_runtime),
            "AMPLS runtime factory returned null");
    if (argc == 5) {
      run_case(argv[1], parse_anchor(argv[2]), *original_runtime, *fixed_runtime);
      run_case(argv[3], parse_anchor(argv[4]), *original_runtime, *fixed_runtime);
    } else {
      run_case(argc > 1 ? argv[1] : SANDO_NUMERIC_FOCUS_FIXTURE,
               argc > 2 ? parse_anchor(argv[2]) : 91659.8128,
               *original_runtime, *fixed_runtime);
    }
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "numeric focus probe: " << error.what() << '\n';
    return 1;
  }
}
