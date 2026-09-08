#pragma once

#include <sando/planning_instance.hpp>
#include <nlohmann/json.hpp>
#include <Eigen/Core>

#include <filesystem>
#include <array>
#include <utility>
#include <vector>

namespace sando_learning {

class CorridorPolicy {
 public:
  struct Dense {
    Eigen::MatrixXd weight;
    Eigen::VectorXd bias;
    bool relu{false};
    std::vector<double> apply(const std::vector<double>& input) const;
  };
  explicit CorridorPolicy(const nlohmann::json& model);
  explicit CorridorPolicy(const std::filesystem::path& path);
  static CorridorPolicy load(const std::filesystem::path& path);

  std::vector<std::pair<Assignment, double>> scores(const PlanningInstance& instance) const;
  std::vector<Assignment> rank(const PlanningInstance& instance) const;
  nlohmann::json debugJson(const PlanningInstance& instance) const;

 private:
  Dense plane1_, plane2_, score1_, score2_, score3_;
  nlohmann::json model_;
  void validateModel() const;
  std::vector<double> context(const PlanningInstance&, double scale) const;
  std::vector<std::vector<std::vector<std::array<double, 4>>>> normalizedPlanes(
      const PlanningInstance&, double scale) const;
  std::vector<double> corridorEncoding(const std::vector<std::array<double, 4>>& planes) const;
};

}  // namespace sando_learning
