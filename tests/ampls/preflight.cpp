#include "gurobi_interface.h"

#include <gurobi_c.h>

#include <cmath>
#include <array>
#include <cstdio>
#include <cstdlib>
#include <filesystem>
#include <future>
#include <iostream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <vector>

namespace fs = std::filesystem;

void require(bool condition, const std::string& message) {
  if (!condition)
    throw std::runtime_error(message);
}

void copy_model(const fs::path& source, const fs::path& destination) {
  fs::create_directories(destination.parent_path());
  for (const char* extension : {".nl", ".row", ".col"}) {
    fs::copy_file(source.parent_path() / (source.stem().string() + extension),
                  destination.parent_path() /
                      (destination.stem().string() + extension),
                  fs::copy_options::overwrite_existing);
  }
}

ampls::GurobiModel load_model(const fs::path& nl) {
  const char* options[] = {"cvt:names=1", nullptr};
  return ampls::AMPLModel::load<ampls::GurobiModel>(nl.string().c_str(),
                                                    options);
}

fs::path make_temp_dir() {
  std::array<char, 64> pattern{};
  std::snprintf(pattern.data(), pattern.size(), "%s/ampls-preflight-XXXXXX",
                fs::temp_directory_path().c_str());
  char* result = mkdtemp(pattern.data());
  require(result != nullptr, "mkdtemp failed");
  return fs::path(result);
}

void check_small_model(const fs::path& nl) {
  ampls::GurobiModel model = load_model(nl);
  model.optimize();

  GRBmodel* native = model.getGRBmodel();
  int status = 0;
  require(GRBgetintattr(native, GRB_INT_ATTR_STATUS, &status) == 0,
          "GRBgetintattr(STATUS) failed");
  require(status == GRB_OPTIMAL, "small model did not solve to optimality");

  int native_variables = 0;
  int native_constraints = 0;
  int native_binary_variables = 0;
  require(GRBgetintattr(native, GRB_INT_ATTR_NUMVARS, &native_variables) == 0,
          "GRBgetintattr(NUMVARS) failed");
  require(GRBgetintattr(native, GRB_INT_ATTR_NUMCONSTRS,
                        &native_constraints) == 0,
          "GRBgetintattr(NUMCONSTRS) failed");
  require(GRBgetintattr(native, GRB_INT_ATTR_NUMBINVARS,
                        &native_binary_variables) == 0,
          "GRBgetintattr(NUMBINVARS) failed");
  require(native_variables >= 2 && native_constraints >= 1,
          "native model lost indicator variables or rows: vars=" +
              std::to_string(native_variables) + " rows=" +
              std::to_string(native_constraints));

  double objective = 0.0;
  require(GRBgetdblattr(native, GRB_DBL_ATTR_OBJVAL, &objective) == 0,
          "GRBgetdblattr(OBJVAL) failed");
  require(std::abs(objective - 1.1) < 1e-7,
          "small model objective is not 1.1");

  const auto names = model.getVarMap();
  require(names.size() == 2 && names.count("x") == 1 && names.count("z") == 1,
          "AMPL variable names were not mapped");
  char x_type = 0;
  char z_type = 0;
  require(GRBgetcharattrarray(native, GRB_CHAR_ATTR_VTYPE, names.at("x"), 1,
                              &x_type) == 0 &&
              GRBgetcharattrarray(native, GRB_CHAR_ATTR_VTYPE, names.at("z"), 1,
                                  &z_type) == 0,
          "GRBgetcharattrarray(VTYPE) failed");
  double bounds[2] = {0.0, 0.0};
  require(GRBgetdblattrarray(native, GRB_DBL_ATTR_LB, names.at("z"), 1,
                             bounds) == 0 &&
              GRBgetdblattrarray(native, GRB_DBL_ATTR_UB, names.at("z"), 1,
                                 bounds + 1) == 0,
          "GRBgetdblattrarray(z bounds) failed");
  require(x_type == GRB_CONTINUOUS && z_type == GRB_INTEGER &&
              bounds[0] >= -1e-7 && bounds[1] <= 1.0 + 1e-7,
          "native variable types do not match AMPL x/z declarations: x=" +
              std::string(1, x_type) + " z=" + std::string(1, z_type) +
              " binaries=" + std::to_string(native_binary_variables));
  char* native_names[2] = {nullptr, nullptr};
  require(GRBgetstrattrarray(native, GRB_STR_ATTR_VARNAME, names.at("x"), 1,
                             native_names) == 0 &&
              GRBgetstrattrarray(native, GRB_STR_ATTR_VARNAME, names.at("z"), 1,
                                 native_names + 1) == 0,
          "GRBgetstrattrarray(VARNAME) failed");
  require(std::string(native_names[0]) == "x" &&
              std::string(native_names[1]) == "z",
          "native variable names do not preserve AMPL mapping");
  const auto solution = model.getSolutionVector();
  std::vector<double> native_solution(static_cast<size_t>(native_variables));
  require(GRBgetdblattrarray(native, GRB_DBL_ATTR_X, 0, native_variables,
                              native_solution.data()) == 0,
          "GRBgetdblattrarray(X) failed");
  for (const auto& entry : names) {
    require(entry.second >= 0 && entry.second < native_variables,
            "AMPL mapping points outside native variable array");
    require(std::abs(solution.at(entry.second) - native_solution.at(entry.second)) <
                1e-7,
            "AMPL solution differs from native X at mapped index");
  }
  require(std::abs(solution.at(names.at("x")) - 1.0) < 1e-7,
          "mapped x value is not 1");
  require(std::abs(solution.at(names.at("z")) - 1.0) < 1e-7,
          "mapped z value is not 1");

  double runtime = -1.0;
  require(GRBgetdblattr(native, GRB_DBL_ATTR_RUNTIME, &runtime) == 0,
          "GRBgetdblattr(RUNTIME) failed");
  require(std::isfinite(runtime) && runtime >= 0.0,
          "native runtime is not finite and non-negative");
}

