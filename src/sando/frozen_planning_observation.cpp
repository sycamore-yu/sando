#include <sando/frozen_planning_observation.hpp>

#include <cmath>
#include <cstring>
#include <stdexcept>

namespace sando_learning {
namespace {

using json = nlohmann::json;

[[noreturn]] void fail(const std::string& message) { throw std::invalid_argument(message); }

void finite(double value, const char* what) {
  if (!std::isfinite(value)) fail(std::string("non-finite ") + what);
}

void appendBytes(std::vector<unsigned char>& out, const void* data, std::size_t n) {
  const auto* bytes = static_cast<const unsigned char*>(data);
  out.insert(out.end(), bytes, bytes + n);
}

void appendU32(std::vector<unsigned char>& out, std::uint32_t value) {
  unsigned char bytes[4] = {static_cast<unsigned char>(value),
                            static_cast<unsigned char>(value >> 8),
                            static_cast<unsigned char>(value >> 16),
                            static_cast<unsigned char>(value >> 24)};
  appendBytes(out, bytes, 4);
}

void appendI32(std::vector<unsigned char>& out, int value) {
  appendU32(out, static_cast<std::uint32_t>(value));
}

void appendF64(std::vector<unsigned char>& out, double value) {
  finite(value, "hash field");
  appendBytes(out, &value, sizeof(value));
}

void appendString(std::vector<unsigned char>& out, const std::string& value) {
  appendU32(out, static_cast<std::uint32_t>(value.size()));
  appendBytes(out, value.data(), value.size());
}

std::string hexDigest(const unsigned char digest[32]) {
  static const char* kHex = "0123456789abcdef";
  std::string text(64, '0');
  for (int i = 0; i < 32; ++i) {
    text[static_cast<std::size_t>(2 * i)] = kHex[(digest[i] >> 4) & 0xf];
    text[static_cast<std::size_t>(2 * i + 1)] = kHex[digest[i] & 0xf];
  }
  return text;
}

class Sha256 {
 public:
  Sha256() { reset(); }

  void update(const unsigned char* data, std::size_t length) {
    for (std::size_t i = 0; i < length; ++i) {
      data_[datalen_++] = data[i];
      if (datalen_ == 64) {
        transform();
        bitlen_ += 512;
        datalen_ = 0;
      }
    }
  }

  void update(const std::vector<unsigned char>& data) {
    if (!data.empty()) update(data.data(), data.size());
  }

  void final(unsigned char hash[32]) {
    std::size_t i = datalen_;
    if (datalen_ < 56) {
      data_[i++] = 0x80;
      while (i < 56) data_[i++] = 0x00;
    } else {
      data_[i++] = 0x80;
      while (i < 64) data_[i++] = 0x00;
      transform();
      std::memset(data_, 0, 56);
    }
    bitlen_ += static_cast<std::uint64_t>(datalen_) * 8;
    data_[63] = static_cast<unsigned char>(bitlen_);
    data_[62] = static_cast<unsigned char>(bitlen_ >> 8);
    data_[61] = static_cast<unsigned char>(bitlen_ >> 16);
    data_[60] = static_cast<unsigned char>(bitlen_ >> 24);
    data_[59] = static_cast<unsigned char>(bitlen_ >> 32);
    data_[58] = static_cast<unsigned char>(bitlen_ >> 40);
    data_[57] = static_cast<unsigned char>(bitlen_ >> 48);
    data_[56] = static_cast<unsigned char>(bitlen_ >> 56);
    transform();
    for (i = 0; i < 4; ++i) {
      hash[i] = (state_[0] >> (24 - i * 8)) & 0x000000ff;
      hash[i + 4] = (state_[1] >> (24 - i * 8)) & 0x000000ff;
      hash[i + 8] = (state_[2] >> (24 - i * 8)) & 0x000000ff;
      hash[i + 12] = (state_[3] >> (24 - i * 8)) & 0x000000ff;
      hash[i + 16] = (state_[4] >> (24 - i * 8)) & 0x000000ff;
      hash[i + 20] = (state_[5] >> (24 - i * 8)) & 0x000000ff;
      hash[i + 24] = (state_[6] >> (24 - i * 8)) & 0x000000ff;
      hash[i + 28] = (state_[7] >> (24 - i * 8)) & 0x000000ff;
    }
  }

