#include "sando/ampl_model.hpp"
// Keep the recorder header before Gurobi's macro definitions.
#include "gurobi_interface.h"

#include <cerrno>
#include <chrono>
#include <cmath>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <iostream>
#include <iomanip>
#include <memory>
#include <spawn.h>
#include <sstream>
#include <set>
#include <sys/wait.h>
#include <unistd.h>
#include <fcntl.h>
#include <algorithm>

extern char** environ;

namespace sando_ampl {
namespace {
namespace fs = std::filesystem;

void check(int code, GRBmodel* model, const char* operation) {
  if (code)
    throw GRBException(std::string(operation) + ": " +
                       GRBgeterrormsg(GRBgetenv(model)), code);
}

class WorkDirectory {
 public:
  WorkDirectory() {
    std::string pattern = (fs::temp_directory_path() / "sando-ampl-XXXXXX").string();
    std::vector<char> name(pattern.begin(), pattern.end());
    name.push_back('\0');
    const char* created = mkdtemp(name.data());
    if (!created) throw GRBException("Cannot create AMPL work directory", errno);
    path = created;
  }
  ~WorkDirectory() {
    std::error_code error;
    fs::remove_all(path, error);
  }
  fs::path path;
};

// posix_spawn avoids running C++ allocation or lock operations after fork in
// the planner's multithreaded process. Each interpreter writes only its own files.
void compileModel(const fs::path& directory) {
  const fs::path run = directory / "compile.run";
  {
    std::ofstream stream(run);
    stream << "option presolve 0;\noption auxfiles rc;\nmodel '"
           << (directory / "model.mod").string() << "';\nwrite g"
           << (directory / "model").string() << ";\n";
    if (!stream) throw GRBException("Cannot write AMPL compilation commands");
  }
  const char* configured = std::getenv("SANDO_AMPL_EXECUTABLE");
  std::string executable = configured ? configured : "ampl";
  std::string input = run.string();
  char* arguments[] = {executable.data(), input.data(), nullptr};
  posix_spawn_file_actions_t actions;
  int result = posix_spawn_file_actions_init(&actions);
  if (result) throw GRBException("Cannot initialize AMPL process", result);
  const auto log = (directory / "compile.log").string();
  result = posix_spawn_file_actions_addopen(&actions, STDOUT_FILENO,
                                           log.c_str(), O_CREAT | O_TRUNC | O_WRONLY, 0600);
  if (!result) result = posix_spawn_file_actions_adddup2(&actions, STDOUT_FILENO, STDERR_FILENO);
  pid_t pid = -1;
  if (!result) result = posix_spawnp(&pid, executable.c_str(), &actions, nullptr, arguments, environ);
  posix_spawn_file_actions_destroy(&actions);
  if (result) throw GRBException("Cannot execute AMPL interpreter: " + executable, result);
  int status = 0;
  while (waitpid(pid, &status, 0) < 0) {
    if (errno != EINTR) throw GRBException("Cannot wait for AMPL interpreter", errno);
  }
  if (!WIFEXITED(status) || WEXITSTATUS(status) != 0 || !fs::exists(directory / "model.nl")) {
    std::ifstream stream(log);
    std::ostringstream message;
    message << stream.rdbuf();
    throw GRBException("AMPL model compilation failed: " + message.str().substr(0, 4096));
  }
}

class CallbackBridge final : public ampls::GurobiCallback {
 public:
  explicit CallbackBridge(GRBCallback* callback) : callback_(callback) {}
  int run() override {
    if (!callback_) return 0;
    try {
      callback_->callback();
      return callback_->aborted() ? -1 : 0;
    } catch (...) {
      error_ = std::current_exception();
      return -1;
    }
  }
  GRBCallback* callback_;
  std::exception_ptr error_;
};

struct CallbackRegistration {
  GRBmodel* model;
  ~CallbackRegistration() { GRBsetcallbackfunc(model, nullptr, nullptr); }
};

// AMPLS/Gurobi's model import and destruction touch process-wide driver state.
// Keep those lifecycle operations serialized, while leaving compilation and
// native optimization concurrent. The deleter is locked independently because
// a retained model can outlive the solve that created it.
std::mutex& amplsLifecycleMutex() {
  static std::mutex mutex;
  return mutex;
}

struct GurobiModelDeleter {
  void operator()(ampls::GurobiModel* model) const noexcept {
    if (!model) return;
    std::lock_guard<std::mutex> lock(amplsLifecycleMutex());
    delete model;
  }
};

using OwnedGurobiModel = std::unique_ptr<ampls::GurobiModel, GurobiModelDeleter>;

OwnedGurobiModel loadGurobiModel(const char* path, const char** options) {
  std::lock_guard<std::mutex> lock(amplsLifecycleMutex());
  auto loaded = ampls::AMPLModel::load<ampls::GurobiModel>(path, options);
  return OwnedGurobiModel(new ampls::GurobiModel(std::move(loaded)));
}

class AmplsRuntime final : public Runtime {
 public:
  RuntimeResult solve(const ModelSnapshot& snapshot, GRBCallback* callback,
                      const RuntimeParameters& parameters) override {
    try {
      const bool keep_model = persistent();
      if (!keep_model) model_.reset();
      const bool updating = keep_model && model_ != nullptr;
      if (callback && callback->aborted()) {
        RuntimeResult stopped;
        stopped.status = GRB_INTERRUPTED;
        return stopped;
      }
      const auto begin = std::chrono::steady_clock::now();
      WorkDirectory directory;
      exportAmplModel(snapshot, (directory.path / "model.mod").string());
      const auto exported = std::chrono::steady_clock::now();
      compileModel(directory.path);
      const auto compiled = std::chrono::steady_clock::now();
      const char* options[] = {"outlev=0", "cvt:names=1", nullptr};
      OwnedGurobiModel imported;
      if (!updating) {
        imported = loadGurobiModel((directory.path / "model.nl").c_str(), options);
        if (keep_model) model_ = std::move(imported);
      } else updateNative(model_->getGRBmodel(), snapshot);
      ampls::GurobiModel* model = keep_model ? model_.get() : imported.get();
      GRBmodel* native = model->getGRBmodel();
      GRBenv* environment = GRBgetenv(native);
      check(GRBsetintparam(environment, GRB_INT_PAR_OUTPUTFLAG, parameters.output_flag), native, "OutputFlag");
      check(GRBsetintparam(environment, GRB_INT_PAR_LOGTOCONSOLE, parameters.log_to_console), native, "LogToConsole");
      check(GRBsetintparam(environment, GRB_INT_PAR_THREADS, parameters.threads), native, "Threads");
      check(GRBsetdblparam(environment, GRB_DBL_PAR_TIMELIMIT, parameters.time_limit), native, "TimeLimit");

      // AMPL/MP may reorder columns and introduce auxiliaries. Match the stable
      // recorder identity against native names, rather than using a row position.
      int count = 0;
      check(GRBgetintattr(native, GRB_INT_ATTR_NUMVARS, &count), native, "NumVars");
      std::map<std::string, int> native_names;
      for (int i = 0; i < count; ++i) {
        char* name = nullptr;
        check(GRBgetstrattrelement(native, GRB_STR_ATTR_VARNAME, i, &name), native, "VarName");
        native_names.emplace(name, i);
      }
      std::map<std::uint64_t, int> columns;
      std::set<std::uint64_t> referenced;
      auto references = [&](const ExpressionSnapshot& expression) {
        for (const auto& term : expression.linear)
          if (term.coefficient != 0) referenced.insert(term.variable);
        for (const auto& term : expression.quadratic) {
          if (term.coefficient != 0) { referenced.insert(term.first); referenced.insert(term.second); }
        }
      };
      references(snapshot.objective);
      for (const auto& constraint : snapshot.constraints) {
        references(constraint.expression);
        if (constraint.indicator) referenced.insert(constraint.indicator_variable);
      }
      for (const auto& variable : snapshot.variables) {
        const std::string name = "v_" + std::to_string(variable.id);
        auto found = native_names.find(name);
        if (found == native_names.end()) {
          if (referenced.count(variable.id) && variable.lb != variable.ub)
            throw GRBException("AMPLS native model omitted referenced variable " + name);
          // AMPL drops unused/fixed declarations even with presolve disabled.
          // Restore exactly their recorded domains in the imported model. An
          // unused variable has no objective/row coefficients; fixed variable
          // contributions have already been substituted by the compiler.
          check(GRBaddvar(native, 0, nullptr, nullptr, 0, variable.lb,
                          variable.ub, variable.type, name.c_str()), native, "Restore omitted variable");
          columns.emplace(variable.id, count++);
        } else columns.emplace(variable.id, found->second);
      }
      check(GRBupdatemodel(native), native, "Update restored variables");
      if (const char* audit = std::getenv("SANDO_AMPL_AUDIT_DIR")) {
        const fs::path target = fs::path(audit) / directory.path.filename();
        fs::create_directories(target);
        for (const char* file : {"model.mod", "model.nl", "model.col", "model.row"})
          fs::copy_file(directory.path / file, target / file);
        check(GRBwrite(native, (target / "native.lp").c_str()), native, "Write native audit");
      }
      CallbackBridge bridge(callback);
      CallbackRegistration registration{native};
      check(model->setCallback(&bridge), native, "Set callback");
      // Honor cancellation arriving while AMPL compiled/imported the problem.
      RuntimeResult result;
      if (callback) {
        callback->callback();
        if (callback->aborted()) {
          result.status = GRB_INTERRUPTED;
          return result;
        }
      }
      const auto prepared = std::chrono::steady_clock::now();
      check(GRBoptimize(native), native, "Optimize");
      const auto solved = std::chrono::steady_clock::now();
      if (bridge.error_) {
        std::rethrow_exception(bridge.error_);
      }
      check(GRBgetintattr(native, GRB_INT_ATTR_STATUS, &result.status), native, "Status");
      check(GRBgetdblattr(native, GRB_DBL_ATTR_RUNTIME, &result.runtime), native, "Runtime");
      double native_objective = 0;
      if (result.status == GRB_OPTIMAL) {
        check(GRBgetdblattr(native, GRB_DBL_ATTR_OBJVAL, &native_objective), native, "ObjVal");
        for (const auto& column : columns) {
          double value = 0;
          check(GRBgetdblattrelement(native, GRB_DBL_ATTR_X, column.second, &value), native, "X");
          if (!std::isfinite(value)) throw GRBException("Non-finite AMPLS solution");
          result.values.emplace(column.first, value);
        }
        // Postsolve into the original model: native MIQCP ObjVal can differ
        // numerically from its quadratic evaluated at the returned X. Report
        // the recorded objective at that same point, keeping raw ObjVal in the
        // optional diagnostic trace. Status and solver tolerances stay native.
        result.objective = evaluate(snapshot.objective, result.values);
        if (!std::isfinite(result.objective)) throw GRBException("Non-finite original objective");
      }
      if (const char* trace = std::getenv("SANDO_AMPL_TRACE"); trace && std::string(trace) == "1") {
        const auto read = std::chrono::steady_clock::now();
        auto ms = [](auto a, auto b) { return std::chrono::duration<double, std::milli>(b - a).count(); };
        static std::mutex output_mutex;
        std::lock_guard<std::mutex> lock(output_mutex);
        if (result.status == GRB_OPTIMAL)
          std::cerr << std::setprecision(17) << "AMPLS objective native=" << native_objective
                    << " original=" << result.objective << "\n";
        std::cerr << "AMPLS timing mode=" << (updating ? "update" : "import")
                  << " export_ms=" << ms(begin, exported)
                  << " compile_ms=" << ms(exported, compiled)
                  << " prepare_ms=" << ms(compiled, prepared)
                  << " solve_ms=" << ms(prepared, solved)
                  << " read_ms=" << ms(solved, read)
                  << " total_ms=" << ms(begin, read)
                  << " gurobi_ms=" << result.runtime * 1000
                  << " status=" << result.status << "\n";
      }
      // The callback points at a stack object.  Never leave it installed on
      // the retained model after this request returns.
      check(GRBsetcallbackfunc(native, nullptr, nullptr), native, "Clear callback");
      const char* verify = std::getenv("SANDO_AMPL_VERIFY_UPDATES");
      if (updating && verify && std::string(verify) == "1" &&
          (result.status == GRB_OPTIMAL || result.status == GRB_INFEASIBLE ||
           result.status == GRB_UNBOUNDED || result.status == GRB_INF_OR_UNBD))
        verifyUpdate(directory.path / "model.nl", snapshot, result, parameters);
      // model remains the sole owner of the borrowed native pointer.
      return result;
    } catch (const GRBException&) {
      throw;
    } catch (const std::exception& error) {
      throw GRBException(std::string("AMPLS: ") + error.what());
    }
  }

