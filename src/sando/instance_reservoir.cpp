#include <sando/instance_reservoir.hpp>

#include <fstream>
#include <limits>
#include <stdexcept>

namespace sando_learning {
namespace {

std::string requiredString(const nlohmann::json& metadata, const char* key) {
  const auto found = metadata.find(key);
  if (found == metadata.end() || !found->is_string() || found->get<std::string>().empty())
    throw std::invalid_argument(std::string("reservoir metadata requires ") + key);
  return found->get<std::string>();
}

}  // namespace

InstanceReservoir::InstanceReservoir(std::filesystem::path output, std::size_t capacity,
                                     std::uint64_t seed, nlohmann::json metadata)
    : output_(std::move(output)), capacity_(capacity), seed_(seed), metadata_(std::move(metadata)), rng_(seed) {
  if (output_.empty()) throw std::invalid_argument("reservoir output path is empty");
  if (capacity_ == 0 || capacity_ > 20)
    throw std::invalid_argument("reservoir capacity must be between 1 and 20");
  validateMetadata(metadata_);
  const auto summary = summaryPath();
  if (std::filesystem::exists(output_))
    throw std::invalid_argument("reservoir output already exists: " + output_.string());
  if (std::filesystem::exists(summary))
    throw std::invalid_argument("reservoir summary already exists: " + summary.string());
}

void InstanceReservoir::validateMetadata(const nlohmann::json& metadata) const {
  if (!metadata.is_object()) throw std::invalid_argument("reservoir metadata must be an object");
  requiredString(metadata, "scene_id");
  requiredString(metadata, "episode_id");
  requiredString(metadata, "source_id");
  requiredString(metadata, "config_id");
}

void InstanceReservoir::validate(const PlanningInstance& instance) const {
  validateInstance(instance, true);
  if (instance.scene_id != metadata_.at("scene_id").get<std::string>() ||
      instance.episode_id != metadata_.at("episode_id").get<std::string>() ||
      instance.source_id != metadata_.at("source_id").get<std::string>() ||
      instance.config_id != metadata_.at("config_id").get<std::string>())
    throw std::invalid_argument("planning instance metadata does not match reservoir episode");
}

void InstanceReservoir::recordInvalid(const std::string& reason) {
  ++invalid_count_;
  ++invalid_reasons_[reason.empty() ? "invalid instance" : reason];
}

void InstanceReservoir::reject(const std::string& reason) { recordInvalid(reason); }

void InstanceReservoir::ingest(const PlanningInstance& instance) {
  ingest(instance, nlohmann::json());
}

void InstanceReservoir::ingest(const PlanningInstance& instance, nlohmann::json observation) {
  try {
    validate(instance);
  } catch (const std::exception& error) {
    recordInvalid(error.what());
    return;
  }
  if (!observation.is_null() && !observation.empty()) {
    if (!observation.is_object()) throw std::invalid_argument("observation must be an object");
    observations_[instance.request_id] = std::move(observation);
  }
  const auto slot = chooseSlot();
  if (slot) put(*slot, instance);
}

std::filesystem::path InstanceReservoir::observationDir() const {
  const auto parent = output_.parent_path();
  return parent.empty() ? std::filesystem::path("request_observation")
                        : parent / "request_observation";
}

std::string observationFileName(const std::string& request_id) {
  if (request_id.empty()) throw std::invalid_argument("observation request_id is empty");
  for (char ch : request_id) {
    const bool ok = (ch >= '0' && ch <= '9') || (ch >= 'A' && ch <= 'Z') ||
                    (ch >= 'a' && ch <= 'z') || ch == '_' || ch == '-' || ch == '.';
    if (!ok) throw std::invalid_argument("observation request_id contains unsafe characters");
  }
  return request_id + ".json";
}

std::optional<std::size_t> InstanceReservoir::chooseSlot() {
  if (total_eligible_ == std::numeric_limits<std::size_t>::max())
    throw std::overflow_error("reservoir eligibility count overflow");
  ++total_eligible_;
  if (samples_.size() < capacity_) return samples_.size();
  const auto draw = std::uniform_int_distribution<std::size_t>(0, total_eligible_ - 1)(rng_);
  if (draw < capacity_) return draw;
  return std::nullopt;
}

void InstanceReservoir::put(std::size_t slot, const PlanningInstance& instance) {
  validate(instance);
  if (slot >= capacity_ || slot > samples_.size())
    throw std::out_of_range("reservoir slot is outside the retained sample set");
  if (slot == samples_.size()) samples_.push_back(instance);
  else samples_[slot] = instance;
}

void InstanceReservoir::flush() {
  const auto summary = summaryPath();
  if (std::filesystem::exists(output_) && !output_owned_)
    throw std::runtime_error("refusing to overwrite unowned reservoir output");
  if (std::filesystem::exists(summary) && !output_owned_)
    throw std::runtime_error("refusing to overwrite unowned reservoir summary");

  const auto parent = output_.parent_path();
  if (!parent.empty()) std::filesystem::create_directories(parent);
  const auto suffix = ".tmp." + std::to_string(seed_);
  const auto output_tmp = output_.string() + suffix;
  const auto summary_tmp = summary.string() + suffix;
  if (std::filesystem::exists(output_tmp) || std::filesystem::exists(summary_tmp))
    throw std::runtime_error("reservoir temporary output already exists");

  nlohmann::json summary_json = {
      {"schema_version", 1},
      {"metadata", metadata_},
      {"seed", seed_},
      {"capacity", capacity_},
      {"total_eligible", total_eligible_},
      {"retained", samples_.size()},
      {"invalid_count", invalid_count_},
      {"invalid_reasons", nlohmann::json::object()}};
  for (const auto& [reason, count] : invalid_reasons_) summary_json["invalid_reasons"][reason] = count;

  {
    std::ofstream stream(output_tmp, std::ios::binary | std::ios::trunc);
    if (!stream) throw std::runtime_error("cannot create reservoir output: " + output_tmp);
    for (const auto& instance : samples_) stream << toJson(instance).dump() << '\n';
    stream.flush();
    if (!stream) throw std::runtime_error("cannot write reservoir output: " + output_tmp);
  }
  {
    std::ofstream stream(summary_tmp, std::ios::binary | std::ios::trunc);
    if (!stream) throw std::runtime_error("cannot create reservoir summary: " + summary_tmp);
    stream << summary_json.dump(2) << '\n';
    stream.flush();
    if (!stream) throw std::runtime_error("cannot write reservoir summary: " + summary_tmp);
  }
  std::filesystem::rename(output_tmp, output_);
  try {
    std::filesystem::rename(summary_tmp, summary);
  } catch (...) {
    // The data file remains valid, but leave no temporary summary behind.
    std::error_code ignored;
    std::filesystem::remove(summary_tmp, ignored);
    throw;
  }
  output_owned_ = true;

  const auto obs_dir = observationDir();
  std::error_code ignored;
  if (std::filesystem::exists(obs_dir)) {
    for (const auto& entry : std::filesystem::directory_iterator(obs_dir)) {
      if (entry.is_regular_file()) std::filesystem::remove(entry.path(), ignored);
    }
  }
  std::map<std::string, bool> retained_requests;
  for (const auto& instance : samples_) retained_requests[instance.request_id] = true;
  std::size_t observation_count = 0;
  for (const auto& [request_id, _] : retained_requests) {
    const auto found = observations_.find(request_id);
    if (found == observations_.end()) continue;
    std::filesystem::create_directories(obs_dir);
    const auto path = obs_dir / observationFileName(request_id);
    const auto tmp = path.string() + suffix;
    {
      std::ofstream stream(tmp, std::ios::binary | std::ios::trunc);
      if (!stream) throw std::runtime_error("cannot create observation file: " + tmp);
      stream << found->second.dump() << '\n';
      stream.flush();
      if (!stream) throw std::runtime_error("cannot write observation file: " + tmp);
    }
    std::filesystem::rename(tmp, path);
    ++observation_count;
  }
  summary_json["observation_count"] = observation_count;
  {
    std::ofstream stream(summary, std::ios::binary | std::ios::trunc);
    if (!stream) throw std::runtime_error("cannot update reservoir summary: " + summary.string());
    stream << summary_json.dump(2) << '\n';
  }
}

}  // namespace sando_learning
