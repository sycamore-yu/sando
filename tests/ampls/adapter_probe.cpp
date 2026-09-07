#include <cmath>
#include <iostream>
#include "sando/ampl_model.hpp"
#include <stdexcept>

using namespace sando_ampl;

void require(bool condition, const char* message) {
  if (!condition) throw std::runtime_error(message);
}

int main() {
  try {
    GRBModel model;
    auto x = model.addVar(0, 2, 0, GRB_CONTINUOUS, "x");
    auto z = model.addVar(0, 1, 0, GRB_BINARY, "z");
    auto unused = model.addVar(0, 1, 0, GRB_BINARY, "unused");
    const auto active =
        model.addGenConstrIndicator(z, 1, GRBLinExpr(x), GRB_LESS_EQUAL, 1, "active");
    model.addGenConstrIndicator(z, 0, GRBLinExpr(x), GRB_LESS_EQUAL, 0, "inactive");
    auto delta = GRBLinExpr(x) - 2.0;
    model.setObjective(delta * delta + GRBLinExpr(z) * 0.1);
    model.optimize();
    require(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL, "adapter model not optimal");
    require(unused.get(GRB_DoubleAttr_X) >= 0 && unused.get(GRB_DoubleAttr_X) <= 1,
            "unused AMPL variable was not restored to its original domain");
    require(std::abs(x.get(GRB_DoubleAttr_X) - 1) < 1e-6, "adapter mapped x incorrectly");
    require(std::abs(z.get(GRB_DoubleAttr_X) - 1) < 1e-6, "adapter mapped z incorrectly");
    require(
        std::abs(model.get(GRB_DoubleAttr_ObjVal) - 1.1) < 1e-6,
        "adapter quadratic objective mismatch");
    model.remove(active);
    model.addQConstr(GRBLinExpr(x) * GRBLinExpr(x) <= 2.25);
    model.optimize();
    require(model.get(GRB_IntAttr_Status) == GRB_OPTIMAL, "updated QCP model not optimal");
    require(std::abs(x.get(GRB_DoubleAttr_X) - 1.5) < 1e-5, "updated QCP solution mismatch");
    model.addConstr(GRBLinExpr(x) >= 1.75);
    model.optimize();
    require(model.get(GRB_IntAttr_Status) != GRB_OPTIMAL, "infeasible model accepted");
    bool stale_rejected = false;
    try {
      (void)x.get(GRB_DoubleAttr_X);
    } catch (const GRBException&) {
      stale_rejected = true;
    }
    require(stale_rejected, "failed solve exposed stale x");
    std::cout << "Real AMPL adapter indicator/QCP/update/infeasible checks passed\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