class StopOnFirstMIPCallback : public ampls::GurobiCallback {
 public:
  bool invoked = false;
  bool stop = true;

  int run() override {
    if (getWhere() == GRB_CB_MIP || getWhere() == GRB_CB_MIPSOL) {
      invoked = true;
      if (stop)
        return -1;
    }
    return 0;
  }
};

void check_interrupt_and_recovery(const fs::path& nl) {
  ampls::GurobiModel model = load_model(nl);
  model.setParam(GRB_INT_PAR_THREADS, 1);
  model.setParam(GRB_INT_PAR_PRESOLVE, 0);
  StopOnFirstMIPCallback callback;
  require(model.setCallback(&callback) == 0, "could not install callback");

  model.optimize();
  GRBmodel* native = model.getGRBmodel();
  int status = 0;
  require(GRBgetintattr(native, GRB_INT_ATTR_STATUS, &status) == 0,
          "GRBgetintattr(STATUS) failed after interrupt");
  require(callback.invoked, "hard AMPL model never reached a MIP callback");
  require(status == GRB_INTERRUPTED,
          "callback termination was reported as a successful solve");

  callback.stop = false;
  model.optimize();
  require(GRBgetintattr(native, GRB_INT_ATTR_STATUS, &status) == 0,
          "GRBgetintattr(STATUS) failed after recovery");
  require(status == GRB_OPTIMAL,
          "fresh solve after callback interruption was not optimal");
}

void check_time_limit(const fs::path& nl) {
  ampls::GurobiModel model = load_model(nl);
  model.setParam(GRB_INT_PAR_THREADS, 1);
  model.setParam(GRB_DBL_PAR_TIMELIMIT, 0.0);
  model.optimize();
  int status = 0;
  require(GRBgetintattr(model.getGRBmodel(), GRB_INT_ATTR_STATUS, &status) == 0,
          "GRBgetintattr(STATUS) failed after time limit");
  require(status == GRB_TIME_LIMIT,
          "zero time limit did not produce GRB_TIME_LIMIT");
}

int main(int argc, char** argv) {
  if (argc != 3) {
    std::cerr << "usage: ampls_real_preflight preflight.nl interrupt.nl\n";
    return 2;
  }

  try {
    const fs::path small_source = fs::absolute(argv[1]);
    const fs::path interrupt_source = fs::absolute(argv[2]);
    require(fs::exists(small_source), "preflight NL file does not exist");
    require(fs::exists(interrupt_source), "interrupt NL file does not exist");

    check_small_model(small_source);

    for (int round = 0; round < 9; ++round) {
      const fs::path root = make_temp_dir();
      std::vector<std::future<void>> runs;
      for (int i = 0; i < 9; ++i) {
        const fs::path instance = root / ("instance-" + std::to_string(i)) /
                                  "preflight.nl";
        copy_model(small_source, instance);
        runs.emplace_back(std::async(std::launch::async, [instance] {
          check_small_model(instance);
        }));
      }
      for (auto& run : runs)
        run.get();
      std::error_code cleanup_error;
      fs::remove_all(root, cleanup_error);
    }

    check_interrupt_and_recovery(interrupt_source);
    check_time_limit(interrupt_source);
    std::cout << "AMPLS real-model preflight passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "AMPLS real-model preflight failed: " << error.what() << '\n';
    return 1;
  }
}
