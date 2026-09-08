#include <sando/corridor_policy.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <stdexcept>

namespace sando_learning {
namespace {
using json = nlohmann::json;
void fail(const std::string& s) { throw std::invalid_argument(s); }
double number(const json& x, const char* what) {
  if (!x.is_number() || !std::isfinite(x.get<double>())) fail(std::string("non-finite ") + what);
  return x.get<double>();
}
std::vector<double> numbers(const json& x, const char* what) {
  if (!x.is_array()) fail(std::string(what) + " must be an array");
  std::vector<double> out; out.reserve(x.size());
  for (const auto& v : x) out.push_back(number(v, what));
  return out;
}
CorridorPolicy::Dense layer(const json& layers, const char* name, int in, int out, bool relu) {
  const auto& value = layers.at(name);
  if (!value.is_object()) fail(std::string("layer ") + name + " must be an object");
  CorridorPolicy::Dense result;
  result.relu = relu;
  const auto& weights = value.at("weight");
  if (!weights.is_array() || static_cast<int>(weights.size()) != out)
    fail(std::string("layer ") + name + " has wrong output dimension");
  result.weight.resize(out, in);
  int row_index = 0;
  for (const auto& row : weights) {
    auto parsed = numbers(row, "weight");
    if (static_cast<int>(parsed.size()) != in) fail(std::string("layer ") + name + " has wrong input dimension");
    for (int column = 0; column < in; ++column) result.weight(row_index, column) = parsed[column];
    ++row_index;
  }
  const auto parsed_bias = numbers(value.at("bias"), "bias");
  if (static_cast<int>(parsed_bias.size()) != out) fail(std::string("layer ") + name + " has wrong bias dimension");
  result.bias.resize(out);
  for (int i = 0; i < out; ++i) result.bias(i) = parsed_bias[i];
  return result;
}
bool lexLess(const Assignment& a, const Assignment& b) { return std::lexicographical_compare(a.begin(), a.end(), b.begin(), b.end()); }
}

std::vector<double> CorridorPolicy::Dense::apply(const std::vector<double>& input) const {
  if (weight.cols() != static_cast<int>(input.size())) fail("network input dimension mismatch");
  Eigen::VectorXd vector(static_cast<int>(input.size()));
  for (int i = 0; i < vector.size(); ++i) vector(i) = input[static_cast<std::size_t>(i)];
  Eigen::VectorXd output = weight * vector + bias;
  if (!output.allFinite()) fail("non-finite network score");
  if (relu) output = output.cwiseMax(0.0);
  return std::vector<double>(output.data(), output.data() + output.size());
}

CorridorPolicy::CorridorPolicy(const std::filesystem::path& path)
    : CorridorPolicy(load(path).model_) {}

CorridorPolicy CorridorPolicy::load(const std::filesystem::path& path) {
  std::ifstream stream(path);
  if (!stream) throw std::invalid_argument("cannot open corridor policy model");
  json model; stream >> model;
  return CorridorPolicy(model);
}

CorridorPolicy::CorridorPolicy(const json& model) : model_(model) { validateModel();
  const auto& layers = model_.at("layers");
  plane1_ = layer(layers, "plane1", 4, 32, true);
  plane2_ = layer(layers, "plane2", 32, 32, true);
  score1_ = layer(layers, "score1", 355, 128, true);
  score2_ = layer(layers, "score2", 128, 64, true);
  score3_ = layer(layers, "score3", 64, 1, false);
}

void CorridorPolicy::validateModel() const {
  if (!model_.is_object() || model_.at("schema_version") != 1 ||
      model_.at("kind") != "sando_corridor_policy" || model_.at("n") != 5 || model_.at("norm") != "Linf")
    fail("invalid corridor policy model identity");
  const auto& spec = model_.at("feature_spec");
  if (!spec.is_object()) fail("invalid feature specification");
  const json expected = {{"version", 1}, {"origin", "start_position"},
                         {"spatial_scale", "max(1,max_map_extent)"},
                         {"velocity", "segment_dt/scale"},
                         {"acceleration", "segment_dt_squared/scale"},
                         {"plane_count", "raw"},
                         {"context_order", "start9_goal9_map6_dt5_factor"}};
  if (spec != expected) fail("invalid feature specification");
  if (!model_.at("layers").is_object()) fail("layers must be an object");
  for (const auto& item : model_.at("layers").items())
    if (item.key() != "plane1" && item.key() != "plane2" && item.key() != "score1" &&
        item.key() != "score2" && item.key() != "score3") fail("unexpected policy layer");
  if (!model_.contains("metadata") || !model_.at("metadata").is_object()) fail("metadata must be an object");
}

std::vector<double> CorridorPolicy::context(const PlanningInstance& x, double scale) const {
  const double dt = x.segment_dt;
  std::vector<double> f; f.reserve(30);
  auto state = [&](const std::array<double, 9>& s) {
    for (int i = 0; i < 3; ++i) f.push_back((s[i] - x.start[i]) / scale);
    for (int i = 3; i < 6; ++i) f.push_back(s[i] * dt / scale);
    for (int i = 6; i < 9; ++i) f.push_back(s[i] * dt * dt / scale);
  };
  state(x.start); state(x.goal);
  for (int i = 0; i < 6; ++i) f.push_back((x.map_bounds[i] - x.start[i / 2]) / scale);
  for (int i = 0; i < 5; ++i) f.push_back(dt);
  f.push_back(x.factor);
  for (const double value : f) if (!std::isfinite(value)) fail("non-finite policy input feature");
  return f;
}

std::vector<std::vector<std::vector<std::array<double, 4>>>> CorridorPolicy::normalizedPlanes(
    const PlanningInstance& x, double scale) const {
  std::vector<std::vector<std::vector<std::array<double, 4>>>> result(5);
  for (int t = 0; t < 5; ++t) for (const auto& corridor : x.corridors[t]) {
    result[t].emplace_back();
    auto& normalized = result[t].back();
    for (const auto& plane : corridor.planes) {
      const double norm = std::hypot(std::hypot(plane[0], plane[1]), plane[2]);
      if (!(norm > 0.0) || !std::isfinite(norm)) fail("invalid corridor plane normal");
      const double nx = plane[0] / norm, ny = plane[1] / norm, nz = plane[2] / norm;
      const long double dot = static_cast<long double>(nx) * x.start[0] +
                              static_cast<long double>(ny) * x.start[1] +
                              static_cast<long double>(nz) * x.start[2];
      const long double offset = (static_cast<long double>(plane[3]) / norm - dot) / scale;
      const double normalized_offset = static_cast<double>(offset);
      if (!std::isfinite(offset) || !std::isfinite(normalized_offset)) fail("non-finite normalized corridor plane");
      std::array<double, 4> p{nx, ny, nz, normalized_offset};
      normalized.push_back(p);
    }
  }
  return result;
}

std::vector<double> CorridorPolicy::corridorEncoding(const std::vector<std::array<double, 4>>& planes) const {
  if (planes.empty()) fail("cannot encode empty corridor");
  std::vector<double> mean(32, 0), maximum(32, -std::numeric_limits<double>::infinity());
  for (const auto& plane : planes) {
    std::vector<double> h = plane1_.apply({plane.begin(), plane.end()});
    h = plane2_.apply(h);
    for (int i = 0; i < 32; ++i) { mean[i] += h[i]; maximum[i] = std::max(maximum[i], h[i]); }
  }
  for (double& value : mean) value /= planes.size();
  mean.insert(mean.end(), maximum.begin(), maximum.end());
  mean.push_back(static_cast<double>(planes.size()));
  return mean;
}

std::vector<std::pair<Assignment, double>> CorridorPolicy::scores(const PlanningInstance& x) const {
  validateInstance(x, false);
  if (x.n != 5 || x.norm != "Linf" || x.planner != "SANDO") fail("unsupported planning instance");
  const auto assignments = enumerateAssignments(x);
  double extent = 1.0;
  for (int axis = 0; axis < 3; ++axis) {
    const double difference = x.map_bounds[2*axis+1] - x.map_bounds[2*axis];
    if (!std::isfinite(difference)) fail("non-finite map extent");
    extent = std::max(extent, difference);
  }
  const auto planes = normalizedPlanes(x, extent);
  std::vector<std::vector<std::vector<double>>> encodings(5);
  for (int t = 0; t < 5; ++t) {
    encodings[t].resize(planes[t].size());
    for (std::size_t p = 0; p < planes[t].size(); ++p)
      if (!planes[t][p].empty()) encodings[t][p] = corridorEncoding(planes[t][p]);
  }
  const auto ctx = context(x, extent);
  std::vector<std::pair<Assignment, double>> result;
  for (const auto& a : assignments) {
    std::vector<double> features;
    for (int t = 0; t < 5; ++t) features.insert(features.end(), encodings[t][a[t]].begin(), encodings[t][a[t]].end());
    features.insert(features.end(), ctx.begin(), ctx.end());
    const auto h1 = score1_.apply(features), h2 = score2_.apply(h1), out = score3_.apply(h2);
    result.emplace_back(a, out.front());
  }
  return result;
}

std::vector<Assignment> CorridorPolicy::rank(const PlanningInstance& x) const {
  auto result = scores(x);
  std::stable_sort(result.begin(), result.end(), [](const auto& a, const auto& b) {
    if (a.second != b.second) return a.second > b.second;
    return lexLess(a.first, b.first);
  });
  std::vector<Assignment> assignments; for (auto& item : result) assignments.push_back(std::move(item.first));
  return assignments;
}

json CorridorPolicy::debugJson(const PlanningInstance& x) const {
  validateInstance(x, false);
  if (x.n != 5 || x.norm != "Linf" || x.planner != "SANDO") fail("unsupported planning instance");
  const auto assignments = enumerateAssignments(x); json result;
  double extent = 1.0;
  for (int axis = 0; axis < 3; ++axis) {
    const double difference = x.map_bounds[2*axis+1] - x.map_bounds[2*axis];
    if (!std::isfinite(difference)) fail("non-finite map extent");
    extent = std::max(extent, difference);
  }
  const auto planes = normalizedPlanes(x, extent);
  const auto ctx = context(x, extent);
  json layers = json::array();
  for (int t = 0; t < 5; ++t) {
    json layer_json = json::array();
    for (const auto& layer : planes[t])
      layer_json.push_back(layer.empty() ? json::array() : json(corridorEncoding(layer)));
    layers.push_back(std::move(layer_json));
  }
  json score_list = json::array();
  const auto scored = scores(x);
  for (const auto& [assignment, value] : scored) score_list.push_back({{"assignment", assignment}, {"score", value}});
  result["context"] = ctx;
  result["normalized_planes"] = planes;
  result["layers"] = std::move(layers);
  result["assignments"] = assignments; result["scores"] = score_list; return result;
}

}  // namespace sando_learning