 private:
  void reset() {
    datalen_ = 0;
    bitlen_ = 0;
    state_[0] = 0x6a09e667;
    state_[1] = 0xbb67ae85;
    state_[2] = 0x3c6ef372;
    state_[3] = 0xa54ff53a;
    state_[4] = 0x510e527f;
    state_[5] = 0x9b05688c;
    state_[6] = 0x1f83d9ab;
    state_[7] = 0x5be0cd19;
  }

  static std::uint32_t rotr(std::uint32_t x, std::uint32_t n) { return (x >> n) | (x << (32 - n)); }

  void transform() {
    static const std::uint32_t k[64] = {
        0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4,
        0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe,
        0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f,
        0x4a7484aa, 0x5cb0a9dc, 0x76f988da, 0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7,
        0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc,
        0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
        0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070, 0x19a4c116,
        0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
        0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7,
        0xc67178f2};
    std::uint32_t m[64];
    for (int i = 0, j = 0; i < 16; ++i, j += 4)
      m[i] = (static_cast<std::uint32_t>(data_[j]) << 24) |
             (static_cast<std::uint32_t>(data_[j + 1]) << 16) |
             (static_cast<std::uint32_t>(data_[j + 2]) << 8) |
             static_cast<std::uint32_t>(data_[j + 3]);
    for (int i = 16; i < 64; ++i) {
      const std::uint32_t s0 = rotr(m[i - 15], 7) ^ rotr(m[i - 15], 18) ^ (m[i - 15] >> 3);
      const std::uint32_t s1 = rotr(m[i - 2], 17) ^ rotr(m[i - 2], 19) ^ (m[i - 2] >> 10);
      m[i] = m[i - 16] + s0 + m[i - 7] + s1;
    }
    std::uint32_t a = state_[0], b = state_[1], c = state_[2], d = state_[3];
    std::uint32_t e = state_[4], f = state_[5], g = state_[6], h = state_[7];
    for (int i = 0; i < 64; ++i) {
      const std::uint32_t S1 = rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25);
      const std::uint32_t ch = (e & f) ^ ((~e) & g);
      const std::uint32_t temp1 = h + S1 + ch + k[i] + m[i];
      const std::uint32_t S0 = rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22);
      const std::uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
      const std::uint32_t temp2 = S0 + maj;
      h = g;
      g = f;
      f = e;
      e = d + temp1;
      d = c;
      c = b;
      b = a;
      a = temp1 + temp2;
    }
    state_[0] += a;
    state_[1] += b;
    state_[2] += c;
    state_[3] += d;
    state_[4] += e;
    state_[5] += f;
    state_[6] += g;
    state_[7] += h;
  }

  unsigned char data_[64]{};
  std::uint32_t datalen_{0};
  std::uint64_t bitlen_{0};
  std::uint32_t state_[8]{};
};

std::string sha256(const std::vector<unsigned char>& payload) {
  Sha256 hasher;
  hasher.update(payload);
  unsigned char digest[32];
  hasher.final(digest);
  return hexDigest(digest);
}

json pointArray(const std::vector<std::array<double, 3>>& points) {
  json out = json::array();
  for (const auto& point : points) out.push_back({point[0], point[1], point[2]});
  return out;
}

std::vector<std::array<double, 3>> parsePoints(const json& value, const char* what) {
  if (!value.is_array()) fail(std::string(what) + " must be an array");
  std::vector<std::array<double, 3>> points;
  points.reserve(value.size());
  for (const auto& item : value) {
    if (!item.is_array() || item.size() != 3) fail(std::string(what) + " entries must have 3 numbers");
    std::array<double, 3> point{};
    for (int i = 0; i < 3; ++i) {
      if (!item[i].is_number()) fail(std::string(what) + " entries must have 3 numbers");
      point[static_cast<std::size_t>(i)] = item[i].get<double>();
      finite(point[static_cast<std::size_t>(i)], what);
    }
    points.push_back(point);
  }
  return points;
}