 private:
  static bool persistent() {
    const char* mode = std::getenv("SANDO_AMPL_MODE");
    return mode && std::string(mode) == "persistent";
  }

  static std::map<std::uint64_t, int> nativeColumns(GRBmodel* native) {
    int count = 0;
    check(GRBgetintattr(native, GRB_INT_ATTR_NUMVARS, &count), native, "NumVars");
    std::map<std::uint64_t, int> columns;
    for (int i = 0; i < count; ++i) {
      char* name = nullptr;
      check(GRBgetstrattrelement(native, GRB_STR_ATTR_VARNAME, i, &name), native, "VarName");
      if (!name) continue;
      const std::string prefix = "v_";
      if (std::string(name).compare(0, prefix.size(), prefix) == 0) {
        try {
          const std::string suffix = std::string(name).substr(prefix.size());
          std::size_t consumed = 0;
          const auto id = std::stoull(suffix, &consumed);
          if (consumed == suffix.size()) columns.emplace(id, i);
        }
        catch (const std::exception&) { /* MP auxiliary name */ }
      }
    }
    return columns;
  }

  static void clearNative(GRBmodel* native) {
    int n = 0;
    check(GRBgetintattr(native, GRB_INT_ATTR_NUMCONSTRS, &n), native, "NumConstrs");
    if (n) { std::vector<int> ids(n); for (int i = 0; i < n; ++i) ids[i] = i;
      check(GRBdelconstrs(native, n, ids.data()), native, "Delete linear constraints"); }
    check(GRBgetintattr(native, GRB_INT_ATTR_NUMQCONSTRS, &n), native, "NumQConstrs");
    if (n) { std::vector<int> ids(n); for (int i = 0; i < n; ++i) ids[i] = i;
      check(GRBdelqconstrs(native, n, ids.data()), native, "Delete quadratic constraints"); }
    check(GRBgetintattr(native, GRB_INT_ATTR_NUMGENCONSTRS, &n), native, "NumGenConstrs");
    if (n) { std::vector<int> ids(n); for (int i = 0; i < n; ++i) ids[i] = i;
      check(GRBdelgenconstrs(native, n, ids.data()), native, "Delete general constraints"); }
    check(GRBupdatemodel(native), native, "Clear constraints");
  }

