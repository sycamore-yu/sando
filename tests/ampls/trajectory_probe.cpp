#include <sando/gurobi_solver.hpp>

#include <Eigen/Core>

#include <chrono>
#include <cmath>
#include <iostream>
#include <iomanip>
#include <limits>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
constexpr double kTol = 2e-5;

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

Parameters parameters(int n, const std::string& norm, bool eliminate) {
  Parameters p{};
  p.num_N = n;
  p.num_P = 1;
  p.dc = 1.0;
  p.dynamic_constraint_type = norm;
  p.using_variable_elimination = eliminate;
  p.x_min = -2.0;
  p.x_max = 5.0;
  p.y_min = -3.0;
  p.y_max = 4.0;
  p.z_min = -1.0;
  p.z_max = 4.0;
  p.v_max = 20.0;
  p.a_max = 40.0;
  p.j_max = 100.0;
  p.factor_initial = 1.0;
  p.factor_final = 1.0;
  p.factor_constant_step_size = 1.0;
  p.max_gurobi_comp_time_sec = 20.0;
  p.jerk_smooth_weight = 1.0;
  p.debug_verbose = false;
  p.horizon = static_cast<double>(n);
  p.use_dynamic_factor = false;
  return p;
}

LinearConstraint3D box(double x_shift) {
  Eigen::Matrix<double, 6, 3> a;
  a << 1, 0, 0, -1, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 1, 0, 0, -1;
  Eigen::Matrix<double, 6, 1> b;
  b << 5.0 + x_shift, 2.0 - x_shift, 4.0, 3.0, 4.0, 1.0;
  return LinearConstraint3D(a, b);
}

double polynomial(const Eigen::Matrix<double, 4, 1>& c, double u) {
  return ((c(0) * u + c(1)) * u + c(2)) * u + c(3);
}

double velocity(const Eigen::Matrix<double, 4, 1>& c, double u) {
  return (3.0 * c(0) * u + 2.0 * c(1)) * u + c(2);
}

double acceleration(const Eigen::Matrix<double, 4, 1>& c, double u) {
  return 6.0 * c(0) * u + 2.0 * c(1);
}

