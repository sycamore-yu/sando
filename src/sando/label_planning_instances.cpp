#include <sando/candidate_costs.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <iostream>
#include <memory>
#include <stdexcept>
#include <unistd.h>

namespace sando_learning {
namespace {

using json = nlohmann::json;
using Clock = std::chrono::steady_clock;

[[noreturn]] void fail(const std::string& message) { throw std::invalid_argument(message); }

json optional_number(const std::optional<double>& value) {
  return value.has_value() ? json(*value) : json(nullptr);
}

json attempt_to_json(const CandidateAttempt& attempt) {
  return {{"status", attempt.status},
          {"wall_time", attempt.wall_time},
          {"backend_time", std::isfinite(attempt.backend_time) ? json(attempt.backend_time) : json(nullptr)},
          {"objective", optional_number(attempt.objective)},
          {"residuals", residualsToJson(attempt.residuals)},
          {"error", attempt.error}};
}

std::map<std::uint64_t, double> lifted_values(const PlanningInstance& instance,
                                               const Assignment& assignment,
                                               const Values& continuous) {
  Values result = continuous;
  for (int t = 0; t < instance.n; ++t)
    for (std::size_t p = 0; p < instance.assignment_variables[t].size(); ++p)
      result[instance.assignment_variables[t][p]] = (static_cast<int>(p) == assignment[t]) ? 1.0 : 0.0;
  return result;
}

}  // namespace

CandidateEvaluation evaluateCandidate(const PlanningInstance& instance, const Assignment& assignment,
                                      sando_ampl::Runtime& runtime, int retry_seconds) {
  validateInstance(instance, true);
  validateAssignment(instance, assignment);
  if (retry_seconds < 0) fail("retry time limit must be nonnegative");
  const auto conversion_started = Clock::now();
  const auto fixed = fixAssignment(instance, assignment);
  CandidateEvaluation candidate;
  candidate.assignment = assignment;
  candidate.model_conversion_time = std::chrono::duration<double>(Clock::now() - conversion_started).count();

  for (int attempt_number = 0; attempt_number < 2; ++attempt_number) {
    sando_ampl::RuntimeParameters parameters = instance.runtime;
    if (attempt_number) parameters.time_limit = retry_seconds;
    CandidateAttempt attempt;
    const auto started = Clock::now();
    try {
      const auto result = runtime.solve(fixed, nullptr, parameters);
      attempt.status = result.status;
      attempt.backend_time = result.runtime;
      const bool backend_time_valid = std::isfinite(attempt.backend_time) && attempt.backend_time >= 0.0;
      if (!backend_time_valid) attempt.error = "backend returned an invalid runtime";
      if (backend_time_valid && result.status == sando_ampl::GRB_OPTIMAL) {
        if (!std::isfinite(result.objective)) {
          attempt.error = "backend returned a non-finite objective";
        } else {
          attempt.objective = result.objective;
          attempt.residuals = checkResiduals(fixed, result.values, result.objective);
          if (attempt.residuals.valid) {
            const auto lifted = lifted_values(instance, assignment, result.values);
            const auto original_residuals = checkResiduals(instance.model, lifted, result.objective);
            if (original_residuals.valid) {
              candidate.classification = "feasible";
              candidate.raw_objective = result.objective;
            } else {
              attempt.residuals = original_residuals;
              attempt.error = "lifted solution violates original model: " + original_residuals.reason;
            }
          } else {
            attempt.error = "optimal solution failed residual checks: " + attempt.residuals.reason;
          }
        }
      } else if (backend_time_valid && result.status == sando_ampl::GRB_INFEASIBLE) {
        candidate.classification = "infeasible";
      } else if (backend_time_valid) {
        attempt.error = "solver status is not a proof of infeasibility";
      }
    } catch (const std::exception& error) {
      attempt.status = sando_ampl::GRB_NUMERIC;
      attempt.error = error.what();
    }
    attempt.wall_time = std::chrono::duration<double>(Clock::now() - started).count();
    candidate.attempts.push_back(std::move(attempt));
    if (candidate.classification != "unknown") break;
  }
  if (candidate.classification == "unknown") {
    if (candidate.attempts.size() == 2 && candidate.attempts.back().error.empty())
      candidate.attempts.back().error = "unknown solver result";
  }
  return candidate;
}

nlohmann::json candidateToJson(const CandidateEvaluation& candidate) {
  json result{{"assignment", candidate.assignment},
              {"classification", candidate.classification},
              {"model_conversion_time", candidate.model_conversion_time},
              {"raw_objective", optional_number(candidate.raw_objective)},
              {"cost", optional_number(candidate.cost)},
              {"attempts", json::array()}};
  for (const auto& attempt : candidate.attempts) result["attempts"].push_back(attempt_to_json(attempt));
  return result;
}

nlohmann::json evaluateInstanceJson(const PlanningInstance& instance, sando_ampl::Runtime& runtime) {
  const auto started = Clock::now();
  validateInstance(instance, true);
  const auto assignments = enumerateAssignments(instance);
  if (assignments.size() > 243) fail("assignment count exceeds 243");
  std::vector<CandidateEvaluation> candidates;
  candidates.reserve(assignments.size());
  for (const auto& assignment : assignments)
    candidates.push_back(evaluateCandidate(instance, assignment, runtime));

  std::vector<double> objectives;
  std::size_t unknown = 0, infeasible = 0;
  for (const auto& candidate : candidates) {
    if (candidate.classification == "feasible") objectives.push_back(*candidate.raw_objective);
    else if (candidate.classification == "infeasible") ++infeasible;
    else ++unknown;
  }
  const bool all_infeasible = !candidates.empty() && unknown == 0 && infeasible == candidates.size();
  const bool complete = unknown == 0 && !objectives.empty();
  if (complete) {
    const auto [minimum, maximum] = std::minmax_element(objectives.begin(), objectives.end());
    const long double lo = *minimum, hi = *maximum;
    const long double scale = std::max(hi - lo,
        1e-6L * std::max({1.0L, std::abs(lo), std::abs(hi)}));
    for (auto& candidate : candidates) {
      if (candidate.classification == "feasible")
        candidate.cost = static_cast<double>((static_cast<long double>(*candidate.raw_objective) - lo) / scale);
      else if (candidate.classification == "infeasible") candidate.cost = 2.0;
    }
  }

  json result{{"schema_version", 1},
              {"instance", toJson(instance)},
              {"total_valid_assignments", candidates.size()},
              {"costs_complete", complete},
              {"failurestats", {{"unknown", unknown}, {"proven_infeasible", infeasible}, {"all_infeasible", all_infeasible}}},
              {"timing", {{"covered", complete ? candidates.size() : 0}, {"excluded", complete ? 0 : candidates.size()}, {"wall_seconds", 0.0}, {"backend_seconds", 0.0}, {"model_conversion_seconds", 0.0}, {"attempt_count", 0}, {"retries", 0}}},
              {"candidates", json::array()}};
  double wall_seconds = 0., backend_seconds = 0., conversion_seconds = 0.;
  std::size_t attempt_count = 0, retries = 0;
  for (const auto& candidate : candidates) {
    result["candidates"].push_back(candidateToJson(candidate));
    conversion_seconds += candidate.model_conversion_time;
    attempt_count += candidate.attempts.size();
    if (candidate.attempts.size() > 1) ++retries;
    for (const auto& attempt : candidate.attempts) {
      wall_seconds += attempt.wall_time;
      if (std::isfinite(attempt.backend_time)) backend_seconds += attempt.backend_time;
    }
  }
  result["timing"]["solve_and_residual_wall_seconds"] = wall_seconds;
  result["timing"]["wall_seconds"] = std::chrono::duration<double>(Clock::now() - started).count();
  result["timing"]["backend_seconds"] = backend_seconds;
  result["timing"]["model_conversion_seconds"] = conversion_seconds;
  result["timing"]["attempt_count"] = attempt_count;
  result["timing"]["retries"] = retries;
  if (candidates.empty()) result["excluded_reason"] = "no_valid_assignments";
  else if (all_infeasible) result["excluded_reason"] = "all_infeasible";
  else if (!complete) result["excluded_reason"] = "unknown_or_infeasible_results";
  return result;
}

}  // namespace sando_learning

