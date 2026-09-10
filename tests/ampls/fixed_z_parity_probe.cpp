// Fixed-Z forward parity probe (lightweight fixture: corridors + bounds + states).
// Usage: fixed_z_parity_probe <fixture.json> [z0,z1,...] [f0,f1,...]
#include <sando/gurobi_solver.hpp>
#include <sando/segment_time.hpp>

#include <nlohmann/json.hpp>

#include <Eigen/Core>

#include <array>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

using json = nlohmann::json;
using sando_learning::Assignment;

void require(bool ok, const std::string& message) {
  if (!ok) throw std::runtime_error(message);
}

template <typename T>
std::vector<T> parse_csv(const std::string& text) {
  std::vector<T> out;
  std::stringstream ss(text);
  std::string item;
  while (std::getline(ss, item, ',')) {
    if (item.empty()) continue;
    std::stringstream one(item);
    T value{};
    one >> value;
    out.push_back(value);
  }
  return out;
}

struct LightFixture {
  int n{5};
  std::string norm{"Linf"};
  double factor{1.0};
  double initial_dt{0.0};
  double dc{0.01};
  double t0{0.0};
  std::array<double, 9> start{};
  std::array<double, 9> goal{};
  std::array<double, 6> map_bounds{};
  std::vector<std::vector<std::vector<std::array<double, 4>>>> corridors;  // [t][p][plane]
};

LightFixture load_light(const std::string& path) {
  std::ifstream stream(path);
  require(static_cast<bool>(stream), "cannot open fixture: " + path);
  json value;
  stream >> value;
  LightFixture out;
  out.n = value.at("n").get<int>();
  out.norm = value.value("norm", "Linf");
  out.factor = value.at("factor").get<double>();
  out.initial_dt = value.at("initial_dt").get<double>();
  out.dc = value.at("dc").get<double>();
  out.t0 = value.value("t0", 0.0);
  require(value.at("start").size() == 9, "start size");
  require(value.at("goal").size() == 9, "goal size");
  require(value.at("map_bounds").size() == 6, "map_bounds size");
  for (int i = 0; i < 9; ++i) {
    out.start[i] = value.at("start")[i].get<double>();
    out.goal[i] = value.at("goal")[i].get<double>();
  }
  for (int i = 0; i < 6; ++i) out.map_bounds[i] = value.at("map_bounds")[i].get<double>();
  require(value.at("corridors").is_array(), "corridors");
  for (const auto& layer : value.at("corridors")) {
    std::vector<std::vector<std::array<double, 4>>> polys;
    for (const auto& corridor : layer) {
      std::vector<std::array<double, 4>> planes;
      for (const auto& plane : corridor.at("planes")) {
        require(plane.size() == 4, "plane size");
        planes.push_back({plane[0].get<double>(), plane[1].get<double>(), plane[2].get<double>(),
                          plane[3].get<double>()});
      }
      polys.push_back(std::move(planes));
    }
    out.corridors.push_back(std::move(polys));
  }
  require(static_cast<int>(out.corridors.size()) == out.n, "corridor layers != n");
  return out;
}

LinearConstraint3D poly_from_planes(const std::vector<std::array<double, 4>>& planes) {
  require(!planes.empty(), "empty corridor planes");
  Eigen::MatrixXd A(static_cast<int>(planes.size()), 3);
  Eigen::VectorXd b(static_cast<int>(planes.size()));
  for (int r = 0; r < static_cast<int>(planes.size()); ++r) {
    A(r, 0) = planes[r][0];
    A(r, 1) = planes[r][1];
    A(r, 2) = planes[r][2];
    b(r) = planes[r][3];
  }
  return LinearConstraint3D(A, b);
}