  static void updateNative(GRBmodel* native, const ModelSnapshot& snapshot) {
    clearNative(native);
    const auto old = nativeColumns(native);
    std::set<std::uint64_t> wanted;
    for (const auto& variable : snapshot.variables) wanted.insert(variable.id);
    std::vector<int> remove;
    int count = 0;
    check(GRBgetintattr(native, GRB_INT_ATTR_NUMVARS, &count), native, "NumVars");
    std::set<int> retained_columns;
    for (const auto& [id, column] : old)
      if (wanted.count(id)) retained_columns.insert(column);
    // MP auxiliaries may share a recorder-name prefix; only exact identities
    // in the current snapshot are retained.
    for (int i = 0; i < count; ++i) {
      if (!retained_columns.count(i)) remove.push_back(i);
    }
    std::sort(remove.begin(), remove.end());
    remove.erase(std::unique(remove.begin(), remove.end()), remove.end());
    if (!remove.empty()) check(GRBdelvars(native, static_cast<int>(remove.size()), remove.data()), native, "Delete native variables");
    check(GRBupdatemodel(native), native, "Delete native variables update");

    auto columns = nativeColumns(native);
    for (const auto& variable : snapshot.variables) {
      const auto found = columns.find(variable.id);
      int column;
      if (found == columns.end()) {
        const std::string name = "v_" + std::to_string(variable.id);
        check(GRBaddvar(native, 0, nullptr, nullptr, 0, variable.lb, variable.ub,
                        variable.type, name.c_str()), native, "Add recorder variable");
      } else {
        column = found->second;
        check(GRBsetdblattrelement(native, GRB_DBL_ATTR_LB, column, variable.lb), native, "Variable lower bound");
        check(GRBsetdblattrelement(native, GRB_DBL_ATTR_UB, column, variable.ub), native, "Variable upper bound");
        check(GRBsetcharattrelement(native, GRB_CHAR_ATTR_VTYPE, column, variable.type), native, "Variable type");
      }
    }
    check(GRBupdatemodel(native), native, "Add recorder variables");
    columns = nativeColumns(native);
    for (const auto& variable : snapshot.variables) {
      const int column = columns.at(variable.id);
      check(GRBsetdblattrelement(native, GRB_DBL_ATTR_LB, column, variable.lb), native, "Variable lower bound");
      check(GRBsetdblattrelement(native, GRB_DBL_ATTR_UB, column, variable.ub), native, "Variable upper bound");
      check(GRBsetcharattrelement(native, GRB_CHAR_ATTR_VTYPE, column, variable.type), native, "Variable type");
    }
    auto addTerms = [&](const ExpressionSnapshot& expression, std::vector<int>& indices,
                        std::vector<double>& values) {
      for (const auto& term : expression.linear) {
        auto found = columns.find(term.variable);
        if (found == columns.end()) throw GRBException("missing recorder variable", 10005);
        indices.push_back(found->second); values.push_back(term.coefficient);
      }
    };
    for (const auto& constraint : snapshot.constraints) {
      std::vector<int> linear_indices; std::vector<double> linear_values;
      addTerms(constraint.expression, linear_indices, linear_values);
      const double rhs = constraint.rhs - constraint.expression.constant;
      const char sense = constraint.sense == GRB_LESS_EQUAL ? '<' : constraint.sense == GRB_GREATER_EQUAL ? '>' : '=';
      const std::string name = "c_" + std::to_string(constraint.id);
      if (constraint.indicator) {
        const auto indicator = columns.find(constraint.indicator_variable);
        if (indicator == columns.end()) throw GRBException("missing indicator variable", 10005);
        check(GRBaddgenconstrIndicator(native, name.c_str(), indicator->second,
                                        constraint.indicator_value,
                                        static_cast<int>(linear_indices.size()),
                                        linear_indices.empty() ? nullptr : linear_indices.data(),
                                        linear_values.empty() ? nullptr : linear_values.data(),
                                        sense, rhs), native, "Add indicator constraint");
      } else if (constraint.quadratic || !constraint.expression.quadratic.empty()) {
        std::vector<int> qrow, qcol; std::vector<double> qval;
        for (const auto& term : constraint.expression.quadratic) {
          qrow.push_back(columns.at(term.first)); qcol.push_back(columns.at(term.second)); qval.push_back(term.coefficient);
        }
        check(GRBaddqconstr(native, static_cast<int>(linear_indices.size()),
                            linear_indices.empty() ? nullptr : linear_indices.data(),
                            linear_values.empty() ? nullptr : linear_values.data(),
                            static_cast<int>(qval.size()), qrow.empty() ? nullptr : qrow.data(),
                            qcol.empty() ? nullptr : qcol.data(), qval.empty() ? nullptr : qval.data(),
                            sense, rhs, name.c_str()), native, "Add quadratic constraint");
      } else {
        check(GRBaddconstr(native, static_cast<int>(linear_indices.size()),
                           linear_indices.empty() ? nullptr : linear_indices.data(),
                           linear_values.empty() ? nullptr : linear_values.data(), sense, rhs,
                           name.c_str()), native, "Add linear constraint");
      }
    }
    check(GRBsetintattr(native, GRB_INT_ATTR_MODELSENSE, snapshot.objective_sense == GRB_MAXIMIZE ? -1 : 1), native, "Objective sense");
    check(GRBsetdblattr(native, GRB_DBL_ATTR_OBJCON, snapshot.objective.constant), native, "Objective constant");
    count = 0; check(GRBgetintattr(native, GRB_INT_ATTR_NUMVARS, &count), native, "NumVars");
    for (int i = 0; i < count; ++i) {
      check(GRBsetdblattrelement(native, GRB_DBL_ATTR_OBJ, i, 0.0), native, "Clear linear objective");
    }
    check(GRBdelq(native), native, "Clear quadratic objective");
    for (const auto& term : snapshot.objective.linear) check(GRBsetdblattrelement(native, GRB_DBL_ATTR_OBJ, columns.at(term.variable), term.coefficient), native, "Set linear objective");
    std::vector<int> qrow, qcol;
    std::vector<double> qvalue;
    for (const auto& term : snapshot.objective.quadratic) {
      qrow.push_back(columns.at(term.first));
      qcol.push_back(columns.at(term.second));
      qvalue.push_back(term.coefficient);
    }
    if (!qvalue.empty())
      check(GRBaddqpterms(native, static_cast<int>(qvalue.size()), qrow.data(), qcol.data(), qvalue.data()), native, "Set quadratic objective");
    check(GRBupdatemodel(native), native, "Commit persistent update");
    check(GRBgetintattr(native, GRB_INT_ATTR_NUMVARS, &count), native, "Updated native variable count");
    if (static_cast<std::size_t>(count) != snapshot.variables.size())
      throw GRBException("persistent update retained auxiliary variables");
  }

