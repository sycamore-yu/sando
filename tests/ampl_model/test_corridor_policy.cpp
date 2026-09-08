#include <sando/corridor_policy.hpp>
#include <sando/segment_time.hpp>

#include <cassert>
#include <cmath>
#include <functional>
#include <limits>

namespace {
using namespace sando_learning;

nlohmann::json dense(int input, int output) {
  nlohmann::json weight = nlohmann::json::array();
  for (int i = 0; i < output; ++i) weight.push_back(std::vector<double>(input, 0.0));
  return {{"weight", weight}, {"bias", std::vector<double>(output, 0.0)}};
}

nlohmann::json model() {
  return {{"schema_version", 1}, {"kind", "sando_corridor_policy"}, {"n", 5}, {"norm", "Linf"},
          {"feature_spec", {{"version", 1}, {"origin", "start_position"},
                             {"spatial_scale", "max(1,max_map_extent)"},
                             {"velocity", "segment_dt/scale"},
                             {"acceleration", "segment_dt_squared/scale"},
                             {"plane_count", "raw"},
                             {"context_order", "start9_goal9_map6_dt5_factor"}}},
          {"layers", {{"plane1", dense(4, 32)}, {"plane2", dense(32, 32)},
                      {"score1", dense(355, 128)}, {"score2", dense(128, 64)},
                      {"score3", dense(64, 1)}}},
          {"metadata", {{"model", "test"}}}};
}

PlanningInstance instance(bool one_choice = false) {
  PlanningInstance x;
  x.factor = 1.0; x.initial_dt = 1.0; x.dc = 1.0; x.segment_dt = 2.0;
  x.start = {10., 20., 30., 0., 0., 0., 0., 0., 0.};
  x.goal = {12., 22., 32., 0., 0., 0., 0., 0., 0.};
  x.map_bounds = {0., 40., 0., 50., 0., 60.};
  x.corridors.resize(5); x.valid_mask.resize(5); x.assignment_variables.resize(5);
  for (int t = 0; t < 5; ++t) {
    x.corridors[t].resize(3);
    x.valid_mask[t] = one_choice ? std::vector<bool>{true, false, false}
                                 : std::vector<bool>{true, true, true};
    x.assignment_variables[t] = {1, 2, 3};
    for (std::size_t p = 0; p < x.corridors[t].size(); ++p)
      if (x.valid_mask[t][p]) x.corridors[t][p].planes = {{{1., 0., 0., 40.}}};
  }
  return x;
}

bool throws(const std::function<void()>& f) {
  try { f(); } catch (const std::exception&) { return true; }
  return false;
}
}

int main() {
  CorridorPolicy policy(model());
  const auto one = instance(true);
  const auto one_scores = policy.scores(one);
  const Assignment expected_one{0, 0, 0, 0, 0};
  assert(one_scores.size() == 1 && one_scores.front().first == expected_one);
  const auto debug = policy.debugJson(one);
  assert(debug.at("context").size() == 30);
  assert(debug.at("normalized_planes").size() == 5);
  assert(debug.at("layers").size() == 5);

  const auto all = instance(false);
  const auto ranked = policy.rank(all);
  assert(ranked.size() == 243);
  assert(ranked.front() == Assignment(5, 0));  // all scores tie; lexicographic order wins.

  auto none = instance(true);
  none.valid_mask[2] = {false, false, false};
  assert(throws([&] { policy.scores(none); }));
  for (auto& corridor : none.corridors[2]) corridor.planes.clear();
  assert(policy.scores(none).empty());

  auto bad_weight = model();
  bad_weight["layers"]["score3"]["weight"][0][0] = std::numeric_limits<double>::quiet_NaN();
  assert(throws([&] { CorridorPolicy invalid(bad_weight); }));
  auto bad_input = instance(true);
  bad_input.map_bounds[1] = std::numeric_limits<double>::infinity();
  assert(throws([&] { policy.scores(bad_input); }));
  return 0;
}
