// Fixed-C / fixed-Z forward at multiple time factors via live SolverGurobi.
// Hydrates corridors from a PlanningInstance fixture (planes stay fixed);
// rebuilds only the time-dependent planning model for each f.

#include <sando/gurobi_solver.hpp>
#include <sando/planning_instance.hpp>
#include <sando/segment_time.hpp>

#include <nlohmann/json.hpp>

#include <Eigen/Core>

#include <cmath>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using json = nlohmann::json;
using sando_learning::Assignment;
using sando_learning::PlanningInstance;
using sando_learning::Values;

void require(bool ok, const std::string& message) {
  if (!ok) throw std::runtime_error(message);
}

bool close_scaled(double a, double b) {
  return std::isfinite(a) && std::isfinite(b) &&
         std::abs(a - b) <= 2e-6 * std::max({1.0, std::abs(a), std::abs(b)});
}

PlanningInstance load_instance(const std::string& path) {
  std::ifstream stream(path);
  require(static_cast<bool>(stream), "cannot open fixture: " + path);
  json encoded;
  stream >> encoded;
  return sando_learning::fromJson(encoded);
}

LinearConstraint3D poly_from_planes(const std::vector<std::array<double, 4>>& planes) {
  require(!planes.empty(), "empty corridor planes");
  Eigen::MatrixXd A(static_cast<int>(planes.size()), 3);
  Eigen::VectorXd b(static_cast<int>(planes.size()));
  for (int r = 0; r < static_cast<int>(planes.size()); ++r) {
    A(r, 0) = planes[r][0];
    A(r, 1) = planes[r][1];
    A(r, 2) = planes[r][2];
    b(r) = planes[r][3];
  }
  return LinearConstraint3D(A, b);
}

Parameters parameters_from_instance(const PlanningInstance& instance) {
  Parameters p{};
  p.num_N = instance.n;
  p.num_P = static_cast<int>(instance.corridors.empty() ? 0 : instance.corridors.front().size());
  p.dc = instance.dc;
  p.dynamic_constraint_type = instance.norm;
  p.using_variable_elimination = true;
  require(instance.map_bounds.size() == 6, "map_bounds size");
  p.x_min = instance.map_bounds[0];
  p.x_max = instance.map_bounds[1];
  p.y_min = instance.map_bounds[2];
  p.y_max = instance.map_bounds[3];
  p.z_min = instance.map_bounds[4];
  p.z_max = instance.map_bounds[5];
  // Match config/sando.yaml capture defaults used by the numeric-focus fixtures.
  p.v_max = 5.0;
  p.a_max = 20.0;
  p.j_max = 100.0;
  p.jerk_smooth_weight = 10.0;
  p.factor_initial = 1.0;
  p.factor_final = 1.0;
  p.factor_constant_step_size = 1.0;
  p.max_gurobi_comp_time_sec = 30.0;
  p.debug_verbose = false;
  p.horizon = 15.0;
  p.use_dynamic_factor = false;
  return p;
}

RobotState state_from_array(const std::array<double, 9>& values) {
  RobotState state;
  state.setPos(values[0], values[1], values[2]);
  state.setVel(values[3], values[4], values[5]);
  state.setAccel(values[6], values[7], values[8]);
  return state;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const std::string fixture =
        argc > 1 ? argv[1] : "tests/ampls/fixtures/translated_trajectory.json";
    const double expected_native = argc > 2 ? std::stod(argv[2]) : 91659.8128;

    const auto captured = load_instance(fixture);
    require(captured.n == 5, "fixture must be N=5");
    require(captured.norm == "Linf", "fixture must be Linf");
    require(captured.planner == "SANDO", "fixture must be SANDO");

    SolverGurobi solver;
    solver.setPlannerName("SANDO");
    solver.initializeSolver(parameters_from_instance(captured));
    solver.setX0(state_from_array(captured.start));
    solver.setXf(state_from_array(captured.goal));
    solver.setT0(captured.t0);
    solver.setInitialDt(captured.initial_dt);

    std::vector<std::vector<LinearConstraint3D>> layers(static_cast<size_t>(captured.n));
    for (int t = 0; t < captured.n; ++t) {
      layers[t].reserve(captured.corridors[t].size());
      for (const auto& corridor : captured.corridors[t])
        layers[t].push_back(poly_from_planes(corridor.planes));
    }
    solver.setPolytopesTimeLayered(layers);

    const Assignment z{0, 0, 0, 0, 0};
    const std::vector<double> factors = {captured.factor, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5};

    json report{{"fixture", fixture},
                {"native_factor", captured.factor},
                {"assignment", z},
                {"fixed_corridors", true},
                {"rows", json::array()}};

    json native_row;
    for (double factor : factors) {
      bool error = false;
      double backend_ms = 0.0;
      const bool ok = solver.generateNewTrajectory(error, backend_ms, factor, false, &z);
      json row{{"factor", factor},
               {"ok", ok && !error},
               {"backend_ms", backend_ms},
               {"expected_segment_dt",
                sando_time::segmentDuration(captured.initial_dt, captured.dc, factor)}};
      if (!(ok && !error)) {
        row["error"] = error ? "solver_error_flag" : "generate_returned_false";
        report["rows"].push_back(row);
        std::cout << row.dump() << '\n';
        continue;
      }
      row["objective"] = solver.getObjectiveValue();
      row["segment_dt"] =
          sando_time::segmentDuration(captured.initial_dt, captured.dc, factor);
      // Direct fixed-Z models drop binary assignment ids; avoid validateInstance
      // paths that require MIQP assignment_variables. Use live residuals + PWP.
      const auto live = solver.getPlanningInstance(factor);
      row["residuals"] = live.outcome.value("residuals", json(nullptr));
      if (live.outcome.contains("residuals") && live.outcome["residuals"].is_object()) {
        require(live.outcome["residuals"].value("valid", false),
                "live residual check failed at f=" + std::to_string(factor));
        row["residuals_valid"] = true;
      } else {
        row["residuals_valid"] = false;
        require(false, "missing live residuals at f=" + std::to_string(factor));
      }
      PieceWisePol pwp;
      solver.getPieceWisePol(pwp);
      require(pwp.coeff_x.size() == static_cast<size_t>(captured.n), "pwp segment count");
      row["coeff_x0"] = pwp.coeff_x[0](0);
      row["pwp_times0"] = pwp.times.empty() ? json(nullptr) : json(pwp.times.front());
      report["rows"].push_back(row);
      std::cout << row.dump() << '\n';
      if (std::abs(factor - captured.factor) < 1e-12) native_row = row;
    }

    require(!native_row.is_null(), "native factor solve missing");
    require(close_scaled(native_row.at("objective").get<double>(), expected_native),
            "native-factor fixed-Z objective moved from numeric-focus anchor");

    const auto frozen = sando_learning::fixAssignment(captured, z);
    auto runtime = sando_ampl::createRuntime();
    require(runtime != nullptr, "AMPLS runtime unavailable");
    const auto frozen_result = runtime->solve(frozen, nullptr, captured.runtime);
    require(frozen_result.status == sando_ampl::GRB_OPTIMAL, "frozen fixAssignment not OPTIMAL");
    require(close_scaled(frozen_result.objective, native_row.at("objective").get<double>()),
            "live rebuild vs frozen snapshot objective mismatch at native f");

    report["native_vs_frozen_ok"] = true;
    report["status"] = "passed";
    std::cout << report.dump() << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "time_fixed_z_forward_probe: " << error.what() << '\n';
    return 1;
  }
}
