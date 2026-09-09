#pragma once

#include <sando/frozen_planning_observation.hpp>
#include <sando/planning_instance.hpp>
#include <sando/sando_type.hpp>

#include <string>
#include <vector>

namespace sando_learning {

struct ReconstructedGeometry {
  bool ok{false};
  double factor{0.0};
  double d0{0.0};
  double segment_dt{0.0};
  double T{0.0};
  std::vector<double> layer_end_times;
  PlanningInstance instance;
  int valid_assignment_count{0};
  double cvx_decomp_ms{0.0};
  std::string error;
};

struct ReconstructedSolve {
  std::string status;  // optimal|infeasible|timeout_or_unknown|numerical_error|rebuild_error
  std::string solver_kind{"miqp"};
  int attempt_count{0};
  ReconstructedGeometry geometry;
  nlohmann::json objective = nullptr;
  nlohmann::json residuals = nullptr;
  nlohmann::json assignment = nullptr;
  nlohmann::json coefficients = nullptr;
  double wall_ms{0.0};
  double backend_ms{0.0};
  std::string error;
};

Parameters parametersFromObservation(const FrozenPlanningObservation& observation);
ReconstructedGeometry buildGeometryForFactor(
    const FrozenPlanningObservation& observation, double factor);
ReconstructedSolve solveReconstructedRequest(
    const FrozenPlanningObservation& observation, double factor);
nlohmann::json reconstructedSolveToJson(const ReconstructedSolve& result);

}  // namespace sando_learning
