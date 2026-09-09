#define SANDO_REPLAY_INTEGER_PLANNING_NO_MAIN
#include "../../src/sando/replay_integer_planning.cpp"

#include <sando/segment_time.hpp>

#include <cassert>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>

namespace sando_ampl {
// The test supplies a fake Runtime directly.  Defining the factory here keeps
// the AMPL model recorder linkable without starting a native solver.
std::shared_ptr<Runtime> createRuntime() { return {}; }
}  // namespace sando_ampl

namespace {

using namespace sando_learning;

class FakeRuntime final : public sando_ampl::Runtime {
 public:
  std::vector<int> statuses;
  int calls{0};
  bool throw_on_solve{false};

  sando_ampl::RuntimeResult solve(const sando_ampl::ModelSnapshot& model,
                                  sando_ampl::GRBCallback*,
                                  const sando_ampl::RuntimeParameters&) override {
    ++calls;
    if (throw_on_solve) throw std::runtime_error("mock solve exception");
    sando_ampl::RuntimeResult result;
    result.status = calls <= static_cast<int>(statuses.size()) ? statuses[calls - 1] : sando_ampl::GRB_OPTIMAL;
    result.runtime = 0.0;
    for (const auto& variable : model.variables) result.values[variable.id] = 1.0;
    if (result.status == sando_ampl::GRB_OPTIMAL) result.objective = evaluate(model.objective, result.values);
    return result;
  }
};

PlanningInstance make_instance(int choices = 2) {
  PlanningInstance result;
  result.factor = 1.0;
  result.initial_dt = 0.1;
  result.dc = 0.05;
  result.segment_dt = sando_time::segmentDuration(result.initial_dt, result.dc, result.factor);
  result.start = {0., 0., 1., 0., 0., 0., 0., 0., 0.};
  result.goal = {1., 1., 2., 0., 0., 0., 0., 0., 0.};
  result.map_bounds = {-2., 2., -2., 2., 0., 4.};
  result.corridors.resize(5);
  result.valid_mask.resize(5);
  result.assignment_variables.resize(5);
  for (int t = 0; t < 5; ++t) {
    for (int p = 0; p < choices; ++p) {
      result.corridors[t].push_back({{{1., 0., 0., 3.}}});
      result.valid_mask[t].push_back(true);
      const auto id = static_cast<std::uint64_t>(t * choices + p + 1);
      result.assignment_variables[t].push_back(id);
      result.model.variables.push_back({id, "assignment", 0., 1., 0., sando_ampl::GRB_BINARY});
    }
  }
  for (auto& axis : result.coefficients) axis.resize(20);
  result.outcome["previous_appended_assignment"] = {0, 0, 0, 0, 0};
  validateInstance(result);
  return result;
}

json zero_vector(int count) {
  json result = json::array();
  for (int index = 0; index < count; ++index) result.push_back(0.0);
  return result;
}

json zero_layer(int input, int output) {
  json weights = json::array();
  for (int row = 0; row < output; ++row) weights.push_back(zero_vector(input));
  return {{"weight", std::move(weights)}, {"bias", zero_vector(output)}};
}

std::filesystem::path write_zero_policy() {
  const auto path = std::filesystem::temp_directory_path() /
                    ("sando_integer_replay_policy_" + std::to_string(::getpid()) + ".json");
  const json feature_spec = {{"version", 1}, {"origin", "start_position"},
                             {"spatial_scale", "max(1,max_map_extent)"},
                             {"velocity", "segment_dt/scale"},
                             {"acceleration", "segment_dt_squared/scale"},
                             {"plane_count", "raw"},
                             {"context_order", "start9_goal9_map6_dt5_factor"}};
  const json model = {
      {"schema_version", 1}, {"kind", "sando_corridor_policy"}, {"n", 5}, {"norm", "Linf"},
      {"feature_spec", feature_spec},
      {"layers", {{"plane1", zero_layer(4, 32)}, {"plane2", zero_layer(32, 32)},
                   {"score1", zero_layer(355, 128)}, {"score2", zero_layer(128, 64)},
                   {"score3", zero_layer(64, 1)}}},
      {"metadata", json::object()}};
  std::ofstream stream(path);
  stream << model.dump() << '\n';
  stream.close();
  return path;
}

void assert_timing_accounted(const MethodResult& result) {
  for (const auto& attempt : result.attempts) {
    assert(attempt.wall_seconds + 1e-12 >= attempt.prepare_seconds);
    assert(attempt.adapter_seconds >= 0.0);
    assert(std::abs(attempt.wall_seconds - attempt.prepare_seconds - attempt.adapter_seconds) < 1e-8);
  }
}

void require_throws_with(const char* needle, const std::function<void()>& body) {
  try {
    body();
  } catch (const std::invalid_argument& error) {
    assert(std::string(error.what()).find(needle) != std::string::npos);
    return;
  }
  assert(false && "expected invalid_argument");
}

void check_previous_candidates() {
  auto instance = make_instance(2);
  const auto all = enumerateAssignments(instance);
  assert(all.size() == 32);

  const auto run = [&](const Assignment& previous, std::size_t limit) {
    instance.outcome["previous_appended_assignment"] = previous;
    MethodResult result;
    auto candidates = first_candidates(instance, "previous", nullptr, result, limit);
    assert(candidates.size() <= limit);
    assert(candidates.size() == std::min(limit, all.size()));
    assert(candidates.front() == previous);
    for (std::size_t i = 0; i < candidates.size(); ++i)
      for (std::size_t j = i + 1; j < candidates.size(); ++j)
        assert(candidates[i] != candidates[j]);
    return candidates;
  };

  // Previous at first / middle / last of the enumeration, limits 1 and 3.
  assert(run(all.front(), 1).size() == 1);
  assert(run(all[all.size() / 2], 1).size() == 1);
  assert(run(all.back(), 1).size() == 1);
  assert(run(all.back(), 1).front() == all.back());
  assert(run(all.front(), 3).size() == 3);
  assert(run(all[all.size() / 2], 3).size() == 3);
  assert(run(all.back(), 3).size() == 3);

  // Missing previous fills from enumeration only.
  instance.outcome["previous_appended_assignment"] = nullptr;
  MethodResult missing;
  auto missing_candidates = first_candidates(instance, "previous", nullptr, missing, 1);
  assert(!missing.history_available);
  assert(missing.fallback_reason == "history_unavailable");
  assert(missing_candidates.size() == 1);
  assert(missing_candidates.front() == all.front());

  // Invalid previous is skipped, then enumeration fills the limit.
  instance.outcome["previous_appended_assignment"] = Assignment{9, 9, 9, 9, 9};
  MethodResult invalid;
  auto invalid_candidates = first_candidates(instance, "previous", nullptr, invalid, 1);
  assert(invalid.history_available);
  assert(invalid.fallback_reason == "previous_assignment_invalid");
  assert(invalid_candidates.size() == 1);
  assert(invalid_candidates.front() == all.front());
}

void check_candidate_limit_parsing() {
  const char* argv_base[] = {"replay_integer_planning", "--input", "in.json", "--output",
                             "out.json", "--seed", "1"};
  unsetenv("SANDO_CORRIDOR_CANDIDATE_LIMIT");
  {
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6], "--candidate-limit", "1"};
    const auto options = parse_options(9, const_cast<char**>(argv));
    assert(options.candidate_limit == 1);
  }
  // CLI overrides env when both are set.
  setenv("SANDO_CORRIDOR_CANDIDATE_LIMIT", "3", 1);
  {
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6], "--candidate-limit", "1"};
    const auto options = parse_options(9, const_cast<char**>(argv));
    assert(options.candidate_limit == 1);
  }
  unsetenv("SANDO_CORRIDOR_CANDIDATE_LIMIT");
  require_throws_with("--candidate-limit", [&]() {
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6], "--candidate-limit", "0"};
    parse_options(9, const_cast<char**>(argv));
  });
  require_throws_with("--candidate-limit", [&]() {
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6], "--candidate-limit", "-1"};
    parse_options(9, const_cast<char**>(argv));
  });
  require_throws_with("--candidate-limit", [&]() {
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6], "--candidate-limit", "1x"};
    parse_options(9, const_cast<char**>(argv));
  });
  require_throws_with("SANDO_CORRIDOR_CANDIDATE_LIMIT", [&]() {
    setenv("SANDO_CORRIDOR_CANDIDATE_LIMIT", "999999999999999999999", 1);
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6]};
    try {
      parse_options(7, const_cast<char**>(argv));
    } catch (...) {
      unsetenv("SANDO_CORRIDOR_CANDIDATE_LIMIT");
      throw;
    }
  });
  unsetenv("SANDO_CORRIDOR_CANDIDATE_LIMIT");
}

