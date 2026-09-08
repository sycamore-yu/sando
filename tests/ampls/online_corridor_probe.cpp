#include <sando/gurobi_solver.hpp>
#include <sando/planning_instance.hpp>

#include <Eigen/Core>

#include <iostream>
#include <memory>
#include <stdexcept>
#include <string>

namespace {
using sando_learning::Assignment;

void require(bool value, const std::string& message) {
  if (!value) throw std::runtime_error(message);
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
  p.horizon = 5.0;
  return p;
}

LinearConstraint3D box(double x_max) {
  Eigen::Matrix<double, 6, 3> a;
  a << 1, 0, 0, -1, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 1, 0, 0, -1;
  Eigen::Matrix<double, 6, 1> b;
  b << x_max, 2.0, 4.0, 3.0, 4.0, 1.0;
  return LinearConstraint3D(a, b);
}

LinearConstraint3D excludesStart() {
  auto result = box(2.0);
  result.b_(1) = -1.0;  // x >= 1, while the initial point is x == 0.
  return result;
}

struct Fixture {
  SolverGurobi solver;
  explicit Fixture(bool excludeFirstCorridor = false) {
    solver.setPlannerName("SANDO");
    solver.initializeSolver(parameters());
    RobotState start, goal;
    start.setPos(0.0, 0.0, 1.0);
    goal.setPos(3.0, 1.0, 2.0);
    solver.setX0(start);
    solver.setXf(goal);
    solver.setT0(0.0);
    solver.setInitialDt(1.0);
    std::vector<std::vector<LinearConstraint3D>> layers(5);
    for (int t = 0; t < 5; ++t) {
      layers[t].push_back(t == 0 && excludeFirstCorridor ? excludesStart() : box(5.0));
      layers[t].push_back(t == 0 && !excludeFirstCorridor ? excludesStart() : box(5.0));
    }
    solver.setPolytopesTimeLayered(layers);
  }
};

nlohmann::json zeroLayer(int outputs, int inputs, bool relu) {
  nlohmann::json weights = nlohmann::json::array();
  for (int row = 0; row < outputs; ++row)
    weights.push_back(std::vector<double>(static_cast<std::size_t>(inputs), 0.0));
  return {{"weight", std::move(weights)},
          {"bias", std::vector<double>(static_cast<std::size_t>(outputs), 0.0)},
          {"relu", relu}};
}

std::shared_ptr<const sando_learning::CorridorPolicy> zeroPolicy() {
  nlohmann::json layers;
  layers["plane1"] = zeroLayer(32, 4, true);
  layers["plane2"] = zeroLayer(32, 32, true);
  layers["score1"] = zeroLayer(128, 355, true);
  layers["score2"] = zeroLayer(64, 128, true);
  layers["score3"] = zeroLayer(1, 64, false);
  const nlohmann::json model = {
      {"schema_version", 1},
      {"kind", "sando_corridor_policy"},
      {"n", 5},
      {"norm", "Linf"},
      {"feature_spec", {{"version", 1}, {"origin", "start_position"},
                        {"spatial_scale", "max(1,max_map_extent)"},
                        {"velocity", "segment_dt/scale"},
                        {"acceleration", "segment_dt_squared/scale"},
                        {"plane_count", "raw"},
                        {"context_order", "start9_goal9_map6_dt5_factor"}}},
      {"layers", std::move(layers)},
      {"metadata", nlohmann::json::object()}};
  return std::make_shared<const sando_learning::CorridorPolicy>(model);
}
}  // namespace