void check_solution(const PieceWisePol& pwp, const RobotState& start, const RobotState& goal,
                    double v_max, double a_max, double j_max,
                    const std::string& norm, const std::vector<LinearConstraint3D>& corridor,
                    double jerk_weight, double objective) {
  require(pwp.times.size() == pwp.coeff_x.size() + 1, "piecewise time/coeff size mismatch");
  require(pwp.coeff_x.size() == pwp.coeff_y.size() && pwp.coeff_x.size() == pwp.coeff_z.size(),
          "piecewise axis size mismatch");
  const int n = static_cast<int>(pwp.coeff_x.size());
  auto value = [&](int axis, int segment, double u) {
    const auto& c = axis == 0 ? pwp.coeff_x[segment] : axis == 1 ? pwp.coeff_y[segment] : pwp.coeff_z[segment];
    return polynomial(c, u);
  };
  auto deriv = [&](int axis, int segment, double u, int order) {
    const auto& c = axis == 0 ? pwp.coeff_x[segment] : axis == 1 ? pwp.coeff_y[segment] : pwp.coeff_z[segment];
    if (order == 1) return velocity(c, u);
    if (order == 2) return acceleration(c, u);
    return 6.0 * c(0);
  };
  auto norm_value = [&](const Eigen::Vector3d& value) {
    if (norm == "L1") return value.cwiseAbs().sum();
    if (norm == "L2") return value.norm();
    return value.cwiseAbs().maxCoeff();
  };
  double expected_objective = 0.0;
  for (int axis = 0; axis < 3; ++axis) {
    require(std::abs(value(axis, 0, 0.0) - start.pos(axis)) < kTol, "initial position mismatch");
    require(std::abs(deriv(axis, 0, 0.0, 1) - start.vel(axis)) < kTol, "initial velocity mismatch");
    require(std::abs(deriv(axis, 0, 0.0, 2) - start.accel(axis)) < kTol, "initial acceleration mismatch");
    require(std::abs(value(axis, n - 1, pwp.times.back() - pwp.times[n - 1]) - goal.pos(axis)) < kTol,
            "final position mismatch");
    require(std::abs(deriv(axis, n - 1, pwp.times.back() - pwp.times[n - 1], 1) - goal.vel(axis)) < kTol,
            "final velocity mismatch");
    require(std::abs(deriv(axis, n - 1, pwp.times.back() - pwp.times[n - 1], 2) - goal.accel(axis)) < kTol,
            "final acceleration mismatch");
  }
  for (int i = 0; i < n - 1; ++i) {
    const double left = pwp.times[i + 1] - pwp.times[i];
    for (int axis = 0; axis < 3; ++axis) {
      require(std::abs(value(axis, i, left) - value(axis, i + 1, 0.0)) < kTol, "position discontinuity");
      require(std::abs(deriv(axis, i, left, 1) - deriv(axis, i + 1, 0.0, 1)) < kTol, "velocity discontinuity");
      require(std::abs(deriv(axis, i, left, 2) - deriv(axis, i + 1, 0.0, 2)) < kTol, "acceleration discontinuity");
    }
  }
  for (int i = 0; i < n; ++i) {
    const double dt = pwp.times[i + 1] - pwp.times[i];
    for (int sample = 0; sample <= 20; ++sample) {
      const double u = dt * sample / 20.0;
      Eigen::Vector3d point, vel, accel;
      for (int axis = 0; axis < 3; ++axis) {
        point(axis) = value(axis, i, u);
        vel(axis) = deriv(axis, i, u, 1);
        accel(axis) = deriv(axis, i, u, 2);
      }
      const Eigen::Vector3d jerk(6.0 * pwp.coeff_x[i](0), 6.0 * pwp.coeff_y[i](0),
                                 6.0 * pwp.coeff_z[i](0));
      require(norm_value(vel) <= v_max + kTol, "sampled velocity bound violated");
      require(norm_value(accel) <= a_max + kTol, "sampled acceleration bound violated");
      require(norm_value(jerk) <= j_max + kTol, "sampled jerk bound violated");
      require(corridor[i].A_.rows() == 6 && (corridor[i].A_ * point - corridor[i].b_).maxCoeff() <= kTol,
              "Bezier sample outside corridor");
    }
    // Independently derive the cubic Bezier position control points from power coefficients.
    for (int axis = 0; axis < 3; ++axis) {
      const auto& c = axis == 0 ? pwp.coeff_x[i] : axis == 1 ? pwp.coeff_y[i] : pwp.coeff_z[i];
      const double cp[4] = {c(3), c(3) + c(2) * dt / 3.0,
                            c(3) + 2.0 * c(2) * dt / 3.0 + c(1) * dt * dt / 3.0,
                            polynomial(c, dt)};
      for (double v : cp) require(std::isfinite(v), "non-finite Bezier control point");
    }
    for (int cp_index = 0; cp_index < 4; ++cp_index) {
      Eigen::Vector3d cp;
      for (int axis = 0; axis < 3; ++axis) {
        const auto& c = axis == 0 ? pwp.coeff_x[i] : axis == 1 ? pwp.coeff_y[i] : pwp.coeff_z[i];
        const double bezier[4] = {c(3), c(3) + c(2) * dt / 3.0,
                                  c(3) + 2.0 * c(2) * dt / 3.0 + c(1) * dt * dt / 3.0,
                                  polynomial(c, dt)};
        cp(axis) = bezier[cp_index];
      }
      require((corridor[i].A_ * cp - corridor[i].b_).maxCoeff() <= kTol,
              "Bezier control point outside corridor");
    }
    const Eigen::Vector3d jerk(6.0 * pwp.coeff_x[i](0), 6.0 * pwp.coeff_y[i](0),
                               6.0 * pwp.coeff_z[i](0));
    expected_objective += jerk.squaredNorm() * jerk_weight;
  }
  if (std::abs(objective - expected_objective) > 1e-6 * std::max(1e-8, std::abs(expected_objective))) {
    std::cerr << std::setprecision(17) << "jerk objective diagnostic actual=" << objective
              << " expected=" << expected_objective << " delta="
              << (objective - expected_objective) << '\n';
  }
  require(std::abs(objective - expected_objective) <=
              kTol * std::max(1.0, std::abs(expected_objective)),
          "jerk objective mismatch actual=" + std::to_string(objective) +
              " expected=" + std::to_string(expected_objective));
}