void check_runtime_reuse_parsing() {
  const char* argv_base[] = {"replay_integer_planning", "--input", "in.json", "--output",
                             "out.json", "--seed", "1"};
  {
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6]};
    const auto options = parse_options(7, const_cast<char**>(argv));
    assert(options.runtime_reuse == RuntimeReuseMode::Fresh);
  }
  {
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6], "--runtime-reuse", "persistent"};
    const auto options = parse_options(9, const_cast<char**>(argv));
    assert(options.runtime_reuse == RuntimeReuseMode::Persistent);
  }
  {
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6], "--runtime-reuse", "fresh"};
    const auto options = parse_options(9, const_cast<char**>(argv));
    assert(options.runtime_reuse == RuntimeReuseMode::Fresh);
  }
  require_throws_with("--runtime-reuse", [&]() {
    const char* argv[] = {argv_base[0], argv_base[1], argv_base[2], argv_base[3], argv_base[4],
                          argv_base[5], argv_base[6], "--runtime-reuse", "reuse"};
    parse_options(9, const_cast<char**>(argv));
  });
}

}  // namespace

int main() {
  check_previous_candidates();
  check_candidate_limit_parsing();
  check_runtime_reuse_parsing();

  auto instance = make_instance();

  FakeRuntime previous_runtime;
  previous_runtime.statuses = {sando_ampl::GRB_INTERRUPTED, sando_ampl::GRB_INTERRUPTED,
                               sando_ampl::GRB_INTERRUPTED};
  const auto previous = run_method(instance, "previous", nullptr, previous_runtime);
  assert(previous.history_available);
  assert(previous.proposed.size() == 3);
  assert(previous.proposed[0] != previous.proposed[1] && previous.proposed[1] != previous.proposed[2]);
  assert(previous.attempts.size() == 4);
  assert(previous.attempts[0].kind == "qp" && previous.attempts[2].kind == "qp");
  assert(previous.attempts[3].kind == "miqp" && previous.fallback_used && previous.chosen.has_value());
  assert_timing_accounted(previous);

  FakeRuntime limit_one_runtime;
  limit_one_runtime.statuses = {sando_ampl::GRB_INTERRUPTED};
  const auto limited = run_method(instance, "previous", nullptr, limit_one_runtime, 1);
  assert(limited.proposed.size() == 1);
  assert(limited.attempts.size() == 2);

  const auto policy_path = write_zero_policy();
  const auto cleanup = [&]() { std::error_code error; std::filesystem::remove(policy_path, error); };
  PolicySlot policy = load_policy(policy_path.string());
  assert(policy.policy && policy.error.empty());
  FakeRuntime policy_runtime;
  const auto learned = run_method(instance, "bc", &policy, policy_runtime);
  assert(learned.proposed.size() == 3);
  assert(learned.proposed[0] != learned.proposed[1] && learned.proposed[1] != learned.proposed[2]);
  assert(learned.attempts.front().kind == "qp" && learned.chosen.has_value());
  assert_timing_accounted(learned);

  FakeRuntime exception_runtime;
  exception_runtime.throw_on_solve = true;
  const auto exception_result = run_method(make_instance(1), "previous", nullptr, exception_runtime);
  assert(exception_result.attempts.size() == 2);
  for (const auto& attempt : exception_result.attempts) assert(attempt.solve_attempted);

  auto unsupported = instance;
  unsupported.planner = "FASTER";
  FakeRuntime unsupported_runtime;
  const auto unsupported_result = run_method(unsupported, "bc", &policy, unsupported_runtime);
  assert(unsupported_result.fallback_reason == "unsupported_formulation");
  assert(unsupported_result.proposed.empty() && unsupported_result.fallback_used);
  assert(unsupported_result.attempts.size() == 1 && unsupported_result.attempts.front().fallback);

  cleanup();
  return 0;
}
