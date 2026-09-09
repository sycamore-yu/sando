#include <sando/sando.hpp>

#include <atomic>
#include <cmath>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

namespace {

Parameters parameters() {
  Parameters p{};
  p.num_N = 5;
  p.num_P = 1;
  p.dc = 0.1;
  p.dynamic_constraint_type = "Linf";
  p.sfc_size = {3.0, 3.0, 3.0};
  p.res = 0.3;
  p.factor_hgp = 1.0;
  p.max_dist_vertexes = 1.0;
  p.v_max = 5.0;
  p.a_max = 20.0;
  p.j_max = 100.0;
  p.factor_initial = 1.0;
  p.factor_final = 1.0;
  p.factor_constant_step_size = 1.0;
  p.max_gurobi_comp_time_sec = 1.0;
  p.jerk_smooth_weight = 1.0;
  p.horizon = 5.0;
  p.w_max = 1.0;
  p.w_max_yawing = 1.0;
  p.skip_initial_yawing = false;
  return p;
}

RobotState state(double x, double y, double z, double yaw = 0.0) {
  RobotState result;
  result.setZero();
  result.pos = Eigen::Vector3d(x, y, z);
  result.yaw = yaw;
  return result;
}

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

void requirePosition(const RobotState& actual, const RobotState& expected,
                     const std::string& message) {
  require((actual.pos - expected.pos).norm() < 1e-9,
          message + ": got " + std::to_string(actual.pos.x()) + "," +
              std::to_string(actual.pos.y()) + "," + std::to_string(actual.pos.z()));
}

void terminalGoalBeforeState() {
  SANDO planner(parameters());
  const RobotState goal = state(9.0, 8.0, 7.0);
  const RobotState actual_start = state(3.0, 2.0, 1.0);

  planner.setTerminalGoal(goal);
  RobotState before_state;
  require(!planner.getNextGoal(before_state),
          "goal-first startup produced a command before the first state");
  planner.updateState(actual_start);

  RobotState commanded;
  require(planner.getNextGoal(commanded), "goal-first startup produced no command");
  requirePosition(commanded, actual_start,
                  "goal-first startup command did not hold actual start");

  RobotState preserved_goal;
  planner.getGterm(preserved_goal);
  requirePosition(preserved_goal, goal, "goal-first startup lost terminal goal");
}

void stateBeforeTerminalGoal() {
  SANDO planner(parameters());
  const RobotState actual_start = state(-3.0, 4.0, 2.0);
  const RobotState goal = state(6.0, -5.0, 3.0);

  planner.updateState(actual_start);
  planner.setTerminalGoal(goal);

  RobotState commanded;
  require(planner.getNextGoal(commanded), "state-first startup produced no command");
  requirePosition(commanded, actual_start, "state-first startup command moved from actual start");

  RobotState preserved_goal;
  planner.getGterm(preserved_goal);
  requirePosition(preserved_goal, goal, "state-first startup lost terminal goal");
}

void latestEarlyGoalWins() {
  SANDO planner(parameters());
  const RobotState actual_start = state(11.0, 12.0, 13.0);
  const RobotState first_goal = state(20.0, 21.0, 22.0);
  const RobotState latest_goal = state(30.0, 31.0, 32.0);

  planner.setTerminalGoal(first_goal);
  planner.setTerminalGoal(latest_goal);
  planner.updateState(actual_start);

  RobotState commanded;
  require(planner.getNextGoal(commanded), "multiple early goals produced no command");
  requirePosition(commanded, actual_start,
                  "multiple early goals did not hold actual start");
  RobotState preserved_goal;
  planner.getGterm(preserved_goal);
  requirePosition(preserved_goal, latest_goal, "latest early goal was not preserved");
}

void concurrentGoalThenState() {
  for (int iteration = 0; iteration < 8; ++iteration) {
    SANDO planner(parameters());
    const RobotState actual_start = state(-11.0 - iteration, -12.0, -13.0);
    const RobotState goal = state(-20.0, -21.0 - iteration, -22.0);
    std::atomic<int> ready{0};
    std::atomic<bool> start{false};

    std::thread goal_thread([&] {
      ready.fetch_add(1, std::memory_order_release);
      while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
      planner.setTerminalGoal(goal);
    });
    std::thread state_thread([&] {
      ready.fetch_add(1, std::memory_order_release);
      while (!start.load(std::memory_order_acquire)) std::this_thread::yield();
      planner.updateState(actual_start);
    });
    while (ready.load(std::memory_order_acquire) != 2) std::this_thread::yield();
    start.store(true, std::memory_order_release);
    goal_thread.join();
    state_thread.join();

    RobotState commanded;
    require(planner.getNextGoal(commanded), "concurrent startup produced no command");
    requirePosition(commanded, actual_start,
                    "concurrent goal/state startup moved from actual start");
    RobotState preserved_goal;
    planner.getGterm(preserved_goal);
    requirePosition(preserved_goal, goal, "concurrent startup lost terminal goal");
  }
}

}  // namespace

int main() {
  try {
    terminalGoalBeforeState();
    stateBeforeTerminalGoal();
    latestEarlyGoalWins();
    concurrentGoalThenState();
    std::cout << "planner_startup_probe PASS\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "planner_startup_probe FAIL: " << error.what() << '\n';
    return 1;
  }
}
