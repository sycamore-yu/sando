#include <sando/frozen_planning_observation.hpp>
#include <sando/reconstruct_planning_request.hpp>

#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void usage() {
  std::cerr << "usage: reconstruct_planning_request --observation FILE --factor F [--output FILE]\n";
}

}  // namespace

int main(int argc, char** argv) {
  std::string observation_path;
  std::string output_path;
  double factor = 0.0;
  bool factor_given = false;
  for (int i = 1; i < argc; ++i) {
    const std::string arg = argv[i];
    if (arg == "--observation" && i + 1 < argc)
      observation_path = argv[++i];
    else if (arg == "--factor" && i + 1 < argc) {
      factor = std::stod(argv[++i]);
      factor_given = true;
    } else if (arg == "--output" && i + 1 < argc)
      output_path = argv[++i];
    else {
      usage();
      return 2;
    }
  }
  if (observation_path.empty() || !factor_given) {
    usage();
    return 2;
  }
  try {
    std::ifstream in(observation_path);
    if (!in) throw std::runtime_error("cannot open observation file");
    const auto observation = sando_learning::frozenObservationFromJson(nlohmann::json::parse(in));
    const auto result = sando_learning::solveReconstructedRequest(observation, factor);
    auto encoded = sando_learning::reconstructedSolveToJson(result);
    encoded["observation_id"] = observation.observation_id;
    encoded["observation_sha256"] = sando_learning::observationContentSha256(observation);
    encoded["map_sha256"] = sando_learning::mapContentSha256(observation);
    if (output_path.empty())
      std::cout << encoded.dump(2) << '\n';
    else {
      std::ofstream out(output_path);
      if (!out) throw std::runtime_error("cannot open output file");
      out << encoded.dump(2) << '\n';
    }
    if (result.status == "rebuild_error" || result.status == "numerical_error") return 1;
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "reconstruct_planning_request: " << error.what() << '\n';
    return 1;
  }
}