namespace {

void usage() {
  throw std::invalid_argument("usage: label_planning_instances --input FILE --output FILE [--limit N]");
}

}  // namespace

#ifndef SANDO_LABEL_PLANNING_INSTANCES_NO_MAIN
int main(int argc, char** argv) {
  try {
    std::string input_path, output_path;
    std::optional<std::size_t> limit;
    for (int i = 1; i < argc; ++i) {
      const std::string option = argv[i];
      if ((option == "--input" || option == "--output" || option == "--limit") && i + 1 < argc) {
        const std::string value = argv[++i];
        if (option == "--input") input_path = value;
        else if (option == "--output") output_path = value;
        else limit = std::stoull(value);
      } else usage();
    }
    if (input_path.empty() || output_path.empty()) usage();
    std::ifstream input(input_path);
    if (!input) throw std::runtime_error("cannot open input JSONL");
    const int output_fd = ::open(output_path.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0644);
    if (output_fd < 0) throw std::runtime_error("cannot create exclusive output JSONL: " + std::string(std::strerror(errno)));
    FILE* output_stream = ::fdopen(output_fd, "w");
    if (!output_stream) { ::close(output_fd); throw std::runtime_error("cannot open output JSONL stream"); }
    std::unique_ptr<FILE, int (*)(FILE*)> output(output_stream, &std::fclose);
    auto runtime = sando_ampl::createRuntime();
    if (!runtime) throw std::runtime_error("cannot create AMPL runtime");
    std::string line;
    std::size_t processed = 0;
    while (std::getline(input, line) && (!limit || processed < *limit)) {
      if (line.empty()) continue;
      const auto instance = sando_learning::fromJson(nlohmann::json::parse(line));
      const std::string serialized = sando_learning::evaluateInstanceJson(instance, *runtime).dump() + "\n";
      if (std::fwrite(serialized.data(), 1, serialized.size(), output.get()) != serialized.size() || std::fflush(output.get()) != 0)
        throw std::runtime_error("cannot write output JSONL");
      ++processed;
      std::cerr << "label_planning_instances: processed=" << processed << '\n' << std::flush;
    }
    if (std::fclose(output.release()) != 0) throw std::runtime_error("cannot close output JSONL");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "label_planning_instances: " << error.what() << '\n';
    return 2;
  }
}
#endif
