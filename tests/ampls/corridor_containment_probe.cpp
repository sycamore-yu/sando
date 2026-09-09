// Diagnose whether reconstructed corridors contain start/goal and connect layers.
#include <sando/frozen_planning_observation.hpp>
#include <sando/planning_instance.hpp>
#include <sando/reconstruct_planning_request.hpp>

#include <nlohmann/json.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using json = nlohmann::json;
using sando_learning::Corridor;
using sando_learning::FrozenPlanningObservation;
using sando_learning::PlanningInstance;

constexpr double kEps = 1e-6;

void require(bool ok, const std::string& message) {
  if (!ok) throw std::runtime_error(message);
}

FrozenPlanningObservation load_observation(const std::string& path) {
  std::ifstream in(path);
  require(static_cast<bool>(in), "cannot open observation: " + path);
  return sando_learning::frozenObservationFromJson(json::parse(in));
}

bool point_in_corridor(const Corridor& c, double x, double y, double z, double* min_slack) {
  if (c.planes.empty()) {
    if (min_slack) *min_slack = -std::numeric_limits<double>::infinity();
    return false;
  }
  double slack = std::numeric_limits<double>::infinity();
  for (const auto& p : c.planes) {
    const double s = p[3] - (p[0] * x + p[1] * y + p[2] * z);
    slack = std::min(slack, s);
  }
  if (min_slack) *min_slack = slack;
  return slack >= -kEps;
}

json layer_report(const std::vector<Corridor>& layer, double x, double y, double z,
                  const char* label) {
  json polys = json::array();
  int inside = 0;
  for (size_t p = 0; p < layer.size(); ++p) {
    double slack = 0.0;
    const bool ok = point_in_corridor(layer[p], x, y, z, &slack);
    if (ok) ++inside;
    polys.push_back({{"p", p},
                     {"plane_count", layer[p].planes.size()},
                     {"inside", ok},
                     {"min_slack", slack}});
  }
  return {{"label", label},
          {"point", {x, y, z}},
          {"P", layer.size()},
          {"inside_count", inside},
          {"polytopes", std::move(polys)}};
}

// Cheap connectivity: shared free AABB overlap of two polytopes via plane AABBs is hard;
// instead report pairwise midpoint of endpoints feasibility: sample line start->goal
// and whether any poly on each layer covers the corresponding sample (weak signal).
json weak_path_cover(const PlanningInstance& inst) {
  const double sx = inst.start[0], sy = inst.start[1], sz = inst.start[2];
  const double gx = inst.goal[0], gy = inst.goal[1], gz = inst.goal[2];
  json layers = json::array();
  const int N = static_cast<int>(inst.corridors.size());
  for (int t = 0; t < N; ++t) {
    const double a = (N <= 1) ? 0.0 : static_cast<double>(t) / static_cast<double>(N - 1);
    const double x = sx + a * (gx - sx);
    const double y = sy + a * (gy - sy);
    const double z = sz + a * (gz - sz);
    int inside = 0;
    double best = -std::numeric_limits<double>::infinity();
    for (const auto& c : inst.corridors[static_cast<size_t>(t)]) {
      double slack = 0.0;
      if (point_in_corridor(c, x, y, z, &slack)) ++inside;
      best = std::max(best, slack);
    }
    layers.push_back({{"t", t},
                      {"alpha", a},
                      {"point", {x, y, z}},
                      {"inside_count", inside},
                      {"best_slack", best}});
  }
  return layers;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    const std::string observation_path =
        argc > 1 ? argv[1]
                 : "docker/dev-workspace/results/joint-time-v2/stage-jia/"
                   "static_forest-easy-seed0/request_observation/2.json";
    const double factor = argc > 2 ? std::stod(argv[2]) : 2.0;
    const std::string out_path = argc > 3 ? argv[3] : "";

    const auto observation = load_observation(observation_path);
    const auto solved = sando_learning::solveReconstructedRequest(observation, factor);
    require(solved.status != "rebuild_error", "rebuild_error: " + solved.error);

    PlanningInstance instance = solved.geometry.instance;
    // MIQP may be infeasible; still want corridors + start/goal.
    require(!instance.corridors.empty(), "empty corridors");

    json report = {
        {"observation", observation_path},
        {"factor", factor},
        {"status", solved.status},
        {"solver_kind", solved.solver_kind},
        {"N", instance.n},
        {"P", instance.corridors.front().size()},
        {"start", instance.start},
        {"goal", instance.goal},
        {"map_bounds", instance.map_bounds},
        {"segment_dt", instance.segment_dt},
        {"start_layer0", layer_report(instance.corridors.front(), instance.start[0],
                                      instance.start[1], instance.start[2], "start")},
        {"goal_layerN", layer_report(instance.corridors.back(), instance.goal[0],
                                     instance.goal[1], instance.goal[2], "goal")},
        {"weak_path_cover", weak_path_cover(instance)},
    };

    // Also check start against ALL layers and goal against ALL layers.
    json start_all = json::array();
    json goal_all = json::array();
    for (size_t t = 0; t < instance.corridors.size(); ++t) {
      start_all.push_back(layer_report(instance.corridors[t], instance.start[0],
                                       instance.start[1], instance.start[2], "start"));
      start_all.back()["t"] = t;
      goal_all.push_back(layer_report(instance.corridors[t], instance.goal[0], instance.goal[1],
                                      instance.goal[2], "goal"));
      goal_all.back()["t"] = t;
    }
    report["start_all_layers"] = start_all;
    report["goal_all_layers"] = goal_all;

    const int start_inside0 = report["start_layer0"]["inside_count"].get<int>();
    const int goal_insideN = report["goal_layerN"]["inside_count"].get<int>();
    report["verdict"] = {
        {"start_in_layer0", start_inside0 > 0},
        {"goal_in_layerN", goal_insideN > 0},
        {"likely_containment_bug", start_inside0 == 0 || goal_insideN == 0},
    };

    const std::string text = report.dump(2);
    if (!out_path.empty()) {
      std::ofstream out(out_path);
      require(static_cast<bool>(out), "cannot write " + out_path);
      out << text << '\n';
      std::cerr << "wrote " << out_path << '\n';
    }
    std::cout << text << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "corridor_containment_probe: " << error.what() << '\n';
    return 1;
  }
}
