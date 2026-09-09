// Debug-only: ablate MIQP constraint groups on a frozen reconstruct observation.
#include <sando/frozen_planning_observation.hpp>
#include <sando/gurobi_solver.hpp>
#include <sando/planning_instance.hpp>
#include <sando/reconstruct_planning_request.hpp>
#include <sando/segment_time.hpp>

#include <nlohmann/json.hpp>

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using json = nlohmann::json;
using sando_ampl::ConstraintSnapshot;
using sando_ampl::ModelSnapshot;
using sando_learning::FrozenPlanningObservation;
using sando_learning::PlanningInstance;

constexpr double kFactor = 2.0;
constexpr const char* kDefaultObservation =
    "docker/dev-workspace/results/joint-time-v2/stage-jia/"
    "static_forest-easy-seed0/request_observation/2.json";

void require(bool ok, const std::string& message) {
  if (!ok) throw std::runtime_error(message);
}

FrozenPlanningObservation load_observation(const std::string& path) {
  std::ifstream in(path);
  require(static_cast<bool>(in), "cannot open observation: " + path);
  return sando_learning::frozenObservationFromJson(json::parse(in));
}

const char* status_name(int status) {
  switch (status) {
    case sando_ampl::GRB_OPTIMAL:
      return "optimal";
    case sando_ampl::GRB_INFEASIBLE:
      return "infeasible";
    case sando_ampl::GRB_INF_OR_UNBD:
      return "inf_or_unbd";
    case sando_ampl::GRB_UNBOUNDED:
      return "unbounded";
    case sando_ampl::GRB_INTERRUPTED:
      return "interrupted";
    case sando_ampl::GRB_NUMERIC:
      return "numeric";
    default:
      return "other";
  }
}

bool contains_any(const std::string& name, const std::vector<std::string>& needles) {
  for (const auto& needle : needles)
    if (name.find(needle) != std::string::npos) return true;
  return false;
}

// SANDO Linf uses max_vel_Linf_*; Safe* covers FASTER; MaxVel covers legacy.
bool is_dynamics(const ConstraintSnapshot& c) {
  return contains_any(c.name, {"SafeMaxVel", "SafeMinVel", "SafeMaxAccel", "SafeMinAccel",
                               "SafeMaxJerk", "SafeMinJerk", "max_vel", "min_vel", "max_accel",
                               "min_accel", "max_jerk", "min_jerk", "MaxVel", "MinVel",
                               "MaxAccel", "MinAccel", "MaxJerk", "MinJerk", "vel_L1",
                               "accel_L1", "jerk_L1", "vel_L2", "accel_L2", "jerk_L2"});
}

bool is_corridor(const ConstraintSnapshot& c) {
  if (c.indicator) return true;
  return contains_any(c.name, {"Poly", "poly", "corridor", "Indicator", "indicator",
                               "At_least_1_pol", "empty_poly"});
}

bool is_map_bound(const ConstraintSnapshot& c) {
  return contains_any(c.name, {"Map", "Bound"});
}

ModelSnapshot drop_if(const ModelSnapshot& model,
                      bool (*pred)(const ConstraintSnapshot&)) {
  ModelSnapshot out = model;
  out.constraints.clear();
  out.constraints.reserve(model.constraints.size());
  for (const auto& c : model.constraints)
    if (!pred(c)) out.constraints.push_back(c);
  return out;
}

void dump_model(const ModelSnapshot& model, const std::string& path) {
  const json encoded = sando_learning::modelToJson(model);
  if (path.empty()) {
    std::cout << encoded.dump() << '\n';
    return;
  }
  std::ofstream out(path);
  require(static_cast<bool>(out), "cannot write snapshot: " + path);
  out << encoded.dump(2) << '\n';
  std::cerr << "wrote model snapshot (" << model.constraints.size() << " constraints) to "
            << path << '\n';
}

void solve_ablation(const char* label, const ModelSnapshot& model,
                    const sando_ampl::RuntimeParameters& runtime) {
  auto rt = sando_ampl::createRuntime();
  require(rt != nullptr, "createRuntime returned null");
  const auto result = rt->solve(model, nullptr, runtime);
  std::cout << "ablation=" << label << " constraints=" << model.constraints.size()
            << " status=" << status_name(result.status) << " (" << result.status << ")"
            << " runtime_s=" << result.runtime << '\n';
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const std::string observation_path = argc > 1 ? argv[1] : kDefaultObservation;
    const std::string snapshot_path = argc > 2 ? argv[2] : "";

    const auto observation = load_observation(observation_path);
    const auto geometry =
        sando_learning::buildGeometryForFactor(observation, kFactor);
    require(geometry.ok, "buildGeometryForFactor failed: " + geometry.error);
    std::cout << "geometry ok factor=" << geometry.factor
              << " segment_dt=" << geometry.segment_dt << " T=" << geometry.T
              << " valid_assignments=" << geometry.valid_assignment_count << '\n';

    const auto solved =
        sando_learning::solveReconstructedRequest(observation, kFactor);
    std::cout << "reconstruct status=" << solved.status
              << " solver_kind=" << solved.solver_kind
              << " backend_ms=" << solved.backend_ms << '\n';
    require(solved.status != "rebuild_error",
            "reconstruct rebuild_error: " + solved.error);

    PlanningInstance instance = solved.geometry.instance;
    require(!instance.model.constraints.empty(),
            "planning instance has empty model snapshot");
    // MIQP binaries present so validateInstance can succeed.
    sando_learning::validateInstance(instance);

    dump_model(instance.model, snapshot_path);

    // Name inventory (helps tune ablation needles without a second dry run).
    json name_counts = json::object();
    for (const auto& c : instance.model.constraints) {
      std::string key = c.name;
      const auto pos = key.find_first_of("0123456789");
      if (pos != std::string::npos) key.resize(pos);
      name_counts[key] = name_counts.value(key, 0) + 1;
    }
    std::cout << "constraint_name_prefixes=" << name_counts.dump() << '\n';

    const auto& runtime = instance.runtime;
    const auto full = instance.model;
    const auto no_dyn = drop_if(full, is_dynamics);
    const auto no_cor = drop_if(full, is_corridor);
    const auto no_map = drop_if(full, is_map_bound);

    std::cout << "removed dynamics=" << (full.constraints.size() - no_dyn.constraints.size())
              << " corridor=" << (full.constraints.size() - no_cor.constraints.size())
              << " map=" << (full.constraints.size() - no_map.constraints.size()) << '\n';

    solve_ablation("full", full, runtime);
    solve_ablation("remove_dynamics", no_dyn, runtime);
    solve_ablation("remove_corridor_indicator", no_cor, runtime);
    solve_ablation("remove_map_bounds", no_map, runtime);
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "infeasibility_group_probe: " << error.what() << '\n';
    return 1;
  }
}
