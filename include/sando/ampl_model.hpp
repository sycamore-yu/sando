#pragma once

// A deliberately small source-compatible subset of the Gurobi C++ modeling API.
// It records the model; solving is supplied by Runtime (the AMPLS adapter).

#include <cstdint>
#include <map>
#include <memory>
#include <string>
#include <utility>
#include <vector>
#include <exception>

namespace sando_ampl {

struct ModelData;

constexpr double GRB_INFINITY = 1.0e100;
constexpr char GRB_CONTINUOUS = 'C';
constexpr char GRB_BINARY = 'B';
constexpr char GRB_INTEGER = 'I';
constexpr char GRB_LESS_EQUAL = '<';
constexpr char GRB_EQUAL = '=';
constexpr char GRB_GREATER_EQUAL = '>';
constexpr int GRB_MINIMIZE = 1;
constexpr int GRB_MAXIMIZE = -1;
constexpr int GRB_OPTIMAL = 2;
constexpr int GRB_INFEASIBLE = 3;
constexpr int GRB_INF_OR_UNBD = 4;
constexpr int GRB_UNBOUNDED = 5;
constexpr int GRB_INTERRUPTED = 11;
constexpr int GRB_NUMERIC = 12;

enum class IntAttr { Status, NumVars };
enum class DoubleAttr { X, ObjVal, Runtime };
enum class StringAttr { ModelName };
enum class IntParam { OutputFlag, LogToConsole, Threads };
enum class DoubleParam { TimeLimit };
constexpr IntAttr GRB_IntAttr_Status = IntAttr::Status;
constexpr IntAttr GRB_IntAttr_NumVars = IntAttr::NumVars;
constexpr DoubleAttr GRB_DoubleAttr_X = DoubleAttr::X;
constexpr DoubleAttr GRB_DoubleAttr_ObjVal = DoubleAttr::ObjVal;
constexpr DoubleAttr GRB_DoubleAttr_Runtime = DoubleAttr::Runtime;
constexpr StringAttr GRB_StringAttr_ModelName = StringAttr::ModelName;
constexpr IntParam GRB_IntParam_OutputFlag = IntParam::OutputFlag;
constexpr IntParam GRB_IntParam_LogToConsole = IntParam::LogToConsole;
constexpr IntParam GRB_IntParam_Threads = IntParam::Threads;
constexpr DoubleParam GRB_DoubleParam_TimeLimit = DoubleParam::TimeLimit;

class GRBException : public std::exception {
 public:
  GRBException(std::string message = {}, int code = 0) noexcept;
  const char* what() const noexcept override;
  const char* getMessage() const noexcept;
  int getErrorCode() const noexcept;

 private:
  std::string message_;
  int code_;
};

struct VariableSnapshot {
  std::uint64_t id{};
  std::string name;
  double lb{}, ub{}, objective{};
  char type{GRB_CONTINUOUS};
};
struct LinearTerm {
  std::uint64_t variable{};
  double coefficient{};
};
struct QuadraticTerm {
  std::uint64_t first{}, second{};
  double coefficient{};
};
struct ExpressionSnapshot {
  double constant{};
  std::vector<LinearTerm> linear;
  std::vector<QuadraticTerm> quadratic;
};
struct ConstraintSnapshot {
  std::uint64_t id{};
  std::string name;
  ExpressionSnapshot expression;
  int sense{GRB_EQUAL};
  double rhs{};
  bool quadratic{false};
  bool indicator{false};
  std::uint64_t indicator_variable{};
  int indicator_value{};
};
struct ModelSnapshot {
  std::string name;
  std::vector<VariableSnapshot> variables;
  std::vector<ConstraintSnapshot> constraints;
  ExpressionSnapshot objective;
  int objective_sense{GRB_MINIMIZE};
  std::uint64_t revision{};
};
struct RuntimeParameters {
  int output_flag{0};
  int log_to_console{0};
  int threads{0};
  double time_limit{GRB_INFINITY};
};
struct RuntimeResult {
  int status{GRB_NUMERIC};
  double objective{};
  double runtime{};
  std::map<std::uint64_t, double> values;
};

class GRBCallback {
 public:
  virtual ~GRBCallback() = default;
  virtual void callback() {}
  void abort() noexcept { aborted_ = true; }
  void resetAbort() noexcept { aborted_ = false; }
  bool aborted() const noexcept { return aborted_; }