json stateArray(const std::array<double, 9>& state) {
  json out = json::array();
  for (double value : state) out.push_back(value);
  return out;
}

std::array<double, 9> parseState(const json& value, const char* what) {
  if (!value.is_array() || value.size() != 9) fail(std::string(what) + " must have 9 numbers");
  std::array<double, 9> state{};
  for (int i = 0; i < 9; ++i) {
    if (!value[i].is_number()) fail(std::string(what) + " must have 9 numbers");
    state[static_cast<std::size_t>(i)] = value[i].get<double>();
    finite(state[static_cast<std::size_t>(i)], what);
  }
  return state;
}

void requireText(const std::string& value, const char* what) {
  if (value.empty()) fail(std::string(what) + " is empty");
}

}  // namespace

std::string sha256Hex(const std::string& text) {
  return sha256(std::vector<unsigned char>(text.begin(), text.end()));
}

std::string sha256BytesHex(const std::vector<unsigned char>& payload) { return sha256(payload); }

void validateFrozenObservation(const FrozenPlanningObservation& observation) {
  if (observation.schema_version != 1) fail("unsupported frozen observation schema");
  if (observation.kind != "sando_frozen_planning_observation") fail("unexpected frozen observation kind");
  requireText(observation.observation_id, "observation_id");
  requireText(observation.request_id, "request_id");
  if (observation.n <= 0) fail("invalid n");
  finite(observation.A_time, "A_time");
  finite(observation.planning_start_time, "planning_start_time");
  finite(observation.observation_time, "observation_time");
  finite(observation.initial_dt, "initial_dt");
  finite(observation.dc, "dc");
  if (observation.initial_dt < 0.0 || observation.dc <= 0.0) fail("invalid time inputs");
  for (double value : observation.start) finite(value, "start");
  for (double value : observation.goal) finite(value, "goal");
  finite(observation.v_max, "v_max");
  finite(observation.a_max, "a_max");
  finite(observation.j_max, "j_max");
  finite(observation.jerk_smooth_weight, "jerk_smooth_weight");
  finite(observation.res, "res");
  finite(observation.factor_hgp, "factor_hgp");
  if (!(observation.res > 0.0) || !(observation.factor_hgp > 0.0)) fail("invalid map resolution");
  for (double value : observation.map_origin) finite(value, "map_origin");
  finite(observation.z_min, "z_min");
  finite(observation.z_max, "z_max");
  finite(observation.drone_radius, "drone_radius");
  if (observation.sfc_size.size() != 3) fail("sfc_size must have 3 values");
  for (double value : observation.sfc_size) finite(value, "sfc_size");
  finite(observation.shrinked_box_size, "shrinked_box_size");
  finite(observation.obst_max_vel, "obst_max_vel");
  finite(observation.obst_position_error, "obst_position_error");
  for (double value : observation.map_bounds) finite(value, "map_bounds");
  if (observation.global_path.empty()) fail("global_path is empty");
  if (observation.obst_pos.size() != observation.obst_bbox.size())
    fail("obst_pos and obst_bbox size mismatch");
  const auto& classified = observation.visible_map;
  if (classified.points.size() != classified.classes.size())
    fail("visible_map points/classes size mismatch");
  if (!classified.voxel_indices.empty() && classified.voxel_indices.size() != classified.points.size())
    fail("visible_map voxel_indices size mismatch");
  for (std::size_t i = 0; i < classified.points.size(); ++i) {
    for (double value : classified.points[i]) finite(value, "visible_map point");
    const auto label = classified.classes[i];
    if (label != kMapClassOccupied && label != kMapClassUnknown) fail("invalid visible_map class");
  }
  requireText(observation.environment_assumption, "environment_assumption");
}