bool run_case(int n, const std::string& norm, bool eliminate) {
  SolverGurobi solver;
  auto par = parameters(n, norm, eliminate);
  solver.setPlannerName("SANDO");
  solver.initializeSolver(par);
  RobotState start, goal;
  start.setPos(0.0, 0.0, 1.0);
  goal.setPos(3.0, 1.0, 2.0);
  solver.setX0(start);
  solver.setXf(goal);
  solver.setT0(0.0);
  solver.setInitialDt(1.0);
  std::vector<std::vector<LinearConstraint3D>> layers(n);
  std::vector<LinearConstraint3D> flat;
  for (int i = 0; i < n; ++i) {
    layers[i].push_back(box(0.1 * i));
    flat.push_back(layers[i].front());
  }
  solver.setPolytopesTimeLayered(layers);
  bool error = false;
  double milliseconds = 0.0;
  const auto begin = std::chrono::steady_clock::now();
  const bool solved = solver.generateNewTrajectory(error, milliseconds, 1.0);
  const auto elapsed = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - begin).count();
  require(solved && !error, "trajectory solve failed");
  PieceWisePol pwp;
  solver.getPieceWisePol(pwp);
  require(pwp.times.size() == static_cast<size_t>(n + 1), "unexpected trajectory segment count");
  for (int i = 0; i < n; ++i)
    require(std::abs((pwp.times[i + 1] - pwp.times[i]) - 2.0) < kTol,
            "unexpected dt for dc=1");
  check_solution(pwp, start, goal, par.v_max, par.a_max, par.j_max, norm, flat,
                par.jerk_smooth_weight, solver.getObjectiveValue());
  // Repeat the request to exercise deletion of binaries and their indicator constraints.
  error = false;
  require(solver.generateNewTrajectory(error, milliseconds, 1.0) && !error, "repeat solve failed");
  std::cout << "PASS N=" << n << " norm=" << norm << " VE=" << eliminate
            << " elapsed_ms=" << elapsed << "\n";
  return true;
}

}  // namespace

int main() {
  try {
    for (int n : {4, 5, 6}) {
      for (const std::string& norm : {"Linf", "L1", "L2"}) {
        for (bool eliminate : {true, false}) run_case(n, norm, eliminate);
      }
    }
    SolverGurobi empty_solver;
    auto p = parameters(4, "Linf", true);
    empty_solver.initializeSolver(p);
    std::vector<std::vector<LinearConstraint3D>> empty(4);
    for (auto& layer : empty) {
      Eigen::MatrixXd a(0, 3);
      Eigen::VectorXd b(0);
      layer.emplace_back(a, b);
    }
    empty_solver.setPolytopesTimeLayered(empty);
    RobotState start, goal;
    start.setPos(0, 0, 1);
    goal.setPos(3, 1, 2);
    empty_solver.setX0(start);
    empty_solver.setXf(goal);
    empty_solver.setInitialDt(1.0);
    bool error = false;
    double milliseconds = 0.0;
    require(!empty_solver.generateNewTrajectory(error, milliseconds, 1.0),
            "empty corridor unexpectedly solved");
    std::cout << "PASS empty corridor rejected\n";
  } catch (const std::exception& e) {
    std::cerr << "trajectory_probe FAIL: " << e.what() << '\n';
    return 1;
  }
  return 0;
}