  static double evaluate(const ExpressionSnapshot& expression,
                         const std::map<std::uint64_t, double>& values) {
    long double value = expression.constant;
    for (const auto& term : expression.linear)
      value += static_cast<long double>(term.coefficient) * values.at(term.variable);
    for (const auto& term : expression.quadratic)
      value += static_cast<long double>(term.coefficient) * values.at(term.first) * values.at(term.second);
    return static_cast<double>(value);
  }

  static void verifyValues(const ModelSnapshot& snapshot,
                           const std::map<std::uint64_t, double>& values,
                           double objective) {
    constexpr double tolerance = 2e-6;
    for (const auto& variable : snapshot.variables) {
      const double value = values.at(variable.id);
      if (value < variable.lb - tolerance || value > variable.ub + tolerance ||
          ((variable.type == GRB_BINARY || variable.type == GRB_INTEGER) &&
           std::abs(value - std::round(value)) > tolerance))
        throw GRBException("persistent verification variable violation", 10006);
    }
    for (const auto& constraint : snapshot.constraints) {
      if (constraint.indicator &&
          std::abs(values.at(constraint.indicator_variable) - constraint.indicator_value) > tolerance)
        continue;
      const double residual = evaluate(constraint.expression, values) - constraint.rhs;
      if ((constraint.sense == GRB_LESS_EQUAL && residual > tolerance) ||
          (constraint.sense == GRB_GREATER_EQUAL && residual < -tolerance) ||
          (constraint.sense == GRB_EQUAL && std::abs(residual) > tolerance))
        throw GRBException("persistent verification constraint violation", 10006);
    }
    if (std::abs(evaluate(snapshot.objective, values) - objective) >
        tolerance * std::max(1.0, std::abs(objective)))
      throw GRBException("persistent verification objective mismatch", 10006);
  }

