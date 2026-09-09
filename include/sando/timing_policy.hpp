#pragma once

#include <Eigen/Core>
#include <nlohmann/json.hpp>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace sando_learning {

/** Strict portable inference for the stage-5 scalar factor policy. */
class TimingPolicy {
 public:
  explicit TimingPolicy(const std::string& path) { load(path); }

  bool valid() const noexcept { return valid_; }
  const std::string& path() const noexcept { return path_; }
  const std::string& type() const noexcept { return type_; }
  int nfe() const noexcept { return nfe_; }
  void setNfe(int value) { if ((type_ == "flow" && value != 1 && value != 4 && value != 8) || (type_ == "regression" && value != 1)) throw std::invalid_argument("invalid timing nfe"); nfe_ = value; }

  std::vector<double> predict(const Eigen::Vector3d& delta, const Eigen::Vector3d& v0,
                              const Eigen::Vector3d& a0, const Eigen::Vector3d& vf,
                              const Eigen::Vector3d& af, double initial_dt, double dc) const {
    if (!valid_) throw std::runtime_error("timing policy is invalid");
    std::vector<double> x;
    x.reserve(17);
    for (double z : delta) x.push_back(z);
    for (double z : v0) x.push_back(z);
    for (double z : a0) x.push_back(z);
    for (double z : vf) x.push_back(z);
    for (double z : af) x.push_back(z);
    x.push_back(initial_dt); x.push_back(dc);
    for (double z : x) if (!std::isfinite(z)) throw std::runtime_error("non-finite timing feature");
    for (size_t i=0;i<x.size();++i) x[i]=(x[i]-normalizer_mean_[i])/normalizer_std_[i];
    std::vector<double> result;
    const double regression_mean = type_ == "regression" ? apply_net(x).front() : 0.0;
    for (double latent : {-1.0, 0.0, 1.0}) {
      double state = latent;
      if (type_ == "regression") state = regression_mean + residual_std_ * latent;
      else for (int step = 0; step < nfe_; ++step) {
        std::vector<double> input = x; input.push_back(state);
        input.push_back(step / static_cast<double>(nfe_));
        state += apply_net(input).front() / static_cast<double>(nfe_);
      }
      if (!std::isfinite(state)) throw std::runtime_error("non-finite timing prediction");
      result.push_back(std::clamp(state, log_min_, log_max_));
    }
    return result;
  }

  std::vector<double> apply_net(const std::vector<double>& x) const {
    std::vector<double> y=x;
    for (size_t i=0;i<layers_.size();++i) { y=layers_[i].apply(y); if(i+1<layers_.size()) for(double& v:y)v=std::tanh(v); }
    return y;
  }

 private:
  struct Layer {
    Eigen::MatrixXd weight;
    Eigen::VectorXd bias;
    std::vector<double> apply(const std::vector<double>& x) const {
      if (weight.cols() != static_cast<int>(x.size())) throw std::runtime_error("timing model input dimension mismatch");
      Eigen::VectorXd v(weight.cols()); for (int i=0;i<v.size();++i) v[i]=x[static_cast<size_t>(i)];
      Eigen::VectorXd y = weight*v + bias;
      if (!y.allFinite()) throw std::runtime_error("non-finite timing model output");
      return std::vector<double>(y.data(), y.data()+y.size());
    }
  };
  void load(const std::string& path) {
    path_ = path; std::ifstream stream(path); if (!stream) throw std::invalid_argument("cannot open timing policy");
    nlohmann::json j; stream >> j;
    if (j.value("schema_version", 0) != 1 || !j.contains("type") || !j.contains("feature_spec") ||
        !j.contains("mean") || !j.contains("std") || !j.contains("weights")) throw std::invalid_argument("invalid timing policy schema");
    type_ = j.at("type").get<std::string>(); if (type_ != "regression" && type_ != "flow") throw std::invalid_argument("invalid timing policy type");
    if (j.at("feature_spec") != nlohmann::json::array({"goal_position_delta","start_velocity","start_acceleration","goal_velocity","goal_acceleration","initial_dt","dc"})) throw std::invalid_argument("invalid timing feature specification");
    auto mean=j.at("mean").get<std::vector<double>>(), sd=j.at("std").get<std::vector<double>>(); if(mean.size()!=17||sd.size()!=17) throw std::invalid_argument("invalid timing normalizer");
    for(size_t i=0;i<17;++i) { if(!std::isfinite(mean[i])||!std::isfinite(sd[i])||sd[i]<=0) throw std::invalid_argument("invalid timing normalizer"); normalizer_mean_[i]=mean[i]; normalizer_std_[i]=sd[i]; }
    auto w=j.at("weights"); if(!w.is_array()||w.size()!=6) throw std::invalid_argument("invalid timing weights");
    const int input_dim = type_ == "regression" ? 17 : 19;
    const int expected_in[3] = {input_dim, 64, 64};
    const int expected_out[3] = {64, 64, 1};
    for(size_t i=0;i<6;i+=2) { auto a=w[i].get<std::vector<std::vector<double>>>(); auto b=w[i+1].get<std::vector<double>>(); const size_t layer_index=i/2; if(a.size()!=static_cast<size_t>(expected_out[layer_index])||b.size()!=a.size()) throw std::invalid_argument("invalid timing layer dimensions"); if(a.front().size()!=static_cast<size_t>(expected_in[layer_index])) throw std::invalid_argument("invalid timing layer dimensions"); Layer l; l.weight.resize(a.size(),a.front().size()); l.bias=Eigen::Map<Eigen::VectorXd>(b.data(),b.size()); for(size_t r=0;r<a.size();++r){if(a[r].size()!=a.front().size())throw std::invalid_argument("invalid timing layer");for(size_t c=0;c<a[r].size();++c){if(!std::isfinite(a[r][c]))throw std::invalid_argument("non-finite timing weight");l.weight(r,c)=a[r][c];} if(!std::isfinite(b[r]))throw std::invalid_argument("non-finite timing bias");} layers_.push_back(std::move(l)); }
    nfe_=j.value("nfe",1); setNfe(nfe_); if(!j.contains("logfactor_bounds") || j.at("logfactor_bounds") != nlohmann::json::array({0.0,std::log(5.0)})) throw std::invalid_argument("invalid timing log bounds"); if(!j.contains("latent_quantiles") || j.at("latent_quantiles") != nlohmann::json::array({-1.0,0.0,1.0})) throw std::invalid_argument("invalid timing quantiles"); residual_std_=j.value("residual_std",0.0); if(!std::isfinite(residual_std_)||residual_std_<0)throw std::invalid_argument("invalid timing residual"); valid_=true;
  }
  std::string path_, type_; bool valid_{false}; int nfe_{1}; double residual_std_{0}; double log_min_{0},log_max_{std::log(5.0)}; double normalizer_mean_[17]{},normalizer_std_[17]{}; std::vector<Layer> layers_;
};
}