 private:
  bool aborted_{false};
};

class Runtime {
 public:
  virtual ~Runtime() = default;
  virtual RuntimeResult solve(const ModelSnapshot&, GRBCallback*, const RuntimeParameters&) = 0;
};

std::shared_ptr<Runtime> createRuntime();

class GRBVar;
class GRBLinExpr;
class GRBQuadExpr;
struct GRBTempConstr;

class GRBLinExpr {
 public:
  GRBLinExpr();
  GRBLinExpr(double constant);
  GRBLinExpr(const GRBVar& variable);
  double getValue() const;
  GRBLinExpr& operator+=(const GRBLinExpr&);
  GRBLinExpr& operator-=(const GRBLinExpr&);
  GRBLinExpr& operator*=(double);
  GRBLinExpr& operator/=(double);
  double constant() const { return constant_; }
  const std::map<std::uint64_t, double>& terms() const { return terms_; }

 public:
  double constant_{};
  std::map<std::uint64_t, double> terms_;
  std::weak_ptr<struct ModelData> model_;
  friend class GRBModel;
  friend class GRBQuadExpr;
  friend GRBLinExpr operator+(GRBLinExpr, const GRBLinExpr&);
  friend GRBLinExpr operator-(GRBLinExpr, const GRBLinExpr&);
  friend GRBLinExpr operator*(GRBLinExpr, double);
  friend GRBLinExpr operator*(double, GRBLinExpr);
  friend GRBLinExpr operator/(GRBLinExpr, double);
};

class GRBQuadExpr {
 public:
  GRBQuadExpr();
  GRBQuadExpr(double constant);
  GRBQuadExpr(const GRBLinExpr& expression);
  double getValue() const;
  GRBQuadExpr& operator+=(const GRBQuadExpr&);
  GRBQuadExpr& operator-=(const GRBQuadExpr&);
  GRBQuadExpr& operator*=(double);

 public:
  double constant_{};
  std::map<std::uint64_t, double> linear_;
  std::map<std::pair<std::uint64_t, std::uint64_t>, double> quadratic_;
  std::weak_ptr<struct ModelData> model_;
  friend class GRBModel;
  friend GRBQuadExpr operator+(GRBQuadExpr, const GRBQuadExpr&);
  friend GRBQuadExpr operator-(GRBQuadExpr, const GRBQuadExpr&);
  friend GRBQuadExpr operator*(GRBQuadExpr, double);
  friend GRBQuadExpr operator*(double, GRBQuadExpr);
  friend GRBQuadExpr operator*(const GRBLinExpr&, const GRBLinExpr&);
};

class GRBVar {
 public:
  GRBVar() = default;
  double get(DoubleAttr attr) const;
  double getValue() const { return get(GRB_DoubleAttr_X); }
  explicit operator bool() const noexcept { return id_ != 0; }

 private:
  std::uint64_t id_{};
  std::weak_ptr<struct ModelData> model_;
  GRBVar(std::uint64_t id, const std::shared_ptr<struct ModelData>& model)
      : id_(id), model_(model) {}
  friend class GRBModel;
  friend class GRBLinExpr;
};

struct GRBTempConstr {
  GRBQuadExpr expression;
  int sense{GRB_EQUAL};
  double rhs{};
};
class GRBConstr {
 public:
  GRBConstr() = default;

 private:
  std::uint64_t id_{};
  std::weak_ptr<struct ModelData> model_;
  GRBConstr(std::uint64_t id, const std::shared_ptr<struct ModelData>& model)
      : id_(id), model_(model) {}
  friend class GRBModel;
};
class GRBQConstr {
 public:
  GRBQConstr() = default;

 private:
  std::uint64_t id_{};
  std::weak_ptr<struct ModelData> model_;
  GRBQConstr(std::uint64_t id, const std::shared_ptr<struct ModelData>& model)
      : id_(id), model_(model) {}
  friend class GRBModel;
};
class GRBGenConstr {
 public:
  GRBGenConstr() = default;

