#pragma once

#include <sando/planning_instance.hpp>

#include <array>
#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace sando_learning {

struct CandidateAttempt {
  int status{sando_ampl::GRB_NUMERIC};
  double wall_time{};
  double backend_time{};
  std::optional<double> objective;
  Residuals residuals;
  std::string error;
};

struct CandidateEvaluation {
  Assignment assignment;
  std::vector<CandidateAttempt> attempts;
  double model_conversion_time{};
  std::string classification{"unknown"};
  std::optional<double> raw_objective;
  std::optional<double> cost;
  std::optional<std::array<std::vector<double>, 3>> trajectory_coefficients;
  std::optional<double> segment_dt;
};

CandidateEvaluation evaluateCandidate(const PlanningInstance&, const Assignment&,
                                      sando_ampl::Runtime&, int retry_seconds = 10);
nlohmann::json candidateToJson(const CandidateEvaluation&);
nlohmann::json evaluateInstanceJson(const PlanningInstance&, sando_ampl::Runtime&);

}  // namespace sando_learning