std::string mapContentSha256(const FrozenPlanningObservation& observation) {
  validateFrozenObservation(observation);
  std::vector<unsigned char> payload;
  payload.reserve(64 + observation.visible_map.points.size() * 40);
  appendBytes(payload, "SANDOMAP1", 9);
  appendF64(payload, observation.res);
  appendF64(payload, observation.factor_hgp);
  for (double value : observation.map_origin) appendF64(payload, value);
  for (int value : observation.map_dim) appendI32(payload, value);
  appendU32(payload, static_cast<std::uint32_t>(observation.visible_map.points.size()));
  const bool have_idx = !observation.visible_map.voxel_indices.empty();
  appendU32(payload, have_idx ? 1u : 0u);
  for (std::size_t i = 0; i < observation.visible_map.points.size(); ++i) {
    for (double value : observation.visible_map.points[i]) appendF64(payload, value);
    payload.push_back(observation.visible_map.classes[i]);
    if (have_idx) {
      for (int value : observation.visible_map.voxel_indices[i]) appendI32(payload, value);
    }
  }
  return sha256(payload);
}

std::string observationContentSha256(const FrozenPlanningObservation& observation) {
  validateFrozenObservation(observation);
  std::vector<unsigned char> payload;
  appendBytes(payload, "SANDOOBS1", 9);
  appendString(payload, mapContentSha256(observation));
  appendString(payload, observation.environment_assumption);
  appendString(payload, observation.sim_env);
  appendString(payload, observation.norm);
  appendString(payload, observation.planner);
  appendI32(payload, observation.n);
  appendF64(payload, observation.initial_dt);
  appendF64(payload, observation.dc);
  appendF64(payload, observation.A_time);
  for (double value : observation.start) appendF64(payload, value);
  for (double value : observation.goal) appendF64(payload, value);
  appendF64(payload, observation.v_max);
  appendF64(payload, observation.a_max);
  appendF64(payload, observation.j_max);
  appendF64(payload, observation.jerk_smooth_weight);
  appendF64(payload, observation.z_min);
  appendF64(payload, observation.z_max);
  appendF64(payload, observation.drone_radius);
  appendU32(payload, static_cast<std::uint32_t>(observation.sfc_size.size()));
  for (double value : observation.sfc_size) appendF64(payload, value);
  payload.push_back(observation.use_shrinked_box ? 1 : 0);
  appendF64(payload, observation.shrinked_box_size);
  appendF64(payload, observation.obst_max_vel);
  appendF64(payload, observation.obst_position_error);
  payload.push_back(observation.inflate_unknown_boundary ? 1 : 0);
  for (double value : observation.map_bounds) appendF64(payload, value);
  appendU32(payload, static_cast<std::uint32_t>(observation.global_path.size()));
  for (const auto& point : observation.global_path)
    for (double value : point) appendF64(payload, value);
  appendU32(payload, static_cast<std::uint32_t>(observation.obst_pos.size()));
  for (const auto& point : observation.obst_pos)
    for (double value : point) appendF64(payload, value);
  for (const auto& point : observation.obst_bbox)
    for (double value : point) appendF64(payload, value);
  return sha256(payload);
}

