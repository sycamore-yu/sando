#include "sando/timing_policy.hpp"

#include <cassert>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>

static int parity_main(const char* model_path, const char* feature_path) {
  std::ifstream stream(feature_path);
  if (!stream) throw std::runtime_error("cannot open feature JSON");
  nlohmann::json j; stream >> j;
  std::vector<double> x;
  if (j.is_array()) x = j.get<std::vector<double>>();
  else {
    auto start = j.at("start").get<std::vector<double>>();
    auto goal = j.at("goal").get<std::vector<double>>();
    if (start.size() != 9 || goal.size() != 9) throw std::runtime_error("start/goal must have 9 values");
    for (int i = 0; i < 3; ++i) x.push_back(goal[i] - start[i]);
    x.insert(x.end(), start.begin() + 3, start.end());
    x.insert(x.end(), goal.begin() + 3, goal.end());
    x.push_back(j.at("initial_dt").get<double>());
    x.push_back(j.at("dc").get<double>());
  }
  if (x.size() != 17) throw std::runtime_error("features must have 17 values");
  sando_learning::TimingPolicy policy(model_path);
  auto logs = policy.predict(Eigen::Vector3d(x[0], x[1], x[2]),
                             Eigen::Vector3d(x[3], x[4], x[5]),
                             Eigen::Vector3d(x[6], x[7], x[8]),
                             Eigen::Vector3d(x[9], x[10], x[11]),
                             Eigen::Vector3d(x[12], x[13], x[14]), x[15], x[16]);
  std::cout << nlohmann::json(logs).dump() << '\n';
  return 0;
}

int main(int argc, char** argv) {
  if (argc == 3) {
    try { return parity_main(argv[1], argv[2]); }
    catch (const std::exception& error) { std::cerr << error.what() << '\n'; return 2; }
  }
  if (argc != 1) return 2;
  const char* path = "/tmp/sando_timing_policy_test.json";
  nlohmann::json weights = nlohmann::json::array();
  auto layer = [](int out, int in, double value) {
    nlohmann::json w = nlohmann::json::array();
    for (int r=0;r<out;++r) { nlohmann::json row=nlohmann::json::array(); for(int c=0;c<in;++c) row.push_back(r==0&&c==0?value:0.0); w.push_back(row); }
    return w;
  };
  weights.push_back(layer(64,17,0.0)); weights.push_back(std::vector<double>(64,0.0));
  weights.push_back(layer(64,64,0.0)); weights.push_back(std::vector<double>(64,0.0));
  weights.push_back(layer(1,64,0.0)); weights.push_back(std::vector<double>{0.0});
  nlohmann::json model={{"schema_version",1},{"type","regression"},{"feature_spec",{"goal_position_delta","start_velocity","start_acceleration","goal_velocity","goal_acceleration","initial_dt","dc"}},{"mean",std::vector<double>(17,0.0)},{"std",std::vector<double>(17,1.0)},{"logfactor_bounds",{0.0,1.6094379124341003}},{"latent_quantiles",{-1.0,0.0,1.0}},{"residual_std",0.0},{"nfe",1},{"weights",weights}};
  std::ofstream(path) << model.dump();
  sando_learning::TimingPolicy policy(path);
  auto out=policy.predict(Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),1.0,0.01);
  assert(out.size()==3); for(double x:out) assert(x==0.0); assert(policy.proposalCount()==3);
  bool failed=false;
  try { policy.predict(Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),std::numeric_limits<double>::quiet_NaN(),0.01); }
  catch (const std::runtime_error&) { failed=true; }
  assert(failed);
  failed=false;
  try { policy.predict(Eigen::Vector3d(std::numeric_limits<double>::infinity(),0,0),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),1.0,0.01); }
  catch (const std::runtime_error&) { failed=true; }
  assert(failed);
  auto expect_invalid=[&](nlohmann::json bad){
    std::ofstream(path)<<bad.dump();
    bool threw=false;
    try { sando_learning::TimingPolicy p(path); }
    catch (const std::invalid_argument&) { threw=true; }
    assert(threw);
  };
  nlohmann::json bad=model; bad["mean"]=std::vector<double>(16,0.0); expect_invalid(bad);
  bad=model; bad["schema_version"]=99; expect_invalid(bad);
  bad=model; bad["logfactor_bounds"]=nlohmann::json::array({0.0,std::log(2.5)}); expect_invalid(bad);
  bad=model; bad["latent_quantiles"]=nlohmann::json::array({0.0}); expect_invalid(bad);
  nlohmann::json v2=model;
  v2["schema_version"]=2; v2["output_mode"]="single"; v2["proposal_count"]=1;
  v2["logfactor_bounds"]=nlohmann::json::array({0.0,std::log(2.5)});
  v2["latent_quantiles"]=nlohmann::json::array({0.0});
  std::ofstream(path)<<v2.dump();
  sando_learning::TimingPolicy single(path);
  auto one=single.predict(Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),1.0,0.01);
  assert(single.proposalCount()==1); assert(one.size()==1); assert(one[0]==0.0);
  nlohmann::json clamped=v2; clamped["weights"][5]=std::vector<double>{10.0};
  std::ofstream(path)<<clamped.dump();
  sando_learning::TimingPolicy high(path);
  auto hi=high.predict(Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),Eigen::Vector3d::Zero(),1.0,0.01);
  assert(hi.size()==1); assert(hi[0]>=0.0); assert(hi[0]<=std::log(2.5));
  assert(std::abs(hi[0]-std::log(2.5))<1e-15);
  bad=v2; bad.erase("output_mode"); expect_invalid(bad);
  bad=v2; bad["output_mode"]="three"; expect_invalid(bad);
  bad=v2; bad["proposal_count"]=3; expect_invalid(bad);
  bad=v2; bad["logfactor_bounds"]=nlohmann::json::array({0.0,std::log(5.0)}); expect_invalid(bad);
  bad=v2; bad["latent_quantiles"]=nlohmann::json::array({-1.0,0.0,1.0}); expect_invalid(bad);
  std::remove(path); return 0;
}
