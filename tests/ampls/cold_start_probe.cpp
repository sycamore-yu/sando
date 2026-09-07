#include "sando/ampl_model.hpp"

#include <atomic>
#include <chrono>
#include <cmath>
#include <condition_variable>
#include <cstdlib>
#include <future>
#include <iostream>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

using namespace sando_ampl;

namespace {

int worker_count() {
  const char* configured = std::getenv("SANDO_AMPL_COLD_WORKERS");
  if (!configured) return 9;
  const int count = std::atoi(configured);
  return count > 0 ? count : 9;
}

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

struct FirstSolveGate {
  std::atomic<int> arrivals{0};
  std::atomic<bool> timed_out{false};
  std::condition_variable condition;
  std::mutex mutex;
};

class FirstSolveCallback final : public GRBCallback {
 public:
  explicit FirstSolveCallback(FirstSolveGate& gate) : gate_(gate) {}

  void callback() override {
    // GRBModel::optimize and AmplsRuntime::solve each call the adapter
    // callback once before GRBoptimize. Only the third invocation originates
    // in the native solver; gating either earlier call would prove nothing
    // about concurrent optimization. Keep this count aligned with those two
    // explicit cancellation checks.
    if (++calls_ != 3) return;
    std::unique_lock<std::mutex> lock(gate_.mutex);
    gate_.arrivals.fetch_add(1, std::memory_order_release);
    gate_.condition.notify_all();
    const bool overlap = gate_.condition.wait_for(
        lock, std::chrono::seconds(15),
        [&] { return gate_.arrivals.load(std::memory_order_acquire) >= 2; });
    if (!overlap) {
      gate_.timed_out.store(true, std::memory_order_release);
      abort();
    }
  }

 private:
  FirstSolveGate& gate_;
  int calls_{0};
};

void solve_worker(int worker, std::promise<void> ready, std::shared_future<void> start,
                  FirstSolveGate& gate, std::string& failure) {
  try {
    // Every worker owns a fresh runtime and reaches its first solve before any
    // worker is released. There is deliberately no warm-up model.
    GRBModel model;
    auto x = model.addVar(0.0, 4.0, 0.0, GRB_CONTINUOUS, "x");
    auto z = model.addVar(0.0, 1.0, 0.0, GRB_BINARY, "switch");
    model.addGenConstrIndicator(z, 1, GRBLinExpr(x) <= 1.0, "cap_when_on");
    model.setObjective((GRBLinExpr(x) - 3.0) * (GRBLinExpr(x) - 3.0) - 5.0 * GRBLinExpr(z));

    ready.set_value();
    start.wait();

    FirstSolveCallback first_solve_callback(gate);
    model.setCallback(&first_solve_callback);
    model.optimize();
    model.setCallback(nullptr);
    require(!gate.timed_out.load(std::memory_order_acquire),
            "parallel native solve callback gate timed out");
    require(gate.arrivals.load(std::memory_order_acquire) >= 2,
            "parallel native solve callback gate saw fewer than two arrivals");
    require(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL,
            "worker " + std::to_string(worker) + " first solve was not optimal");
    require(std::abs(x.getValue() - 1.0) < 1e-6 && std::abs(z.getValue() - 1.0) < 1e-6,
            "worker " + std::to_string(worker) + " first solution mismatch");
    require(std::abs(model.get(GRB_DoubleAttr_ObjVal) + 1.0) < 1e-6,
            "worker " + std::to_string(worker) + " first objective mismatch");

    // Exercise two independent persistent updates after the cold concurrent
    // load, while keeping each worker's model and runtime isolated.
    model.addConstr(GRBLinExpr(z) == 0.0, "turn_off");
    model.setObjective((GRBLinExpr(x) - 2.0) * (GRBLinExpr(x) - 2.0));
    model.optimize();
    require(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL &&
                std::abs(x.getValue() - 2.0) < 1e-6 && std::abs(z.getValue()) < 1e-6,
            "worker " + std::to_string(worker) + " first update mismatch");

    model.addQConstr(GRBLinExpr(x) * GRBLinExpr(x) <= 2.25, "quadratic_cap");
    model.setObjective((GRBLinExpr(x) - 3.0) * (GRBLinExpr(x) - 3.0));
    model.optimize();
    require(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL &&
                std::abs(x.getValue() - 1.5) < 1e-5 &&
                std::abs(model.get(GRB_DoubleAttr_ObjVal) - 2.25) < 1e-5,
            "worker " + std::to_string(worker) + " second update mismatch");
  } catch (const std::exception& error) {
    failure = error.what();
    try {
      ready.set_value();
    } catch (const std::future_error&) {
      // The worker may already have announced readiness before failing.
    }
  }
}

}  // namespace

int main() {
  try {
    // Persistent mode is required for the two post-load updates. Respect an
    // explicit caller setting while making the default deterministic.
    if (!std::getenv("SANDO_AMPL_MODE")) setenv("SANDO_AMPL_MODE", "persistent", 1);

    const int count = worker_count();
    if (count < 2) throw std::runtime_error("cold probe requires at least two workers");
    std::promise<void> start_promise;
    const std::shared_future<void> start = start_promise.get_future().share();
    std::vector<std::promise<void>> readiness;
    std::vector<std::shared_future<void>> ready;
    FirstSolveGate gate;
    std::vector<std::string> failures(static_cast<std::size_t>(count));
    std::vector<std::thread> workers;
    readiness.reserve(static_cast<std::size_t>(count));
    ready.reserve(static_cast<std::size_t>(count));
    workers.reserve(static_cast<std::size_t>(count));
    for (int i = 0; i < count; ++i) {
      readiness.emplace_back();
      ready.push_back(readiness.back().get_future().share());
    }
    for (int i = 0; i < count; ++i)
      workers.emplace_back(solve_worker, i, std::move(readiness[static_cast<std::size_t>(i)]),
                           start, std::ref(gate), std::ref(failures[static_cast<std::size_t>(i)]));
    for (const auto& announced : ready) announced.wait();
    start_promise.set_value();
    for (auto& worker : workers) worker.join();

    for (const auto& failure : failures)
      if (!failure.empty()) throw std::runtime_error(failure);
    std::cout << "Cold concurrent AMPLS adapter probe passed with " << count
              << " independent models and two updates each\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Cold concurrent AMPLS adapter probe failed: " << error.what() << '\n';
    return 1;
  }
}
