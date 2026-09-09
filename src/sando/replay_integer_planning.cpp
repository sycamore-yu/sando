#include <sando/corridor_policy.hpp>
#include <sando/planning_instance.hpp>

#include <algorithm>
#include <chrono>
#include <cerrno>
#include <cmath>
#include <cstdio>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <fstream>
#include <filesystem>
#include <iostream>
#include <memory>
#include <limits>
#include <optional>
#include <random>
#include <stdexcept>
#include <string>
#include <unistd.h>
#include <vector>

namespace {

using json = nlohmann::json;
using Clock = std::chrono::steady_clock;
using sando_learning::Assignment;
using sando_learning::PlanningInstance;
using sando_learning::Values;
using sando_ampl::GRB_OPTIMAL;
using sando_ampl::GRB_NUMERIC;

constexpr const char* kSchema = "sando_integer_replay";
constexpr std::size_t kDefaultCandidateLimit = 3;

struct Options {
  std::string input;
  std::string output;
  std::string bc;
  std::string cost;
  std::string closed_loop;
  std::uint32_t seed{0};
  bool seed_given{false};
  std::optional<std::size_t> limit;
  std::size_t candidate_limit{kDefaultCandidateLimit};
};

struct PolicySlot {
  std::string path;
  std::unique_ptr<sando_learning::CorridorPolicy> policy;
  std::string error;
};

struct SolveAttempt {
  json assignment = nullptr;
  std::string kind;
  int status{GRB_NUMERIC};
  bool solve_attempted{false};
  bool accepted{false};
  bool fallback{false};
  json objective = nullptr;
  json raw_objective = nullptr;
  json residuals = nullptr;
  double wall_seconds{0.0};
  double backend_seconds{0.0};
  double prepare_seconds{0.0};
  double adapter_seconds{0.0};
  std::string error;
  json original_residuals = nullptr;
};

struct MethodResult {
  std::string method;
  std::vector<Assignment> proposed;
  std::vector<SolveAttempt> attempts;
  std::optional<Assignment> chosen;
  bool fallback_used{false};
  std::string fallback_reason;
  bool history_available{false};
  double ranking_seconds{0.0};
  double fallback_seconds{0.0};
  double total_seconds{0.0};
  double backend_seconds{0.0};
  double prepare_seconds{0.0};
  double adapter_seconds{0.0};
};

[[noreturn]] void usage() {
  throw std::invalid_argument(
      "usage: replay_integer_planning --input FILE --output FILE "
      "[--bc FILE] [--cost FILE] [--closed-loop FILE] --seed N [--limit N] "
      "[--candidate-limit N]");
}

std::uint32_t parse_seed(const std::string& value) {
  std::size_t consumed = 0;
  const unsigned long long parsed = std::stoull(value, &consumed);
  if (consumed != value.size() || parsed > 0xffffffffULL)
    throw std::invalid_argument("--seed must be an unsigned 32-bit integer");
  return static_cast<std::uint32_t>(parsed);
}

std::size_t parse_size(const std::string& value, const char* option) {
  std::size_t consumed = 0;
  const unsigned long long parsed = std::stoull(value, &consumed);
  if (consumed != value.size()) throw std::invalid_argument(std::string(option) + " must be an integer");
  if (parsed > static_cast<unsigned long long>(std::numeric_limits<std::size_t>::max()))
    throw std::invalid_argument(std::string(option) + " is too large");
  return static_cast<std::size_t>(parsed);
}

Options parse_options(int argc, char** argv) {
  Options result;
  if (const char* raw = std::getenv("SANDO_CORRIDOR_CANDIDATE_LIMIT")) {
    result.candidate_limit = parse_size(raw, "SANDO_CORRIDOR_CANDIDATE_LIMIT");
    if (result.candidate_limit < 1)
      throw std::invalid_argument("SANDO_CORRIDOR_CANDIDATE_LIMIT must be >= 1");
  }
  for (int i = 1; i < argc; ++i) {
    const std::string option = argv[i];
    if (option == "--input" || option == "--output" || option == "--bc" ||
        option == "--cost" || option == "--closed-loop" || option == "--seed" || option == "--limit" ||
        option == "--candidate-limit") {
      if (i + 1 >= argc) usage();
      const std::string value = argv[++i];
      if (value.empty()) throw std::invalid_argument(option + " cannot be empty");
      if (option == "--input") result.input = value;
      else if (option == "--output") result.output = value;
      else if (option == "--bc") result.bc = value;
      else if (option == "--cost") result.cost = value;
      else if (option == "--closed-loop") result.closed_loop = value;
      else if (option == "--seed") { result.seed = parse_seed(value); result.seed_given = true; }
      else if (option == "--candidate-limit") {
        result.candidate_limit = parse_size(value, "--candidate-limit");
        if (result.candidate_limit < 1)
          throw std::invalid_argument("--candidate-limit must be >= 1");
      } else result.limit = parse_size(value, "--limit");
    } else usage();
  }
  if (result.input.empty() || result.output.empty() || !result.seed_given) usage();
  return result;
}

PolicySlot load_policy(const std::string& path) {
  PolicySlot result;
  result.path = path;
  if (path.empty()) {
    result.error = "model_missing";
    return result;
  }
  try {
    auto loaded = sando_learning::CorridorPolicy::load(std::filesystem::path(path));
    result.policy = std::make_unique<sando_learning::CorridorPolicy>(std::move(loaded));
  } catch (const std::exception& error) {
    result.error = std::string("model_invalid: ") + error.what();
  }
  return result;
}

json optional_assignment(const std::optional<Assignment>& assignment) {
  return assignment.has_value() ? json(*assignment) : json(nullptr);
}

json attempt_json(const SolveAttempt& attempt) {
  return {{"assignment", attempt.assignment},
          {"kind", attempt.kind},
          {"status", attempt.status},
          {"solve_attempted", attempt.solve_attempted},
          {"accepted", attempt.accepted},
          {"fallback", attempt.fallback},
          {"objective", attempt.objective},
          {"raw_objective", attempt.raw_objective},
          {"residuals", attempt.residuals},
          {"original_residuals", attempt.original_residuals},
          {"wall_seconds", attempt.wall_seconds},
          {"backend_seconds", attempt.backend_seconds},
          {"prepare_seconds", attempt.prepare_seconds},
          {"adapter_seconds", attempt.adapter_seconds},
          {"wall_ms", attempt.wall_seconds * 1000.0},
          {"backend_ms", attempt.backend_seconds * 1000.0},
          {"model_prepare_ms", attempt.prepare_seconds * 1000.0},
          {"adapter_ms", attempt.adapter_seconds * 1000.0},
          {"error", attempt.error}};
}

json method_json(const MethodResult& result) {
  json attempts = json::array();
  for (const auto& attempt : result.attempts) attempts.push_back(attempt_json(attempt));
  json proposed = json::array();
  for (const auto& assignment : result.proposed) proposed.push_back(assignment);
  return {{"method", result.method},
          {"proposed_assignments", std::move(proposed)},
          {"chosen_assignment", optional_assignment(result.chosen)},
          {"history_available", result.history_available},
          {"attempts", std::move(attempts)},
          {"fallback_used", result.fallback_used},
          {"fallback_reason", result.fallback_reason},
          {"timing", {{"ranking_seconds", result.ranking_seconds},
                       {"backend_seconds", result.backend_seconds},
                       {"prepare_seconds", result.prepare_seconds},
                       {"adapter_seconds", result.adapter_seconds},
                       {"fallback_seconds", result.fallback_seconds},
                       {"total_seconds", result.total_seconds},
                       {"ranking_ms", result.ranking_seconds * 1000.0},
                       {"backend_ms", result.backend_seconds * 1000.0},
                       {"model_prepare_ms", result.prepare_seconds * 1000.0},
                       {"adapter_ms", result.adapter_seconds * 1000.0},
                       {"fallback_ms", result.fallback_seconds * 1000.0},
                       {"total_ms", result.total_seconds * 1000.0}}}};
}

bool finite_nonnegative(double value) {
  return std::isfinite(value) && value >= 0.0;
}

Values lifted_values(const PlanningInstance& instance, const Assignment& assignment,
                    const Values& continuous) {
  Values result = continuous;
  for (int t = 0; t < instance.n; ++t)
    for (std::size_t p = 0; p < instance.assignment_variables[t].size(); ++p)
      result[instance.assignment_variables[t][p]] = (static_cast<int>(p) == assignment[t]) ? 1.0 : 0.0;
  return result;
}

void account_attempt(MethodResult& method, const SolveAttempt& attempt) {
  method.backend_seconds += attempt.backend_seconds;
  method.prepare_seconds += attempt.prepare_seconds;
  method.adapter_seconds += attempt.adapter_seconds;
}

// Solve one snapshot and perform the common status and residual acceptance gate.
SolveAttempt solve_snapshot(const PlanningInstance& instance, const sando_ampl::ModelSnapshot& snapshot,
                            const Assignment* assignment, bool fallback, sando_ampl::Runtime& runtime,
                            std::optional<Assignment>* recovered = nullptr) {
  SolveAttempt attempt;
  attempt.kind = fallback ? "miqp" : (assignment ? "qp" : "original");
  attempt.fallback = fallback;
  if (assignment) attempt.assignment = *assignment;
  const auto started = Clock::now();
  try {
    attempt.solve_attempted = true;
    const auto result = runtime.solve(snapshot, nullptr, instance.runtime);
    attempt.status = result.status;
    if (finite_nonnegative(result.runtime)) attempt.backend_seconds = result.runtime;
    else attempt.error = "backend returned an invalid runtime";
    if (result.status == GRB_OPTIMAL) {
      if (std::isfinite(result.objective)) {
        attempt.objective = result.objective;
        attempt.raw_objective = result.objective;
      } else {
        attempt.error = "backend returned a non-finite objective";
      }
    }
    if (result.status == GRB_OPTIMAL && attempt.error.empty()) {
      const auto fixed = sando_learning::checkResiduals(snapshot, result.values, result.objective);
      if (assignment) {
        const auto lifted = lifted_values(instance, *assignment, result.values);
        const auto original = sando_learning::checkResiduals(instance.model, lifted, result.objective);
        attempt.residuals = sando_learning::residualsToJson(fixed);
        attempt.original_residuals = sando_learning::residualsToJson(original);
        attempt.accepted = fixed.valid && original.valid;
        if (!attempt.accepted) {
          if (!fixed.valid) attempt.error = "fixed residual check failed: " + fixed.reason;
          else attempt.error = "lifted original residual check failed: " + original.reason;
        }
      } else {
        attempt.residuals = sando_learning::residualsToJson(fixed);
        attempt.accepted = fixed.valid;
        if (!attempt.accepted) attempt.error = "original residual check failed: " + fixed.reason;
      }
      if (attempt.accepted && recovered) {
        try {
          *recovered = assignment ? std::optional<Assignment>(*assignment)
                                  : std::optional<Assignment>(sando_learning::recoverAssignment(instance, result.values));
        } catch (const std::exception& error) {
          attempt.accepted = false;
          attempt.error = std::string("assignment recovery failed: ") + error.what();
        }
      }
    } else if (result.status != GRB_OPTIMAL && attempt.error.empty()) {
      attempt.error = "solver status is not optimal";
    }
  } catch (const std::exception& error) {
    attempt.status = GRB_NUMERIC;
    attempt.error = error.what();
  }
  attempt.wall_seconds = std::chrono::duration<double>(Clock::now() - started).count();
  if (!finite_nonnegative(attempt.backend_seconds)) attempt.backend_seconds = 0.0;
  // Runtime wall time includes AMPL export/compile/import and postsolve. Keep
  // that adapter overhead visible without mislabeling it as model conversion.
  attempt.adapter_seconds = std::max(0.0, attempt.wall_seconds - attempt.backend_seconds);
  return attempt;
}

// Return the prior online assignment when it is present and valid.  A missing
// history is deliberately represented separately from an invalid assignment.
std::optional<Assignment> previous_assignment(const PlanningInstance& instance, bool& present) {
  present = false;
  if (!instance.outcome.is_object() || !instance.outcome.contains("previous_appended_assignment") ||
      instance.outcome.at("previous_appended_assignment").is_null()) return std::nullopt;
  present = true;
  try {
    Assignment result = instance.outcome.at("previous_appended_assignment").get<Assignment>();
    sando_learning::validateAssignment(instance, result);
    return result;
  } catch (const std::exception&) {
    return std::nullopt;
  }
}

std::vector<Assignment> first_candidates(const PlanningInstance& instance, const std::string& method,
                                         PolicySlot* policy, MethodResult& result,
                                         std::size_t candidate_limit) {
  const auto all = sando_learning::enumerateAssignments(instance);
  std::vector<Assignment> candidates;
  if (method == "previous") {
    bool present = false;
    const auto prior = previous_assignment(instance, present);
    result.history_available = present;
    if (prior) candidates.push_back(*prior);
    if (!present) result.fallback_reason = "history_unavailable";
    else if (!prior) result.fallback_reason = "previous_assignment_invalid";
    for (const auto& assignment : all) {
      if (std::find(candidates.begin(), candidates.end(), assignment) == candidates.end())
        candidates.push_back(assignment);
      if (candidates.size() == candidate_limit) break;
    }
  } else {
    if (!policy || !policy->policy) return {};
    const auto started = Clock::now();
    const auto ranked = policy->policy->rank(instance);
    result.ranking_seconds = std::chrono::duration<double>(Clock::now() - started).count();
    for (const auto& assignment : ranked) {
      if (std::find(candidates.begin(), candidates.end(), assignment) == candidates.end())
        candidates.push_back(assignment);
      if (candidates.size() == candidate_limit) break;
    }
  }
  return candidates;
}

MethodResult run_method(const PlanningInstance& instance, const std::string& method,
                        PolicySlot* policy, sando_ampl::Runtime& runtime,
                        std::size_t candidate_limit = kDefaultCandidateLimit) {
  MethodResult result;
  result.method = method;
  const auto started = Clock::now();
  if (method == "original") {
    auto attempt = solve_snapshot(instance, instance.model, nullptr, false, runtime, &result.chosen);
    result.attempts.push_back(std::move(attempt));
    result.total_seconds = std::chrono::duration<double>(Clock::now() - started).count();
    result.backend_seconds = result.attempts.back().backend_seconds;
    result.prepare_seconds = result.attempts.back().prepare_seconds;
    result.adapter_seconds = result.attempts.back().adapter_seconds;
    return result;
  }
  const bool supported = instance.n == 5 && instance.norm == "Linf" && instance.planner == "SANDO" &&
                         instance.corridors.size() == 5 && instance.valid_mask.size() == 5;
  if (!supported) {
    result.fallback_used = true;
    result.fallback_reason = "unsupported_formulation";
  } else if (method == "previous") {
    try {
      result.proposed = first_candidates(instance, method, nullptr, result, candidate_limit);
    } catch (const std::exception& error) {
      result.fallback_reason = std::string("candidate_selection_failed: ") + error.what();
    }
  } else if (!policy || !policy->policy) {
    result.fallback_used = true;
    result.fallback_reason = policy ? policy->error : "model_missing";
  } else {
    try {
      result.proposed = first_candidates(instance, method, policy, result, candidate_limit);
    } catch (const std::exception& error) {
      result.fallback_reason = std::string("ranking_failed: ") + error.what();
      result.proposed.clear();
    }
  }
  if (!result.proposed.empty()) {
    for (const auto& assignment : result.proposed) {
      SolveAttempt attempt;
      const auto preparation_started = Clock::now();
      double conversion_seconds = 0.0;
      try {
        const auto fixed = sando_learning::fixAssignment(instance, assignment);
        conversion_seconds = std::chrono::duration<double>(Clock::now() - preparation_started).count();
        attempt = solve_snapshot(instance, fixed, &assignment, false, runtime);
      } catch (const std::exception& error) {
        attempt.kind = "qp"; attempt.assignment = assignment; attempt.status = GRB_NUMERIC; attempt.error = error.what();
        conversion_seconds = std::chrono::duration<double>(Clock::now() - preparation_started).count();
      }
      attempt.prepare_seconds += conversion_seconds;
      attempt.wall_seconds += conversion_seconds;
      account_attempt(result, attempt);
      result.attempts.push_back(std::move(attempt));
      if (result.attempts.back().accepted) { result.chosen = assignment; break; }
    }
  }
  if (!result.chosen) {
    result.fallback_used = true;
    if (result.fallback_reason.empty()) result.fallback_reason = result.proposed.empty() ? "no_candidate" : "candidate_exhausted";
    const auto fallback_started = Clock::now();
    auto attempt = solve_snapshot(instance, instance.model, nullptr, true, runtime, &result.chosen);
    result.fallback_seconds = std::chrono::duration<double>(Clock::now() - fallback_started).count();
    // The fallback assignment is recovered from the accepted solution by
    // solving it separately in the helper that retains RuntimeResult values.
    account_attempt(result, attempt);
    result.attempts.push_back(std::move(attempt));
  }
  result.total_seconds = std::chrono::duration<double>(Clock::now() - started).count();
  return result;
}

json excluded_record(std::size_t line_number, const std::string& error) {
  return {{"schema_version", 1}, {"kind", kSchema}, {"excluded", true},
          {"line", line_number}, {"error", error}, {"input_sha256", nullptr}};
}

json replay_record(const PlanningInstance& instance, const Options& options,
                   const std::vector<std::string>& order,
                   const std::map<std::string, MethodResult>& methods) {
  json method_jsons = json::object();
  for (const auto& name : {"original", "previous", "bc", "cost", "closed_loop"}) {
    const auto found = methods.find(name);
    if (found != methods.end()) {
      method_jsons[name] = method_json(found->second);
      if (std::string(name) == "bc") method_jsons[name]["model_path"] = options.bc.empty() ? json(nullptr) : json(options.bc);
      if (std::string(name) == "cost") method_jsons[name]["model_path"] = options.cost.empty() ? json(nullptr) : json(options.cost);
      if (std::string(name) == "closed_loop") method_jsons[name]["model_path"] = options.closed_loop.empty() ? json(nullptr) : json(options.closed_loop);
    }
  }
  json model_paths = {{"bc", options.bc.empty() ? json(nullptr) : json(options.bc)},
                     {"cost", options.cost.empty() ? json(nullptr) : json(options.cost)},
                     {"closed_loop", options.closed_loop.empty() ? json(nullptr) : json(options.closed_loop)}};
  json metadata = {{"scene_id", instance.scene_id}, {"episode_id", instance.episode_id},
                   {"request_id", instance.request_id}, {"factor_id", instance.factor_id},
                   {"source_id", instance.source_id}, {"config_id", instance.config_id},
                   {"factor", instance.factor}, {"model_paths", std::move(model_paths)}};
  return {{"schema_version", 1}, {"kind", kSchema}, {"excluded", false},
          {"scene_id", instance.scene_id}, {"episode_id", instance.episode_id},
          {"request_id", instance.request_id}, {"factor_id", instance.factor_id},
          {"source_id", instance.source_id}, {"config_id", instance.config_id},
          {"factor", instance.factor}, {"metadata", std::move(metadata)},
          {"seed", options.seed}, {"candidate_limit", options.candidate_limit},
          {"method_order", order},
          {"runtime_reuse", "one_fresh_runtime_per_method"}, {"methods", std::move(method_jsons)}};
}

int open_exclusive(const std::string& path) {
  const int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0644);
  if (fd < 0) throw std::runtime_error("cannot create exclusive output JSONL: " + std::string(std::strerror(errno)));
  return fd;
}

}  // namespace

