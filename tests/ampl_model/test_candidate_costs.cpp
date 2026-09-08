#include <sando/candidate_costs.hpp>
#include <sando/segment_time.hpp>

#include <cassert>
#include <cmath>
#include <memory>
#include <vector>

namespace sando_ampl {
std::shared_ptr<Runtime> createRuntime() { return {}; }
}  // namespace sando_ampl

namespace {
using namespace sando_ampl;
using namespace sando_learning;

class QueueRuntime final : public Runtime {
 public:
  std::vector<RuntimeResult> queue;
  std::vector<double> limits;
  RuntimeResult solve(const ModelSnapshot& model, GRBCallback*, const RuntimeParameters& parameters) override {
    limits.push_back(parameters.time_limit);
    if (queue.empty()) return {GRB_INTERRUPTED, 0., .01, {}};
    auto result = queue.front();
    queue.erase(queue.begin());
    if (result.status == GRB_OPTIMAL) result.objective = evaluate(model.objective, result.values);
    return result;
  }
};

PlanningInstance instance(int choices) {
  PlanningInstance value;
  value.factor = 1.; value.initial_dt = .1; value.dc = .05;
  value.segment_dt = sando_time::segmentDuration(value.initial_dt, value.dc, value.factor);
  value.start = {0., 0., 1., 0., 0., 0., 0., 0., 0.};
  value.goal = {1., 1., 2., 0., 0., 0., 0., 0., 0.};
  value.map_bounds = {-2., 2., -2., 2., 0., 4.};
  value.corridors.resize(5); value.valid_mask.resize(5); value.assignment_variables.resize(5);
  for (int t = 0; t < 5; ++t) {
    for (int p = 0; p < choices; ++p) {
      value.corridors[t].push_back({{{1., 0., 0., 3.}}});
      value.valid_mask[t].push_back(true);
      const auto id = static_cast<std::uint64_t>(t * choices + p + 1);
      value.assignment_variables[t].push_back(id);
      value.model.variables.push_back({id, "s", 0., 1., 0., GRB_BINARY});
      value.model.objective.linear.push_back({id, static_cast<double>(t * choices + p + 1)});
    }
  }
  for (auto& axis : value.coefficients) axis.resize(20);
  return value;
}

RuntimeResult status(int code) { return {code, 0., .01, {}}; }

}  // namespace

int main() {
  auto two = instance(2);
  validateInstance(two);
  QueueRuntime feasible;
  feasible.queue = {status(GRB_OPTIMAL)};
  auto candidate = evaluateCandidate(two, {0, 0, 0, 0, 0}, feasible);
  assert(candidate.classification == "feasible");
  assert(candidate.raw_objective == 25.);
  assert(candidate.attempts.size() == 1);
  assert(feasible.limits.size() == 1 && feasible.limits.front() == two.runtime.time_limit);

  QueueRuntime retry;
  retry.queue = {status(GRB_INTERRUPTED), status(GRB_OPTIMAL)};
  candidate = evaluateCandidate(two, {0, 1, 0, 1, 0}, retry);
  assert(candidate.classification == "feasible" && candidate.attempts.size() == 2);
  assert(retry.limits.size() == 2 && retry.limits.back() == 10.);

  QueueRuntime proven;
  proven.queue = {status(GRB_INFEASIBLE)};
  candidate = evaluateCandidate(two, {1, 1, 1, 1, 1}, proven);
  assert(candidate.classification == "infeasible" && candidate.attempts.size() == 1);

  QueueRuntime all_infeasible;
  all_infeasible.queue = {status(GRB_INFEASIBLE)};
  const auto excluded = evaluateInstanceJson(instance(1), all_infeasible);
  assert(excluded.at("total_valid_assignments") == 1);
  assert(excluded.at("costs_complete") == false);
  assert(excluded.at("failurestats").at("all_infeasible") == true);
  assert(excluded.at("candidates").at(0).at("cost").is_null());

  QueueRuntime unknown;
  unknown.queue = {status(GRB_INTERRUPTED), status(GRB_INTERRUPTED)};
  const auto unknown_result = evaluateInstanceJson(instance(1), unknown);
  assert(unknown_result.at("failurestats").at("all_infeasible") == false);
  assert(unknown_result.at("excluded_reason") == "unknown_or_infeasible_results");

  QueueRuntime negatives;
  negatives.queue.assign(32, status(GRB_OPTIMAL));
  auto negative_instance = instance(2);
  negative_instance.model.objective.constant = -100.;
  const auto result = evaluateInstanceJson(negative_instance, negatives);
  assert(result.at("costs_complete") == true);
  assert(result.at("candidates").front().at("cost") == 0.0);
  assert(result.at("candidates").back().at("cost") == 1.0);
  QueueRuntime mixed;
  mixed.queue.assign(32, status(GRB_OPTIMAL));
  mixed.queue.back() = status(GRB_INFEASIBLE);
  const auto mixed_result = evaluateInstanceJson(two, mixed);
  assert(mixed_result.at("costs_complete") == true);
  assert(mixed_result.at("candidates").back().at("cost") == 2.0);
  QueueRuntime ambiguous;
  ambiguous.queue = {status(GRB_INF_OR_UNBD), status(GRB_INF_OR_UNBD)};
  const auto ambiguous_result = evaluateInstanceJson(instance(1), ambiguous);
  assert(ambiguous_result.at("failurestats").at("unknown") == 1);
  assert(!ambiguous_result.at("costs_complete").get<bool>());
  QueueRuntime tied;
  tied.queue.assign(32, status(GRB_OPTIMAL));
  auto tied_instance = two;
  tied_instance.model.objective.linear.clear();
  tied_instance.model.objective.constant = -1.0;
  const auto tied_result = evaluateInstanceJson(tied_instance, tied);
  for (const auto& item : tied_result.at("candidates")) assert(item.at("cost") == 0.0);
  return 0;
}
