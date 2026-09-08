#pragma once

#include <algorithm>
#include <cmath>
#include <stdexcept>

namespace sando_time {

inline double segmentDuration(double initial_dt, double dc, double factor) {
  if (!std::isfinite(initial_dt) || initial_dt < 0.0 || !std::isfinite(dc) || dc <= 0.0 ||
      !std::isfinite(factor) || factor <= 0.0)
    throw std::invalid_argument("invalid segment time inputs");
  const double dt = std::max(initial_dt, 2.0 * dc) * factor;
  if (!std::isfinite(dt) || dt <= 0.0)
    throw std::invalid_argument("invalid actual segment duration");
  return dt;
}

}  // namespace sando_time