  static void verifyUpdate(const fs::path& nl, const ModelSnapshot& snapshot,
                           const RuntimeResult& result,
                           const RuntimeParameters& parameters) {
    const char* options[] = {"outlev=0", "cvt:names=1", nullptr};
    auto verifier = loadGurobiModel(nl.c_str(), options);
    GRBmodel* native = verifier->getGRBmodel();
    GRBenv* environment = GRBgetenv(native);
    check(GRBsetintparam(environment, GRB_INT_PAR_OUTPUTFLAG, parameters.output_flag), native, "Verify OutputFlag");
    check(GRBsetintparam(environment, GRB_INT_PAR_LOGTOCONSOLE, parameters.log_to_console), native, "Verify LogToConsole");
    check(GRBsetintparam(environment, GRB_INT_PAR_THREADS, parameters.threads), native, "Verify Threads");
    check(GRBsetdblparam(environment, GRB_DBL_PAR_TIMELIMIT, parameters.time_limit), native, "Verify TimeLimit");
    check(GRBoptimize(native), native, "Verify optimize");
    int status = 0;
    check(GRBgetintattr(native, GRB_INT_ATTR_STATUS, &status), native, "Verify status");
    if (status != GRB_OPTIMAL && status != GRB_INFEASIBLE &&
        status != GRB_UNBOUNDED && status != GRB_INF_OR_UNBD) {
      std::cerr << "AMPLS persistent verification inconclusive: reference status " << status << "\n";
      return;
    }
    if (status != result.status) throw GRBException("persistent verification status mismatch", 10006);
    if (status != GRB_OPTIMAL) return;
    std::map<std::uint64_t, double> values;
    const auto columns = nativeColumns(native);
    for (const auto& variable : snapshot.variables) {
      auto found = columns.find(variable.id);
      double value = 0;
      if (found != columns.end()) {
        check(GRBgetdblattrelement(native, GRB_DBL_ATTR_X, found->second, &value), native, "Verify X");
      } else {
        auto refers = [&](const ExpressionSnapshot& expression) {
          for (const auto& term : expression.linear)
            if (term.variable == variable.id && term.coefficient != 0) return true;
          for (const auto& term : expression.quadratic)
            if ((term.first == variable.id || term.second == variable.id) && term.coefficient != 0) return true;
          return false;
        };
        bool referenced = refers(snapshot.objective);
        for (const auto& constraint : snapshot.constraints)
          referenced = referenced || refers(constraint.expression) ||
              (constraint.indicator && constraint.indicator_variable == variable.id);
        if (referenced && variable.lb != variable.ub)
          throw GRBException("verification lost a referenced variable");
        value = std::max(variable.lb, std::min(0.0, variable.ub));
        if (variable.type != GRB_CONTINUOUS) value = std::ceil(value);
      }
      values.emplace(variable.id, value);
    }
    const double objective = evaluate(snapshot.objective, values);
    if (std::abs(objective - result.objective) > 2e-6 * std::max(1.0, std::abs(result.objective)))
      throw GRBException("persistent verification objective mismatch", 10006);
    verifyValues(snapshot, result.values, result.objective);
    verifyValues(snapshot, values, objective);
  }

  OwnedGurobiModel model_;
};
}  // namespace

std::shared_ptr<Runtime> createRuntime() { return std::make_shared<AmplsRuntime>(); }
}  // namespace sando_ampl