Parameters parameters_from_fixture(const LightFixture& instance) {
  Parameters p{};
  p.num_N = instance.n;
  p.num_P = static_cast<int>(instance.corridors.empty() ? 0 : instance.corridors.front().size());
  p.dc = instance.dc;
  p.dynamic_constraint_type = instance.norm;
  p.using_variable_elimination = true;
  p.x_min = instance.map_bounds[0];
  p.x_max = instance.map_bounds[1];
  p.y_min = instance.map_bounds[2];
  p.y_max = instance.map_bounds[3];
  p.z_min = instance.map_bounds[4];
  p.z_max = instance.map_bounds[5];
  p.v_max = 5.0;
  p.a_max = 20.0;
  p.j_max = 100.0;
  p.jerk_smooth_weight = 10.0;
  p.factor_initial = 1.0;
  p.factor_final = 1.0;
  p.factor_constant_step_size = 1.0;
  p.max_gurobi_comp_time_sec = 30.0;
  p.debug_verbose = false;
  p.horizon = 15.0;
  p.use_dynamic_factor = false;
  return p;
}

RobotState state_from_array(const std::array<double, 9>& values) {
  RobotState state;
  state.setPos(values[0], values[1], values[2]);
  state.setVel(values[3], values[4], values[5]);
  state.setAccel(values[6], values[7], values[8]);
  return state;
}

}  // namespace

int main(int argc, char** argv) {
  try {
    require(argc >= 2, "usage: fixed_z_parity_probe <fixture.json> [z csv] [f csv]");
    const auto captured = load_light(argv[1]);
    require(captured.n == 5, "fixture must be N=5");
    Assignment z(static_cast<size_t>(captured.n), 0);
    if (argc >= 3) {
      const auto parsed = parse_csv<int>(argv[2]);
      require(parsed.size() == static_cast<size_t>(captured.n), "assignment length must equal n");
      z.assign(parsed.begin(), parsed.end());
    }
    std::vector<double> factors = {captured.factor, 1.0, 1.5, 2.0};
    if (argc >= 4) factors = parse_csv<double>(argv[3]);

    SolverGurobi solver;
    solver.setPlannerName("SANDO");
    solver.initializeSolver(parameters_from_fixture(captured));
    solver.setX0(state_from_array(captured.start));
    solver.setXf(state_from_array(captured.goal));
    solver.setT0(captured.t0);
    solver.setInitialDt(captured.initial_dt);

    std::vector<std::vector<LinearConstraint3D>> layers(static_cast<size_t>(captured.n));
    for (int t = 0; t < captured.n; ++t) {
      layers[t].reserve(captured.corridors[t].size());
      for (const auto& corridor : captured.corridors[t])
        layers[t].push_back(poly_from_planes(corridor));
    }
    solver.setPolytopesTimeLayered(layers);

    json report{{"fixture", argv[1]},
                {"native_factor", captured.factor},
                {"assignment", z},
                {"rows", json::array()}};

    for (double factor : factors) {
      bool error = false;
      double backend_ms = 0.0;
      const bool ok = solver.generateNewTrajectory(error, backend_ms, factor, false, &z);
      json row{{"factor", factor}, {"ok", ok && !error}, {"backend_ms", backend_ms}};
      if (!(ok && !error)) {
        row["error"] = error ? "solver_error_flag" : "generate_returned_false";
        report["rows"].push_back(row);
        continue;
      }
      row["objective"] = solver.getObjectiveValue();
      row["segment_dt"] =
          sando_time::segmentDuration(captured.initial_dt, captured.dc, factor);
      const auto live = solver.getPlanningInstance(factor);
      row["residuals"] = live.outcome.value("residuals", json(nullptr));
      PieceWisePol pwp;
      solver.getPieceWisePol(pwp);
      json coeffs = json::array();
      for (int s = 0; s < captured.n; ++s) {
        coeffs.push_back({{"x", {pwp.coeff_x[s](0), pwp.coeff_x[s](1), pwp.coeff_x[s](2), pwp.coeff_x[s](3)}},
                          {"y", {pwp.coeff_y[s](0), pwp.coeff_y[s](1), pwp.coeff_y[s](2), pwp.coeff_y[s](3)}},
                          {"z", {pwp.coeff_z[s](0), pwp.coeff_z[s](1), pwp.coeff_z[s](2), pwp.coeff_z[s](3)}}});
      }
      row["coeffs"] = coeffs;
      report["rows"].push_back(row);
    }
    report["status"] = "ok";
    std::cout << report.dump() << '\n';
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "fixed_z_parity_probe: " << error.what() << '\n';
    return 1;
  }
}
