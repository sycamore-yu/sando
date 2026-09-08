#include <sando/corridor_policy.hpp>

#include <fstream>
#include <iostream>

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: corridor_policy_probe MODEL.json INSTANCE.json\n";
    return 2;
  }
  try {
    const auto policy = sando_learning::CorridorPolicy::load(argv[1]);
    std::ifstream stream(argv[2]);
    if (!stream) throw std::runtime_error("cannot open planning instance");
    nlohmann::json encoded;
    stream >> encoded;
    const auto instance = sando_learning::fromJson(encoded);
    std::cout << policy.debugJson(instance).dump(2) << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "corridor_policy_probe FAIL: " << error.what() << '\n';
    return 1;
  }
}