nlohmann::json frozenObservationToJson(const FrozenPlanningObservation& observation) {
  validateFrozenObservation(observation);
  json classes = json::array();
  for (auto label : observation.visible_map.classes) classes.push_back(static_cast<int>(label));
  json voxels = json::array();
  for (const auto& idx : observation.visible_map.voxel_indices)
    voxels.push_back({idx[0], idx[1], idx[2]});
  json visible = {{"kind", "classified_points"},
                  {"points", pointArray(observation.visible_map.points)},
                  {"classes", classes},
                  {"voxel_indices", voxels},
                  {"sha256", mapContentSha256(observation)}};
  return {{"kind", observation.kind},
          {"schema_version", observation.schema_version},
          {"observation_id", observation.observation_id},
          {"observation_sha256", observationContentSha256(observation)},
          {"map_sha256", mapContentSha256(observation)},
          {"identity",
           {{"source_id", observation.source_id},
            {"config_id", observation.config_id},
            {"scene_id", observation.scene_id},
            {"episode_id", observation.episode_id},
            {"request_id", observation.request_id}}},
          {"start", stateArray(observation.start)},
          {"goal", stateArray(observation.goal)},
          {"A_time", observation.A_time},
          {"timestamps",
           {{"planning_start_time", observation.planning_start_time},
            {"observation_time", observation.observation_time},
            {"t0", observation.A_time}}},
          {"time_inputs",
           {{"n", observation.n},
            {"initial_dt", observation.initial_dt},
            {"dc", observation.dc}}},
          {"safety",
           {{"v_max", observation.v_max},
            {"a_max", observation.a_max},
            {"j_max", observation.j_max},
            {"jerk_smooth_weight", observation.jerk_smooth_weight},
            {"environment_assumption", observation.environment_assumption},
            {"sim_env", observation.sim_env},
            {"norm", observation.norm},
            {"planner", observation.planner}}},
          {"geometry",
           {{"res", observation.res},
            {"factor_hgp", observation.factor_hgp},
            {"map_origin",
             {observation.map_origin[0], observation.map_origin[1], observation.map_origin[2]}},
            {"map_dim", {observation.map_dim[0], observation.map_dim[1], observation.map_dim[2]}},
            {"z_min", observation.z_min},
            {"z_max", observation.z_max},
            {"drone_radius", observation.drone_radius},
            {"sfc_size", observation.sfc_size},
            {"use_shrinked_box", observation.use_shrinked_box},
            {"shrinked_box_size", observation.shrinked_box_size},
            {"obst_max_vel", observation.obst_max_vel},
            {"obst_position_error", observation.obst_position_error},
            {"inflate_unknown_boundary", observation.inflate_unknown_boundary},
            {"map_bounds", observation.map_bounds}}},
          {"global_path", pointArray(observation.global_path)},
          {"obst_pos", pointArray(observation.obst_pos)},
          {"obst_bbox", pointArray(observation.obst_bbox)},
          {"visible_map", visible}};
}

