cmake_minimum_required(VERSION 3.16)
project(ampls_real_preflight LANGUAGES CXX)

set(AMPLS_ROOT "/tmp/sando-ampls-api" CACHE PATH "Official AMPLS source checkout")
set(AMPLS_LIB_DIR "${AMPLS_ROOT}/libs/ampls/linux64" CACHE PATH "Directory containing libgurobi-lib.so")
set(GUROBI_ROOT "" CACHE PATH "Gurobi installation or extracted AMPLS solver bundle")
set(GUROBI_LIB_DIR "" CACHE PATH "Directory containing libgurobi*.so")
set(AMPL_EXECUTABLE "" CACHE FILEPATH "AMPL executable used to export the test models")

if(NOT AMPL_EXECUTABLE)
  find_program(AMPL_EXECUTABLE NAMES ampl)
endif()
if(NOT AMPL_EXECUTABLE)
  message(FATAL_ERROR "AMPL_EXECUTABLE is required to export the real AMPL models")
endif()

if(NOT GUROBI_LIB_DIR)
  if(GUROBI_ROOT)
    set(GUROBI_LIB_DIR "${GUROBI_ROOT}/lib/linux64")
  else()
    set(GUROBI_LIB_DIR "${AMPLS_ROOT}/libs/gurobi/lib/linux64")
  endif()
endif()

find_file(AMPLS_GUROBI_DRIVER
  NAMES libgurobi-lib.so gurobi-lib
  PATHS "${AMPLS_LIB_DIR}" NO_DEFAULT_PATH REQUIRED)
find_file(GUROBI_LIBRARY
  NAMES libgurobi130.so libgurobi120.so libgurobi110.so libgurobi.so
  PATHS "${GUROBI_LIB_DIR}" "${GUROBI_ROOT}/lib/linux64"
        "${GUROBI_ROOT}/linux64/lib" "${GUROBI_ROOT}/lib" "${GUROBI_ROOT}"
  NO_DEFAULT_PATH REQUIRED)
find_path(GUROBI_INCLUDE_DIR gurobi_c.h
  PATHS "${GUROBI_ROOT}/include" "${GUROBI_ROOT}/include/gurobi"
        "${GUROBI_ROOT}/linux64/include" "${GUROBI_ROOT}"
  NO_DEFAULT_PATH REQUIRED)

find_package(Threads REQUIRED)

set(AMPLS_SOURCE_DIR "${AMPLS_ROOT}/cpp/ampls")
set(GUROBI_SOURCE_DIR "${AMPLS_ROOT}/cpp/gurobi")
add_executable(ampls_real_preflight
  preflight.cpp
  "${AMPLS_SOURCE_DIR}/src/ampls.cpp"
  "${AMPLS_SOURCE_DIR}/src/csvReader.cpp"
  "${GUROBI_SOURCE_DIR}/src/gurobi_interface.cpp"
  "${GUROBI_SOURCE_DIR}/src/gurobi_callback.cpp")
target_include_directories(ampls_real_preflight PRIVATE
  "${AMPLS_SOURCE_DIR}/include"
  "${GUROBI_SOURCE_DIR}/include"
  "${GUROBI_INCLUDE_DIR}")
target_compile_features(ampls_real_preflight PRIVATE cxx_std_17)
target_link_libraries(ampls_real_preflight PRIVATE
  "${AMPLS_GUROBI_DRIVER}" "${GUROBI_LIBRARY}" Threads::Threads ${CMAKE_DL_LIBS})
set_target_properties(ampls_real_preflight PROPERTIES
  BUILD_RPATH "${AMPLS_LIB_DIR};${GUROBI_LIB_DIR}")

configure_file(preflight.mod "${CMAKE_CURRENT_BINARY_DIR}/preflight.mod" COPYONLY)
configure_file(preflight.run "${CMAKE_CURRENT_BINARY_DIR}/preflight.run" COPYONLY)
configure_file(interrupt.mod "${CMAKE_CURRENT_BINARY_DIR}/interrupt.mod" COPYONLY)
configure_file(interrupt.run "${CMAKE_CURRENT_BINARY_DIR}/interrupt.run" COPYONLY)

set(MODEL_OUTPUTS
  "${CMAKE_CURRENT_BINARY_DIR}/preflight.nl"
  "${CMAKE_CURRENT_BINARY_DIR}/preflight.col"
  "${CMAKE_CURRENT_BINARY_DIR}/preflight.row"
  "${CMAKE_CURRENT_BINARY_DIR}/interrupt.nl"
  "${CMAKE_CURRENT_BINARY_DIR}/interrupt.col"
  "${CMAKE_CURRENT_BINARY_DIR}/interrupt.row")
add_custom_command(OUTPUT ${MODEL_OUTPUTS}
  COMMAND "${AMPL_EXECUTABLE}" preflight.run
  COMMAND "${AMPL_EXECUTABLE}" interrupt.run
  WORKING_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
  DEPENDS preflight.mod preflight.run interrupt.mod interrupt.run
  COMMENT "Exporting real AMPLS preflight models")
add_custom_target(ampls_real_preflight_models DEPENDS ${MODEL_OUTPUTS})
add_dependencies(ampls_real_preflight ampls_real_preflight_models)

enable_testing()
add_test(NAME ampls_real_preflight
  COMMAND ampls_real_preflight
    "${CMAKE_CURRENT_BINARY_DIR}/preflight.nl"
    "${CMAKE_CURRENT_BINARY_DIR}/interrupt.nl")
