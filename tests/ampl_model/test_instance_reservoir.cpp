#include <sando/instance_reservoir.hpp>
#include <sando/segment_time.hpp>

#include <cassert>
#include <chrono>
#include <fstream>
#include <functional>
#include <sstream>
#include <stdexcept>

namespace {
using namespace sando_learning;
using sando_ampl::GRB_BINARY;

PlanningInstance makeInstance(int index) {
  PlanningInstance instance;
  instance.scene_id = "scene";
  instance.episode_id = "episode";
  instance.request_id = "request_" + std::to_string(index);
  instance.source_id = "source";
  instance.config_id = "config";
  instance.factor = 1.5;
  instance.initial_dt = .1;
  instance.dc = .05;
  instance.segment_dt = sando_time::segmentDuration(instance.initial_dt, instance.dc, instance.factor);
  instance.start = {0., 0., 1., 0., 0., 0., 0., 0., 0.};
  instance.goal = {1., 1., 2., 0., 0., 0., 0., 0., 0.};
  instance.map_bounds = {-2., 2., -2., 2., 0., 4.};
  instance.corridors.resize(5);
  instance.valid_mask.resize(5);
  instance.assignment_variables.resize(5);
  for (int t = 0; t < 5; ++t) {
    instance.corridors[t] = {{{{{1., 0., 0., 2.}}}, {{{0., 1., 0., 2.}}}}};
    instance.valid_mask[t] = {true, true};
    instance.assignment_variables[t] = {static_cast<std::uint64_t>(t * 2 + 1),
                                        static_cast<std::uint64_t>(t * 2 + 2)};
  }
  for (int id = 1; id <= 10; ++id)
    instance.model.variables.push_back({static_cast<std::uint64_t>(id), "s", 0., 1., 0., GRB_BINARY});
  for (auto& axis : instance.coefficients)
    for (int i = 0; i < 20; ++i) axis.push_back({static_cast<double>(i), {}, {}});
  instance.runtime.time_limit = 30.;
  return instance;
}

nlohmann::json metadata() {
  return {{"scene_id", "scene"}, {"episode_id", "episode"},
          {"source_id", "source"}, {"config_id", "config"}};
}

bool throws(const std::function<void()>& function) {
  try { function(); } catch (const std::exception&) { return true; }
  return false;
}

std::string read(const std::filesystem::path& path) {
  std::ifstream stream(path, std::ios::binary);
  std::ostringstream contents;
  contents << stream.rdbuf();
  return contents.str();
}

}  // namespace

int main() {
  const auto root = std::filesystem::temp_directory_path() /
                    ("sando_reservoir_" + std::to_string(
                        std::chrono::steady_clock::now().time_since_epoch().count()));
  std::filesystem::create_directories(root);
  try {
    const auto first_path = root / "first.jsonl";
    const auto second_path = root / "second.jsonl";
    InstanceReservoir first(first_path, 3, 12345, metadata());
    InstanceReservoir second(second_path, 3, 12345, metadata());
    for (int i = 0; i < 20; ++i) {
      auto instance = makeInstance(i);
      first.ingest(instance);
      second.ingest(instance);
    }
    auto invalid = makeInstance(20);
    invalid.segment_dt += 1.;
    first.ingest(invalid);
    second.reject("model unavailable");
    assert(first.totalEligible() == 20);
    assert(first.retained() == 3);
    assert(first.invalidCount() == 1);
    assert(second.totalEligible() == 20);
    assert(second.invalidCount() == 1);
    first.flush();
    second.flush();
    assert(read(first_path) == read(second_path));

    std::ifstream lines(first_path);
    std::string line;
    std::size_t count = 0;
    bool retained_late_entry = false;
    while (std::getline(lines, line)) {
      const auto decoded = fromJson(nlohmann::json::parse(line));
      validateInstance(decoded);
      retained_late_entry = retained_late_entry ||
                            std::stoi(decoded.request_id.substr(std::string("request_").size())) >= 10;
      ++count;
    }
    assert(count == 3);
    assert(retained_late_entry);
    const auto summary = nlohmann::json::parse(read(first.summaryPath()));
    assert(summary.at("total_eligible") == 20);
    assert(summary.at("retained") == 3);
    assert(summary.at("invalid_count") == 1);
    assert(summary.at("metadata").at("scene_id") == "scene");

    // A reservoir owns its paths after the first flush, so repeated flushes
    // are permitted while pre-existing unrelated paths are rejected.
    first.flush();
    const auto occupied = root / "occupied.jsonl";
    std::ofstream(occupied) << "foreign\n";
    assert(throws([&] { InstanceReservoir bad(occupied, 1, 1, metadata()); }));
    assert(throws([&] { InstanceReservoir bad(root / "new.jsonl", 0, 1, metadata()); }));
    assert(throws([&] { InstanceReservoir bad(root / "new2.jsonl", 11, 1, metadata()); }));
    assert(throws([&] { InstanceReservoir bad(root / "new3.jsonl", 1, 1, {{"scene_id", "s"}}); }));

    std::filesystem::remove_all(root);
    return 0;
  } catch (...) {
    std::filesystem::remove_all(root);
    throw;
  }
}