FrozenPlanningObservation frozenObservationFromJson(const nlohmann::json& value) {
  if (!value.is_object()) fail("frozen observation must be an object");
  FrozenPlanningObservation observation;
  observation.kind = value.value("kind", std::string{});
  observation.schema_version = value.value("schema_version", 0);
  observation.observation_id = value.value("observation_id", std::string{});
  const json identity = value.value("identity", json::object());
  observation.source_id = identity.value("source_id", std::string{});
  observation.config_id = identity.value("config_id", std::string{});
  observation.scene_id = identity.value("scene_id", std::string{});
  observation.episode_id = identity.value("episode_id", std::string{});
  observation.request_id = identity.value("request_id", std::string{});
  observation.start = parseState(value.at("start"), "start");
  observation.goal = parseState(value.at("goal"), "goal");
  observation.A_time = value.at("A_time").get<double>();
  const json timestamps = value.value("timestamps", json::object());
  observation.planning_start_time = timestamps.value("planning_start_time", 0.0);
  observation.observation_time = timestamps.value("observation_time", 0.0);
  const json time_inputs = value.value("time_inputs", json::object());
  observation.n = time_inputs.value("n", 0);
  observation.initial_dt = time_inputs.value("initial_dt", 0.0);
  observation.dc = time_inputs.value("dc", 0.0);
  const json safety = value.value("safety", json::object());
  observation.v_max = safety.value("v_max", 0.0);
  observation.a_max = safety.value("a_max", 0.0);
  observation.j_max = safety.value("j_max", 0.0);
  observation.jerk_smooth_weight = safety.value("jerk_smooth_weight", 0.0);
  observation.environment_assumption = safety.value("environment_assumption", std::string{});
  observation.sim_env = safety.value("sim_env", std::string{});
  observation.norm = safety.value("norm", std::string{"Linf"});
  observation.planner = safety.value("planner", std::string{"SANDO"});
  const json geometry = value.value("geometry", json::object());
  observation.res = geometry.value("res", 0.0);
  observation.factor_hgp = geometry.value("factor_hgp", 0.0);
  const json origin = geometry.value("map_origin", json::array());
  if (!origin.is_array() || origin.size() != 3) fail("map_origin must have 3 numbers");
  for (int i = 0; i < 3; ++i) observation.map_origin[static_cast<std::size_t>(i)] = origin[i].get<double>();
  const json dim = geometry.value("map_dim", json::array({0, 0, 0}));
  if (!dim.is_array() || dim.size() != 3) fail("map_dim must have 3 integers");
  for (int i = 0; i < 3; ++i) observation.map_dim[static_cast<std::size_t>(i)] = dim[i].get<int>();
  observation.z_min = geometry.value("z_min", 0.0);
  observation.z_max = geometry.value("z_max", 0.0);
  observation.drone_radius = geometry.value("drone_radius", 0.0);
  observation.sfc_size = geometry.value("sfc_size", std::vector<double>{});
  observation.use_shrinked_box = geometry.value("use_shrinked_box", false);
  observation.shrinked_box_size = geometry.value("shrinked_box_size", 0.0);
  observation.obst_max_vel = geometry.value("obst_max_vel", 0.0);
  observation.obst_position_error = geometry.value("obst_position_error", 0.0);
  observation.inflate_unknown_boundary = geometry.value("inflate_unknown_boundary", true);
  const json bounds = geometry.value("map_bounds", json::array());
  if (!bounds.is_array() || bounds.size() != 6) fail("map_bounds must have 6 numbers");
  for (int i = 0; i < 6; ++i) observation.map_bounds[static_cast<std::size_t>(i)] = bounds[i].get<double>();
  observation.global_path = parsePoints(value.at("global_path"), "global_path");
  observation.obst_pos = parsePoints(value.at("obst_pos"), "obst_pos");
  observation.obst_bbox = parsePoints(value.at("obst_bbox"), "obst_bbox");
  const json visible = value.at("visible_map");
  observation.visible_map.points = parsePoints(visible.at("points"), "visible_map.points");
  if (!visible.at("classes").is_array()) fail("visible_map.classes must be an array");
  for (const auto& item : visible.at("classes")) {
    if (!item.is_number_integer()) fail("visible_map.classes must be integers");
    observation.visible_map.classes.push_back(static_cast<std::uint8_t>(item.get<int>()));
  }
  if (visible.contains("voxel_indices") && visible.at("voxel_indices").is_array()) {
    for (const auto& item : visible.at("voxel_indices")) {
      if (!item.is_array() || item.size() != 3) fail("visible_map.voxel_indices entries must have 3 ints");
      observation.visible_map.voxel_indices.push_back(
          {item[0].get<int>(), item[1].get<int>(), item[2].get<int>()});
    }
  }
  validateFrozenObservation(observation);
  if (value.contains("map_sha256") && value.at("map_sha256").is_string() &&
      value.at("map_sha256").get<std::string>() != mapContentSha256(observation))
    fail("visible_map sha256 mismatch");
  if (value.contains("observation_sha256") && value.at("observation_sha256").is_string() &&
      value.at("observation_sha256").get<std::string>() != observationContentSha256(observation))
    fail("observation sha256 mismatch");
  return observation;
}

nlohmann::json frozenObservationReference(const FrozenPlanningObservation& observation) {
  validateFrozenObservation(observation);
  const auto map_sha = mapContentSha256(observation);
  const auto obs_sha = observationContentSha256(observation);
  return {{"observation_id", observation.observation_id},
          {"observation_sha256", obs_sha},
          {"map_sha256", map_sha},
          {"point_count", observation.visible_map.points.size()},
          {"v_max", observation.v_max},
          {"a_max", observation.a_max},
          {"j_max", observation.j_max},
          {"jerk_smooth_weight", observation.jerk_smooth_weight},
          {"environment_assumption", observation.environment_assumption},
          {"sim_env", observation.sim_env},
          {"global_path", pointArray(observation.global_path)},
          {"obst_pos", pointArray(observation.obst_pos)},
          {"obst_bbox", pointArray(observation.obst_bbox)},
          {"A_time", observation.A_time},
          {"visible_map",
           {{"kind", "request_observation"},
            {"observation_id", observation.observation_id},
            {"sha256", map_sha},
            {"observation_sha256", obs_sha},
            {"point_count", observation.visible_map.points.size()},
            {"path", "request_observation/" + observation.observation_id + ".json"}}}};
}

}  // namespace sando_learning
