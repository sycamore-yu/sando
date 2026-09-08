#pragma once

#include <sando/ampl_model.hpp>

namespace sando_ampl::detail {

struct CenteredModel {
  ModelSnapshot snapshot;
  std::map<std::uint64_t, double> offsets;
};

CenteredModel centerContinuousObjective(const ModelSnapshot& original);

}  // namespace sando_ampl::detail
