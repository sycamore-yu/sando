#include "sando/ampl_model.hpp"

#include <cmath>
#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <unistd.h>

using namespace sando_ampl;

static void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

static void unset(const char* name) { ::unsetenv(name); }

int main() {
  try {
    setenv("SANDO_AMPL_MODE", "persistent", 1);
    unset("SANDO_AMPL_VERIFY_UPDATES");
    unset("SANDO_AMPL_AUDIT_DIR");

    // First import (cold path always exports/compiles).
    GRBModel model;
    auto x = model.addVar(0.0, 5.0, 0.0, GRB_CONTINUOUS, "x");
    auto z = model.addVar(0.0, 1.0, 0.0, GRB_BINARY, "switch");
    auto unused = model.addVar(0, 1, 0, GRB_BINARY, "unused");
    auto fixed = model.addVar(0.5, 0.5, 0, GRB_CONTINUOUS, "fixed");
    auto first_indicator = model.addGenConstrIndicator(z, 1, GRBLinExpr(x) <= 1.0, "first_indicator");
    model.setObjective((GRBLinExpr(x) - 2.0) * (GRBLinExpr(x) - 2.0) + GRBLinExpr(z) * 0.1);
    model.optimize();
    require(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL, "first persistent solve failed");
    require(std::abs(x.getValue() - 2) < 1e-6 && std::abs(z.getValue()) < 1e-6, "first solution mismatch");
    require(fixed.getValue() == 0.5 && unused.getValue() >= 0, "omitted variable mapping failed");
    if (const char* hold = std::getenv("SANDO_AMPL_PROBE_HOLD_SECONDS")) {
      const int seconds = std::atoi(hold);
      if (seconds > 0) {
        std::cout << "Holding persistent model for " << seconds << " seconds\n" << std::flush;
        std::this_thread::sleep_for(std::chrono::seconds(seconds));
      }
    }

    // Normal update (audit off, verify off): fast path, no model.nl required.
    model.remove(z);
    model.remove(first_indicator);
    auto replacement = model.addVar(0.0, 1.0, 0.0, GRB_BINARY, "switch");
    model.addGenConstrIndicator(replacement, 1, GRBLinExpr(x) <= 3.0, "second_indicator");
    model.addConstr(GRBLinExpr(replacement) == 1.0);
    model.addQConstr(GRBLinExpr(x) * GRBLinExpr(x) <= 1.5625, "quadratic_bound");
    auto objective = GRBLinExpr(1.25) + (GRBLinExpr(x) * GRBLinExpr(x)) - 3.0 * GRBLinExpr(x)
                     + 0.25 * (GRBLinExpr(x) * GRBLinExpr(replacement));
    model.setObjective(objective);
    model.optimize();
    require(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL, "updated persistent solve failed");
    require(std::abs(model.get(GRB_DoubleAttr_ObjVal) + 0.625) < 1e-6, "updated objective mismatch");
    require(std::abs(x.getValue() - 1.25) < 1e-6 && std::abs(replacement.getValue() - 1) < 1e-6,
            "updated solution mismatch");

    // Update + independent verify with audit off: must export/compile for model.nl.
    setenv("SANDO_AMPL_VERIFY_UPDATES", "1", 1);
    model.addConstr(GRBLinExpr(x) <= 1);
    model.optimize();
    require(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL && std::abs(x.getValue() - 1) < 1e-6,
            "persistent inequality direction mismatch under verify");

    // Audit + verify together.
    const auto audit_root =
        std::filesystem::temp_directory_path() /
        ("sando-ampl-audit-" + std::to_string(::getpid()));
    std::filesystem::create_directories(audit_root);
    setenv("SANDO_AMPL_AUDIT_DIR", audit_root.string().c_str(), 1);
    model.setObjective(GRBLinExpr(x) * GRBLinExpr(x));
    model.optimize();
    require(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL, "audit+verify update failed");
    bool found_audit = false;
    for (const auto& entry : std::filesystem::directory_iterator(audit_root)) {
      if (!entry.is_directory()) continue;
      found_audit = std::filesystem::exists(entry.path() / "model.nl") &&
                    std::filesystem::exists(entry.path() / "native.lp");
      if (found_audit) break;
    }
    require(found_audit, "audit directory missing model.nl");
    unset("SANDO_AMPL_AUDIT_DIR");
    std::error_code cleanup_error;
    std::filesystem::remove_all(audit_root, cleanup_error);

    // Infeasible terminal status still runs verify when enabled.
    model.addConstr(GRBLinExpr(x) >= 2);
    model.optimize();
    require(model.get(GRB_IntAttr_Status) == GRB_INFEASIBLE, "infeasible update not detected");

    unset("SANDO_AMPL_VERIFY_UPDATES");
    std::cout << "Persistent AMPLS update probe passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "Persistent AMPLS update probe failed: " << error.what() << '\n';
    return 1;
  }
}
