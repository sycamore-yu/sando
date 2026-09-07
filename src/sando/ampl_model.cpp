#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <sstream>
#include <sando/ampl_model.hpp>
#include <stdexcept>

namespace sando_ampl {
struct ModelData {
  std::string name;
  struct VarRec {
    VariableSnapshot value;
    bool live{true};
  };
  struct ConRec {
    ConstraintSnapshot value;
    bool live{true};
  };
  std::map<std::uint64_t, VarRec> vars;
  std::map<std::uint64_t, ConRec> cons;
  ExpressionSnapshot objective;
  int objective_sense{GRB_MINIMIZE};
  std::uint64_t next_id{1}, revision{0}, solution_revision{0};
  std::map<std::uint64_t, double> solution;
  RuntimeParameters params;
  std::shared_ptr<Runtime> runtime;
  GRBCallback* callback{};
  int status{GRB_NUMERIC};
  bool solved{false};
  double objval{}, runtime_seconds{};
};
namespace {
using VarRec = ModelData::VarRec;
using ConRec = ModelData::ConRec;

[[noreturn]] void invalid(const char* message) { throw GRBException(message, 10001); }
VarRec& variable(const std::shared_ptr<ModelData>& d, std::uint64_t id) {
  auto it = d->vars.find(id);
  if (it != d->vars.end()) return it->second;
  invalid("invalid variable handle");
}
void invalidate(const std::shared_ptr<ModelData>& d) {
  ++d->revision;
  d->solution.clear();
  d->solution_revision = 0;
  d->status = GRB_NUMERIC;
  d->objval = 0.0;
  d->runtime_seconds = 0.0;
  d->solved = false;
}
ExpressionSnapshot expression(const GRBQuadExpr& e) {
  ExpressionSnapshot out;
  out.constant = e.constant_;
  for (const auto& [id, c] : e.linear_) out.linear.push_back({id, c});
  for (const auto& [ids, c] : e.quadratic_) out.quadratic.push_back({ids.first, ids.second, c});
  return out;
}
void same_model(const std::weak_ptr<ModelData>& a, const std::weak_ptr<ModelData>& b) {
  auto aa = a.lock(), bb = b.lock();
  const std::weak_ptr<ModelData> empty;
  if ((!aa && (a.owner_before(empty) || empty.owner_before(a))) ||
      (!bb && (b.owner_before(empty) || empty.owner_before(b))))
    invalid("expression model no longer exists");
  if (aa && bb && aa != bb) invalid("expressions belong to different models");
}
void require_owner(const std::shared_ptr<ModelData>& model, const std::weak_ptr<ModelData>& owner) {
  if (owner.lock() != model) invalid("handle belongs to another or expired model");
}
void finite(double value) {
  if (!std::isfinite(value)) invalid("non-finite model coefficient");
}
void valid_expression(const std::shared_ptr<ModelData>& d, const GRBQuadExpr& e) {
  same_model(d, e.model_);
  finite(e.constant_);
  for (const auto& [id, coefficient] : e.linear_) {
    finite(coefficient);
    variable(d, id);
  }
  for (const auto& [ids, coefficient] : e.quadratic_) {
    finite(coefficient);
    variable(d, ids.first);
    variable(d, ids.second);
  }
}
void valid_constraint(const std::shared_ptr<ModelData>& model, const GRBTempConstr& constraint) {
  valid_expression(model, constraint.expression);
  finite(constraint.rhs);
  if (constraint.sense != GRB_LESS_EQUAL && constraint.sense != GRB_EQUAL &&
      constraint.sense != GRB_GREATER_EQUAL)
    invalid("invalid constraint sense");
}
void add_linear(GRBQuadExpr& to, const GRBLinExpr& from, double sign) {
  same_model(to.model_, from.model_);
  if (to.model_.expired()) to.model_ = from.model_;
  to.constant_ += sign * from.constant_;
  for (const auto& [id, c] : from.terms_) to.linear_[id] += sign * c;
}
}  // namespace

GRBException::GRBException(std::string message, int code) noexcept
    : message_(std::move(message)), code_(code) {}
const char* GRBException::what() const noexcept { return message_.c_str(); }
const char* GRBException::getMessage() const noexcept { return message_.c_str(); }
int GRBException::getErrorCode() const noexcept { return code_; }

GRBLinExpr::GRBLinExpr() = default;
GRBLinExpr::GRBLinExpr(double c) : constant_(c) {}
GRBLinExpr::GRBLinExpr(const GRBVar& v) : terms_{{v.id_, 1.0}}, model_(v.model_) {
  auto model = model_.lock();
  if (!model) invalid("variable model no longer exists");
  variable(model, v.id_);
}
double GRBLinExpr::getValue() const {
  if (terms_.empty()) return constant_;
  auto d = model_.lock();
  if (!d) invalid("model no longer exists");
  if (d->solution_revision != d->revision) invalid("no valid solution");
  double value = constant_;
  for (const auto& [id, c] : terms_) {
    auto it = d->solution.find(id);
    if (it == d->solution.end()) invalid("solution is missing a variable");
    value += c * it->second;
  }
  return value;
}
GRBLinExpr& GRBLinExpr::operator+=(const GRBLinExpr& e) {
  same_model(model_, e.model_);
  constant_ += e.constant_;
  for (auto [id, c] : e.terms_) terms_[id] += c;
  if (model_.expired()) model_ = e.model_;
  return *this;
}
GRBLinExpr& GRBLinExpr::operator-=(const GRBLinExpr& e) {
  same_model(model_, e.model_);
  constant_ -= e.constant_;
  for (auto [id, c] : e.terms_) terms_[id] -= c;
  if (model_.expired()) model_ = e.model_;
  return *this;
}
GRBLinExpr& GRBLinExpr::operator*=(double s) {
  constant_ *= s;
  for (auto& [id, c] : terms_) c *= s;
  return *this;
}
GRBLinExpr& GRBLinExpr::operator/=(double s) {
  if (s == 0) invalid("division by zero");
  return *this *= (1.0 / s);
}

GRBQuadExpr::GRBQuadExpr() = default;
GRBQuadExpr::GRBQuadExpr(double c) : constant_(c) {}
GRBQuadExpr::GRBQuadExpr(const GRBLinExpr& e)
    : constant_(e.constant_), linear_(e.terms_), model_(e.model_) {}
double GRBQuadExpr::getValue() const {
  if (linear_.empty() && quadratic_.empty()) return constant_;
  auto model = model_.lock();
  if (!model) invalid("model no longer exists");
  if (model->solution_revision != model->revision) invalid("no valid solution");
  auto value_of = [&](std::uint64_t id) {
    const auto found = model->solution.find(id);
    if (found == model->solution.end()) invalid("solution is missing variable");
    return found->second;
  };
  double value = constant_;
  for (const auto& term : linear_) value += term.second * value_of(term.first);
  for (const auto& term : quadratic_)
    value += term.second * value_of(term.first.first) * value_of(term.first.second);
  return value;
}
GRBQuadExpr& GRBQuadExpr::operator+=(const GRBQuadExpr& e) {
  same_model(model_, e.model_);
  constant_ += e.constant_;
  for (auto [i, c] : e.linear_) linear_[i] += c;
  for (auto [ij, c] : e.quadratic_) quadratic_[ij] += c;
  if (model_.expired()) model_ = e.model_;
  return *this;
}
GRBQuadExpr& GRBQuadExpr::operator-=(const GRBQuadExpr& e) {
  same_model(model_, e.model_);
  constant_ -= e.constant_;
  for (auto [i, c] : e.linear_) linear_[i] -= c;
  for (auto [ij, c] : e.quadratic_) quadratic_[ij] -= c;
  if (model_.expired()) model_ = e.model_;
  return *this;
}
GRBQuadExpr& GRBQuadExpr::operator*=(double s) {
  constant_ *= s;
  for (auto& [i, c] : linear_) c *= s;
  for (auto& [ij, c] : quadratic_) c *= s;
  return *this;
}

double GRBVar::get(DoubleAttr attr) const {
  auto d = model_.lock();
  if (!d) invalid("model no longer exists");
  variable(d, id_);
  if (attr == DoubleAttr::X) {
    if (d->solution_revision != d->revision) invalid("no valid solution");
    auto i = d->solution.find(id_);
    if (i == d->solution.end()) invalid("solution is missing variable");
    return i->second;
  }
  invalid("unsupported variable attribute");
}

GRBLinExpr operator+(GRBLinExpr a, const GRBLinExpr& b) { return a += b; }
GRBLinExpr operator+(GRBLinExpr a, double b) {
  a.constant_ += b;
  return a;
}
GRBLinExpr operator+(double a, GRBLinExpr b) {
  b.constant_ += a;
  return b;
}
GRBLinExpr operator-(GRBLinExpr a, const GRBLinExpr& b) { return a -= b; }
GRBLinExpr operator-(GRBLinExpr a, double b) {
  a.constant_ -= b;
  return a;
}
GRBLinExpr operator-(double a, const GRBLinExpr& b) {
  GRBLinExpr r(a);
  return r -= b;
}
GRBLinExpr operator-(const GRBLinExpr& a) {
  auto r = a;
  return r *= -1.0;
}
GRBLinExpr operator*(GRBLinExpr a, double b) { return a *= b; }
GRBLinExpr operator*(double b, GRBLinExpr a) { return a *= b; }
GRBLinExpr operator/(GRBLinExpr a, double b) { return a /= b; }
GRBQuadExpr operator+(GRBQuadExpr a, const GRBQuadExpr& b) { return a += b; }
GRBQuadExpr operator+(GRBQuadExpr a, const GRBLinExpr& b) {
  add_linear(a, b, 1);
  return a;
}
GRBQuadExpr operator+(const GRBLinExpr& a, GRBQuadExpr b) {
  add_linear(b, a, 1);
  return b;
}
GRBQuadExpr operator-(GRBQuadExpr a, const GRBQuadExpr& b) { return a -= b; }
GRBQuadExpr operator*(GRBQuadExpr a, double b) { return a *= b; }
GRBQuadExpr operator*(double b, GRBQuadExpr a) { return a *= b; }
GRBQuadExpr operator*(const GRBLinExpr& a, const GRBLinExpr& b) {
  same_model(a.model_, b.model_);
  GRBQuadExpr r(a.constant_ * b.constant_);
  r.model_ = a.model_.expired() ? b.model_ : a.model_;
  for (auto [i, c] : a.terms_) r.linear_[i] += c * b.constant_;
  for (auto [i, c] : b.terms_) r.linear_[i] += c * a.constant_;
  for (auto [i, c] : a.terms_)
    for (auto [j, d] : b.terms_) {
      auto key = std::minmax(i, j);
      r.quadratic_[key] += c * d;
    }
  return r;
}
GRBQuadExpr operator*(const GRBVar& a, const GRBVar& b) { return GRBLinExpr(a) * GRBLinExpr(b); }
GRBTempConstr operator<=(const GRBLinExpr& e, double r) {
  return {GRBQuadExpr(e), GRB_LESS_EQUAL, r};
}
GRBTempConstr operator>=(const GRBLinExpr& e, double r) {
  return {GRBQuadExpr(e), GRB_GREATER_EQUAL, r};
}
GRBTempConstr operator==(const GRBLinExpr& e, double r) { return {GRBQuadExpr(e), GRB_EQUAL, r}; }
GRBTempConstr operator<=(const GRBQuadExpr& e, double r) { return {e, GRB_LESS_EQUAL, r}; }
GRBTempConstr operator>=(const GRBQuadExpr& e, double r) { return {e, GRB_GREATER_EQUAL, r}; }
GRBTempConstr operator==(const GRBQuadExpr& e, double r) { return {e, GRB_EQUAL, r}; }
GRBTempConstr operator<=(const GRBVar& v, double r) { return GRBLinExpr(v) <= r; }
GRBTempConstr operator>=(const GRBVar& v, double r) { return GRBLinExpr(v) >= r; }
GRBTempConstr operator==(const GRBVar& v, double r) { return GRBLinExpr(v) == r; }
GRBTempConstr operator<=(const GRBLinExpr& a, const GRBLinExpr& b) { return (a - b) <= 0.0; }
GRBTempConstr operator>=(const GRBLinExpr& a, const GRBLinExpr& b) { return (a - b) >= 0.0; }
GRBTempConstr operator==(const GRBLinExpr& a, const GRBLinExpr& b) { return (a - b) == 0.0; }

GRBModel::GRBModel() : data_(std::make_shared<ModelData>()) { data_->runtime = createRuntime(); }
GRBModel::GRBModel(Runtime* r) : GRBModel() {
  data_->runtime = std::shared_ptr<Runtime>(r, [](Runtime*) {});
}
GRBModel::GRBModel(std::shared_ptr<Runtime> r) : GRBModel() { data_->runtime = std::move(r); }
GRBModel::~GRBModel() = default;
GRBVar GRBModel::addVar(double lb, double ub, double obj, char type, const std::string& name) {
  if (!std::isfinite(lb) || !std::isfinite(ub) || !std::isfinite(obj) || lb > ub)
    throw GRBException("invalid variable bounds or objective", 10002);
  if (type == GRB_BINARY && (lb < 0 || ub > 1))
    throw GRBException("binary bounds must lie in [0,1]", 10002);
  auto id = data_->next_id++;
  data_->vars.emplace(id, ModelData::VarRec{{id, name, lb, ub, obj, type}, true});
  if (obj != 0) data_->objective.linear.push_back({id, obj});
  invalidate(data_);
  return GRBVar(id, data_);
}
std::vector<GRBVar> GRBModel::addVars(
    int n,
    const double* lb,
    const double* ub,
    const double* obj,
    const char* type,
    const std::vector<std::string>& names) {
  std::vector<GRBVar> r;
  for (int i = 0; i < n; ++i)
    r.push_back(addVar(
        lb ? lb[i] : 0, ub ? ub[i] : GRB_INFINITY, obj ? obj[i] : 0,
        type ? type[i] : GRB_CONTINUOUS, i < (int)names.size() ? names[i] : std::string()));
  return r;
}
std::vector<GRBVar> GRBModel::getVars() const {
  std::vector<GRBVar> r;
  for (const auto& [id, v] : data_->vars) r.push_back(GRBVar(id, data_));
  return r;
}
GRBConstr GRBModel::addConstr(const GRBTempConstr& t, const std::string& name) {
  valid_constraint(data_, t);
  if (!t.expression.quadratic_.empty()) invalid("linear constraint contains quadratic terms");
  auto id = data_->next_id++;
  auto s = t;
  data_->cons.emplace(
      id, ModelData::ConRec{
              {id, name, expression(s.expression), s.sense, s.rhs, false, false, 0, 0}, true});
  invalidate(data_);
  return GRBConstr(id, data_);
}
GRBQConstr GRBModel::addQConstr(const GRBTempConstr& t, const std::string& name) {
  valid_constraint(data_, t);
  auto id = data_->next_id++;
  data_->cons.emplace(
      id, ModelData::ConRec{
              {id, name, expression(t.expression), t.sense, t.rhs, true, false, 0, 0}, true});
  invalidate(data_);
  return GRBQConstr(id, data_);
}
GRBGenConstr GRBModel::addGenConstrIndicator(
    const GRBVar& v, int value, const GRBTempConstr& t, const std::string& name) {
  require_owner(data_, v.model_);
  const auto& record = variable(data_, v.id_);
  if (record.value.type != GRB_BINARY || (value != 0 && value != 1))
    invalid("indicator requires a binary variable and trigger 0 or 1");
  valid_constraint(data_, t);
  if (!t.expression.quadratic_.empty()) invalid("indicator body must be linear");
  auto id = data_->next_id++;
  data_->cons.emplace(
      id,
      ModelData::ConRec{
          {id, name, expression(t.expression), t.sense, t.rhs, false, true, v.id_, value}, true});
  invalidate(data_);
  return GRBGenConstr(id, data_);
}
GRBGenConstr GRBModel::addGenConstrIndicator(
    const GRBVar& v,
    int value,
    const GRBLinExpr& e,
    int sense,
    double rhs,
    const std::string& name) {
  return addGenConstrIndicator(v, value, GRBTempConstr{GRBQuadExpr(e), sense, rhs}, name);
}
template <class H>
void erase(const std::shared_ptr<ModelData>& d, std::uint64_t id) {
  auto i = d->cons.find(id);
  if (i != d->cons.end()) {
    d->cons.erase(i);
    invalidate(d);
    return;
  }
  invalid("invalid constraint handle");
}
void GRBModel::remove(const GRBVar& v) {
  require_owner(data_, v.model_);
  variable(data_, v.id_);
  data_->vars.erase(v.id_);
  auto strip = [&](ExpressionSnapshot& expression) {
    auto& linear = expression.linear;
    linear.erase(
        std::remove_if(
            linear.begin(), linear.end(), [&](const auto& term) { return term.variable == v.id_; }),
        linear.end());
    auto& quadratic = expression.quadratic;
    quadratic.erase(
        std::remove_if(
            quadratic.begin(), quadratic.end(),
            [&](const auto& term) { return term.first == v.id_ || term.second == v.id_; }),
        quadratic.end());
  };
  strip(data_->objective);
  for (auto& entry : data_->cons) strip(entry.second.value.expression);
  invalidate(data_);
}
void GRBModel::remove(const GRBConstr& c) {
  require_owner(data_, c.model_);
  erase<GRBConstr>(data_, c.id_);
}
void GRBModel::remove(const GRBQConstr& c) {
  require_owner(data_, c.model_);
  erase<GRBQConstr>(data_, c.id_);
}
void GRBModel::remove(const GRBGenConstr& c) {
  require_owner(data_, c.model_);
  erase<GRBGenConstr>(data_, c.id_);
}
void GRBModel::update() {
  // Match Gurobi's batched removals: the caller may remove the binary first
  // and then its indicator handles before committing the update.
  for (auto it = data_->cons.begin(); it != data_->cons.end();) {
    const auto& constraint = it->second.value;
    if (constraint.indicator && !data_->vars.count(constraint.indicator_variable))
      it = data_->cons.erase(it);
    else
      ++it;
  }
}
void GRBModel::setObjective(const GRBQuadExpr& e, int sense) {
  valid_expression(data_, e);
  if (sense != GRB_MINIMIZE && sense != GRB_MAXIMIZE) invalid("invalid objective sense");
  data_->objective = expression(e);
  data_->objective_sense = sense;
  invalidate(data_);
}
void GRBModel::setObjective(const GRBLinExpr& e, int sense) { setObjective(GRBQuadExpr(e), sense); }
void GRBModel::set(IntParam p, int v) {
  if ((p == IntParam::Threads && v < 0) ||
      (p != IntParam::Threads && v != 0 && v != 1))
    invalid("invalid integer solver parameter");
  if (p == IntParam::OutputFlag)
    data_->params.output_flag = v;
  else if (p == IntParam::LogToConsole)
    data_->params.log_to_console = v;
  else
    data_->params.threads = v;
}
void GRBModel::set(DoubleParam, double v) {
  finite(v);
  if (v < 0) invalid("negative solver time limit");
  data_->params.time_limit = v;
}
void GRBModel::set(StringAttr, const std::string& v) { data_->name = v; }
void GRBModel::set(IntAttr, int) { invalid("integer model attribute is read-only"); }
void GRBModel::set(DoubleAttr, double) { invalid("double model attribute is read-only"); }
void GRBModel::setCallback(GRBCallback* c) { data_->callback = c; }
int GRBModel::get(IntAttr a) const {
  if (a == IntAttr::Status) return data_->status;
  if (a == IntAttr::NumVars) return static_cast<int>(data_->vars.size());
  invalid("unsupported integer model attribute");
}
double GRBModel::get(DoubleAttr a) const {
  if (!data_->solved) invalid("model has not completed the current solve");
  if (a == DoubleAttr::ObjVal) {
    if (data_->status != GRB_OPTIMAL || data_->solution_revision != data_->revision)
      invalid("no valid optimal solution");
    return data_->objval;
  }
  if (a == DoubleAttr::Runtime) return data_->runtime_seconds;
  invalid("unsupported double model attribute");
}
ModelSnapshot GRBModel::snapshot() const {
  ModelSnapshot s;
  s.name = data_->name;
  s.revision = data_->revision;
  s.objective = data_->objective;
  s.objective_sense = data_->objective_sense;
  for (const auto& [id, v] : data_->vars) s.variables.push_back(v.value);
  for (const auto& [id, c] : data_->cons) s.constraints.push_back(c.value);
  return s;
}
void GRBModel::optimize() {
  invalidate(data_);
  update();
  if (!data_->runtime) throw GRBException("no AMPL runtime configured", 10003);
  if (data_->callback) {
    data_->callback->resetAbort();
    data_->callback->callback();
  }
  auto result = data_->runtime->solve(snapshot(), data_->callback, data_->params);
  if (result.status == GRB_OPTIMAL) {
    for (const auto& entry : data_->vars) {
      auto found = result.values.find(entry.first);
      if (found == result.values.end()) invalid("optimal solution missing variable");
      finite(found->second);
    }
    finite(result.objective);
    data_->solution = std::move(result.values);
    data_->solution_revision = data_->revision;
  }
  data_->status = result.status;
  data_->objval = result.objective;
  data_->runtime_seconds = result.runtime;
  data_->solved = true;
}
void exportAmplModel(const ModelSnapshot& s, const std::string& path) {
  std::ofstream out(path);
  if (!out) throw GRBException("cannot open model export", 10004);
  out << std::setprecision(std::numeric_limits<double>::max_digits10) << "# sando_ampl model "
      << s.name << "\n";
  for (const auto& v : s.variables) {
    out << "var v_" << v.id;
    if (v.type == GRB_BINARY)
      out << " binary";
    else if (v.type == GRB_INTEGER)
      out << " integer";
    out << " >= " << v.lb << " <= " << v.ub << ";\n";
  }
  auto write_expr = [&](const ExpressionSnapshot& e) {
    out << e.constant;
    for (const auto& t : e.linear) out << " + (" << t.coefficient << ") * v_" << t.variable;
    for (const auto& t : e.quadratic)
      out << " + (" << t.coefficient << ") * v_" << t.first << " * v_" << t.second;
  };
  for (const auto& c : s.constraints) {
    out << "subject to c_" << c.id << ": ";
    if (c.indicator) out << "v_" << c.indicator_variable << " = " << c.indicator_value << " ==> ";
    write_expr(c.expression);
    out << (c.sense == GRB_LESS_EQUAL      ? " <= "
            : c.sense == GRB_GREATER_EQUAL ? " >= "
                                           : " = ")
        << c.rhs << ";\n";
  }
  out << (s.objective_sense == GRB_MAXIMIZE ? "maximize" : "minimize") << " objective: ";
  write_expr(s.objective);
  out << ";\n";
  out.close();
  if (!out) throw GRBException("cannot finish model export", 10004);
}
void GRBModel::exportModel(const std::string& path) const { exportAmplModel(snapshot(), path); }
}  // namespace sando_ampl
