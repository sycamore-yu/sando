#pragma once

#include <sando/planning_instance.hpp>
#include <nlohmann/json.hpp>

#include <cstdint>
#include <filesystem>
#include <map>
#include <optional>
#include <random>
#include <string>
#include <vector>

namespace sando_learning {

// A bounded, deterministic reservoir for valid planning instances from one
// capture episode.  Validation happens before an instance enters the
// reservoir, so invalid data cannot consume an eligibility slot.
class InstanceReservoir {
 public:
  InstanceReservoir(std::filesystem::path output, std::size_t capacity,
                    std::uint64_t seed, nlohmann::json metadata);

  void ingest(const PlanningInstance& instance);
  void ingest(const PlanningInstance& instance, nlohmann::json observation);
  void reject(const std::string& reason);
  void flush();
  std::filesystem::path observationDir() const;

  std::size_t capacity() const noexcept { return capacity_; }
  std::size_t totalEligible() const noexcept { return total_eligible_; }
  std::size_t retained() const noexcept { return samples_.size(); }
  std::size_t invalidCount() const noexcept { return invalid_count_; }
  const std::map<std::string, std::size_t>& invalidReasons() const noexcept {
    return invalid_reasons_;
  }
  const std::filesystem::path& outputPath() const noexcept { return output_; }
  std::filesystem::path summaryPath() const { return output_.string() + ".summary.json"; }

 private:
  void validateMetadata(const nlohmann::json& metadata) const;
  void validate(const PlanningInstance& instance) const;
  void recordInvalid(const std::string& reason);
  std::optional<std::size_t> chooseSlot();
  void put(std::size_t slot, const PlanningInstance& instance);

  std::filesystem::path output_;
  std::size_t capacity_;
  std::uint64_t seed_;
  nlohmann::json metadata_;
  std::mt19937_64 rng_;
  std::size_t total_eligible_{0};
  std::size_t invalid_count_{0};
  std::map<std::string, std::size_t> invalid_reasons_;
  std::vector<PlanningInstance> samples_;
  std::map<std::string, nlohmann::json> observations_;
  bool output_owned_{false};
};

}  // namespace sando_learning
