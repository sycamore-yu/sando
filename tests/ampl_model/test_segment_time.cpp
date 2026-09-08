#include <sando/segment_time.hpp>

#include <array>
#include <cassert>
#include <cmath>
#include <limits>

int main() {
  using sando_time::segmentDuration;
  assert(segmentDuration(1.0, 0.01, 1.5) == 1.5);
  assert(std::abs(segmentDuration(0.001, 0.01, 1.5) - 0.03) < 1e-15);
  assert(segmentDuration(0.0, 1.0, 2.0) == 4.0);
  for (double bad : {-1.0, std::numeric_limits<double>::infinity(),
                     std::numeric_limits<double>::quiet_NaN()}) {
    bool failed = false;
    try { segmentDuration(bad, 0.01, 1.0); }
    catch (const std::invalid_argument&) { failed = true; }
    assert(failed);
  }
  for (auto input : {std::array<double, 3>{1.0, 0.0, 1.0},
                     std::array<double, 3>{1.0, 0.01, 0.0},
                     std::array<double, 3>{1e308, 0.01, 2.0}}) {
    bool failed = false;
    try { segmentDuration(input[0], input[1], input[2]); }
    catch (const std::invalid_argument&) { failed = true; }
    assert(failed);
  }
}
