# AMPLS real-model preflight

This is a standalone C++ smoke test for the public AMPLS/Gurobi interface. It
exports the two real AMPL models, loads the generated `.nl`/`.row`/`.col`
files, checks native Gurobi status and AMPL name mappings, runs nine independent
instances in parallel for nine rounds, and verifies callback interruption,
zero-time-limit status, and a fresh successful solve.

The test uses the official AMPLS source checkout and the AMPL-distributed
Gurobi driver and Gurobi C library. No model is solved by AMPL itself.

```sh
cmake -S tests/ampls -B build/ampls \
  -DAMPLS_ROOT=/path/to/ampls \
  -DAMPLS_LIB_DIR=/path/to/ampls/libs/ampls/linux64 \
  -DGUROBI_ROOT=/path/to/gurobi \
  -DAMPL_EXECUTABLE=/path/to/ampl
cmake --build build/ampls --target ampls_real_preflight -j2
ctest --test-dir build/ampls --output-on-failure
```

If the solver bundle has a different layout, pass `-DGUROBI_LIB_DIR=...` and
`-DGUROBI_INCLUDE_DIR=...` through the normal CMake toolchain or adjust the
corresponding cache paths in `CMakeLists.txt`.