#ifndef SANDO_REPLAY_INTEGER_PLANNING_NO_MAIN
int main(int argc, char** argv) {
  try {
    const Options options = parse_options(argc, argv);
    std::ifstream input(options.input);
    if (!input) throw std::runtime_error("cannot open input JSONL");
    const int fd = open_exclusive(options.output);
    FILE* raw = ::fdopen(fd, "w");
    if (!raw) { ::close(fd); throw std::runtime_error("cannot open output JSONL stream"); }
    std::unique_ptr<FILE, int (*)(FILE*)> output(raw, &std::fclose);

    std::map<std::string, PolicySlot> policies;
    policies.emplace("bc", load_policy(options.bc));
    policies.emplace("cost", load_policy(options.cost));
    policies.emplace("closed_loop", load_policy(options.closed_loop));
    const std::vector<std::string> names{"original", "previous", "bc", "cost", "closed_loop"};
    std::mt19937 rng(options.seed);
    std::string line;
    std::size_t line_number = 0, processed = 0;
    while (std::getline(input, line)) {
      ++line_number;
      if (line.empty()) continue;
      if (options.limit && processed >= *options.limit) break;
      json record;
      try {
        const PlanningInstance instance = sando_learning::fromJson(json::parse(line));
        std::vector<std::string> order = names;
        std::shuffle(order.begin(), order.end(), rng);
        std::map<std::string, MethodResult> methods;
        for (const auto& name : order) {
          auto runtime = sando_ampl::createRuntime();
          if (!runtime) throw std::runtime_error("cannot create AMPL runtime");
          PolicySlot* policy = nullptr;
          if (name == "bc") policy = &policies.at("bc");
          else if (name == "cost") policy = &policies.at("cost");
          else if (name == "closed_loop") policy = &policies.at("closed_loop");
          methods.emplace(name, run_method(instance, name, policy, *runtime, options.candidate_limit));
        }
        record = replay_record(instance, options, order, methods);
      } catch (const std::exception& error) {
        record = excluded_record(line_number, error.what());
      }
      const std::string serialized = record.dump() + "\n";
      if (std::fwrite(serialized.data(), 1, serialized.size(), output.get()) != serialized.size() ||
          std::fflush(output.get()) != 0)
        throw std::runtime_error("cannot write output JSONL");
      ++processed;
    }
    if (std::fclose(output.release()) != 0) throw std::runtime_error("cannot close output JSONL");
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "replay_integer_planning: " << error.what() << '\n';
    return 2;
  }
}
#endif