int main() {
  try {
    Fixture fixture;
    fixture.solver.setCorridorPolicy(nullptr, SolverGurobi::CorridorMethod::Previous,
                                     Assignment{1, 0, 0, 0, 0});
    bool error = false;
    double backend_ms = 0.0;
    require(fixture.solver.generateWithCorridorPolicy(error, backend_ms, 1.0) && !error,
            "previous-corridor request did not fall back to a feasible candidate");
    const auto metrics = fixture.solver.getPolicyMetrics();
    require(metrics.at("attempts").size() >= 2, "previous assignment was not attempted first");
    require(metrics.at("attempts").at(0).at("assignment") == Assignment({1, 0, 0, 0, 0}),
            "previous assignment was not first");
    require(metrics.at("attempts").at(0).at("kind") == "qp" &&
                !metrics.at("attempts").at(0).at("success").get<bool>(),
            "invalid previous assignment unexpectedly succeeded");
    require(metrics.at("accepted_assignment") == Assignment({0, 0, 0, 0, 0}),
            "accepted assignment was not reported");

    const auto captured = fixture.solver.captureExpertInstance(1.0);
    sando_learning::validateInstance(captured);
    require(captured.outcome.at("original_status") == "not_run",
            "QP capture fabricated an original solve outcome");
    require(captured.outcome.at("status").is_null(), "captured original status was not null");
    require(captured.outcome.at("policy_metrics").at("accepted_assignment") ==
                Assignment({0, 0, 0, 0, 0}),
            "capture lost policy metrics");

    Fixture missing;
    missing.solver.setCorridorPolicy(nullptr, SolverGurobi::CorridorMethod::Learned);
    error = false;
    require(missing.solver.generateWithCorridorPolicy(error, backend_ms, 1.0) && !error,
            "missing policy did not use the original planner");
    require(missing.solver.getPolicyMetrics().at("fallback_reason") == "model_missing",
            "missing policy reason was not recorded");

    // A tied policy ranks assignments lexicographically. With corridor 0
    // excluding the start of segment 0, its first three proposals all fail;
    // the original MIQP must then find corridor 1 at the same factor.
    Fixture all_candidates_fail(true);
    all_candidates_fail.solver.setCorridorPolicy(zeroPolicy(), SolverGurobi::CorridorMethod::Learned);
    error = false;
    require(all_candidates_fail.solver.generateWithCorridorPolicy(error, backend_ms, 1.0) && !error,
            "three failed QPs did not fall back to the original MIQP");
    const auto fallback_metrics = all_candidates_fail.solver.getPolicyMetrics();
    require(fallback_metrics.at("attempts").size() == 4,
            "expected exactly three QP attempts and one MIQP fallback");
    Assignment previous;
    for (std::size_t i = 0; i < 3; ++i) {
      const auto& attempt = fallback_metrics.at("attempts").at(i);
      require(attempt.at("kind") == "qp" && !attempt.at("success").get<bool>(),
              "a proposed infeasible assignment unexpectedly solved");
      const auto assignment = attempt.at("assignment").get<Assignment>();
      require(assignment != previous, "candidate assignments were duplicated");
      previous = assignment;
    }
    require(fallback_metrics.at("attempts").at(3).at("kind") == "miqp" &&
                fallback_metrics.at("attempts").at(3).at("success").get<bool>(),
            "MIQP fallback did not solve");
    const auto accepted_fallback =
        fallback_metrics.at("accepted_assignment").get<Assignment>();
    require(accepted_fallback.size() == 5 && accepted_fallback.front() == 1,
            "fallback did not select the only feasible initial corridor");
    const auto fallback_instance = all_candidates_fail.solver.getPlanningInstance(1.0);
    sando_learning::validateAssignment(fallback_instance, accepted_fallback);
    require(fallback_instance.factor == 1.0,
            "fallback changed the requested factor");
    require(all_candidates_fail.solver.getLastAssignment() == accepted_fallback,
            "successful MIQP assignment was not retained");

    Fixture cancelled;
    cancelled.solver.stopExecution();
    cancelled.solver.setCorridorPolicy(nullptr, SolverGurobi::CorridorMethod::Previous);
    error = false;
    require(!cancelled.solver.generateWithCorridorPolicy(error, backend_ms, 1.0),
            "pre-cancelled request unexpectedly solved");
    const auto cancelled_metrics = cancelled.solver.getPolicyMetrics();
    require(cancelled_metrics.at("attempts").empty() &&
                !cancelled_metrics.at("fallback_used").get<bool>() &&
                cancelled_metrics.at("cancelled").get<bool>(),
            "pre-cancelled request started an attempt");

    missing.solver.stopExecution();
    require(!missing.solver.generateWithCorridorPolicy(error, backend_ms, 1.0),
            "cancelled subsequent request unexpectedly solved");
    bool stale_rejected = false;
    try { (void)missing.solver.captureExpertInstance(1.0); }
    catch (const std::exception&) { stale_rejected = true; }
    require(stale_rejected, "cancelled subsequent request exposed an earlier model");

    Fixture original;
    error = false;
    require(original.solver.generateNewTrajectory(error, backend_ms, 1.0) && !error,
            "original MIQP did not solve");
    require(original.solver.getLastAssignment().size() == 5,
            "successful original solve did not recover its assignment");
    std::cout << "online_corridor_probe PASS\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "online_corridor_probe FAIL: " << error.what() << '\n';
    return 1;
  }
}
