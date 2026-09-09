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

inline double baseDuration(double initial_dt, double dc) {
  return segmentDuration(initial_dt, dc, 1.0);
}

inline double horizonDuration(int n, double initial_dt, double dc, double factor) {
  if (n <= 0) throw std::invalid_argument("invalid segment count");
  return static_cast<double>(n) * segmentDuration(initial_dt, dc, factor);
}

}  // namespace sando_time