 private:
  std::uint64_t id_{};
  std::weak_ptr<struct ModelData> model_;
  GRBGenConstr(std::uint64_t id, const std::shared_ptr<struct ModelData>& model)
      : id_(id), model_(model) {}
  friend class GRBModel;
};

class GRBModel {
 public:
  GRBModel();
  GRBModel(const GRBModel&) = delete;
  GRBModel& operator=(const GRBModel&) = delete;
  explicit GRBModel(Runtime* runtime);
  explicit GRBModel(std::shared_ptr<Runtime> runtime);
  ~GRBModel();
  GRBVar addVar(double lb, double ub, double obj, char type, const std::string& name = {});
  std::vector<GRBVar> addVars(
      int count,
      const double* lb = nullptr,
      const double* ub = nullptr,
      const double* obj = nullptr,
      const char* type = nullptr,
      const std::vector<std::string>& names = {});
  std::vector<GRBVar> getVars() const;
  GRBConstr addConstr(const GRBTempConstr&, const std::string& name = {});
  GRBQConstr addQConstr(const GRBTempConstr&, const std::string& name = {});
  GRBGenConstr addGenConstrIndicator(
      const GRBVar&, int value, const GRBTempConstr&, const std::string& name = {});
  GRBGenConstr addGenConstrIndicator(
      const GRBVar&,
      int value,
      const GRBLinExpr&,
      int sense,
      double rhs,
      const std::string& name = {});
  void remove(const GRBVar&);
  void remove(const GRBConstr&);
  void remove(const GRBQConstr&);
  void remove(const GRBGenConstr&);
  void update();
  void setObjective(const GRBQuadExpr&, int sense = GRB_MINIMIZE);
  void setObjective(const GRBLinExpr&, int sense = GRB_MINIMIZE);
  void set(IntParam param, int value);
  void set(DoubleParam param, double value);
  void set(StringAttr attr, const std::string& value);
  void set(IntAttr attr, int value);
  void set(DoubleAttr attr, double value);
  void setCallback(GRBCallback* callback);
  int get(IntAttr attr) const;
  double get(DoubleAttr attr) const;
  void optimize();
  ModelSnapshot snapshot() const;
  void exportModel(const std::string& path) const;
  void write(const std::string& path) const { exportModel(path); }

 private:
  std::shared_ptr<struct ModelData> data_;
};

GRBLinExpr operator+(GRBLinExpr, const GRBLinExpr&);
GRBLinExpr operator+(GRBLinExpr, double);
GRBLinExpr operator+(double, GRBLinExpr);
GRBLinExpr operator-(GRBLinExpr, const GRBLinExpr&);
GRBLinExpr operator-(GRBLinExpr, double);
GRBLinExpr operator-(double, const GRBLinExpr&);
GRBLinExpr operator-(const GRBLinExpr&);
GRBLinExpr operator*(GRBLinExpr, double);
GRBLinExpr operator*(double, GRBLinExpr);
GRBLinExpr operator/(GRBLinExpr, double);
GRBQuadExpr operator+(GRBQuadExpr, const GRBQuadExpr&);
GRBQuadExpr operator+(GRBQuadExpr, const GRBLinExpr&);
GRBQuadExpr operator+(const GRBLinExpr&, GRBQuadExpr);
GRBQuadExpr operator-(GRBQuadExpr, const GRBQuadExpr&);
GRBQuadExpr operator*(GRBQuadExpr, double);
GRBQuadExpr operator*(double, GRBQuadExpr);
GRBQuadExpr operator*(const GRBLinExpr&, const GRBLinExpr&);
GRBQuadExpr operator*(const GRBVar&, const GRBVar&);
GRBTempConstr operator<=(const GRBLinExpr&, double);
GRBTempConstr operator>=(const GRBLinExpr&, double);
GRBTempConstr operator==(const GRBLinExpr&, double);
GRBTempConstr operator<=(const GRBQuadExpr&, double);
GRBTempConstr operator>=(const GRBQuadExpr&, double);
GRBTempConstr operator==(const GRBQuadExpr&, double);
GRBTempConstr operator<=(const GRBVar&, double);
GRBTempConstr operator>=(const GRBVar&, double);
GRBTempConstr operator==(const GRBVar&, double);
GRBTempConstr operator<=(const GRBLinExpr&, const GRBLinExpr&);
GRBTempConstr operator>=(const GRBLinExpr&, const GRBLinExpr&);
GRBTempConstr operator==(const GRBLinExpr&, const GRBLinExpr&);
void exportAmplModel(const ModelSnapshot&, const std::string& path);

}  // namespace sando_ampl
