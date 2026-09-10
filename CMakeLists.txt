cmake_minimum_required(VERSION 3.8)
project(sando)

# Set C++ standard to C++17 (required for std::scoped_lock)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

# Performance optimization flags
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -march=native -DNDEBUG")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -ffast-math -funroll-loops")
# Link-time optimization for better cross-TU optimization
set(CMAKE_INTERPROCEDURAL_OPTIMIZATION TRUE)

# avoid Found-related error (ref: https://stackoverflow.com/questions/18327197/opencv-is-considered-to-be-not-found)
set(decomp_rviz_plugins_FOUND 1)

# find dependencies
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(gazebo REQUIRED) # Note: if you put this line later on, it gives an error
find_package(rclcpp REQUIRED)
find_package(rclpy REQUIRED)
find_package(rclcpp_components REQUIRED)
find_package(example_interfaces REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(Eigen3 REQUIRED)
find_package(decomp_util REQUIRED)
find_package(decomp_ros_msgs REQUIRED)
find_package(decomp_rviz_plugins REQUIRED)
find_package(decomp_test_node REQUIRED)
find_package(PCL REQUIRED)
find_package(pcl_conversions REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(dynus_interfaces REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(gazebo_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(gazebo_ros REQUIRED)
find_package(tf2_geometry_msgs REQUIRED)
find_package(tf2_eigen REQUIRED)
find_package(std_srvs REQUIRED)
find_package(pcl_ros REQUIRED)
find_package(nlohmann_json REQUIRED)

# Solver backend
option(SANDO_USE_AMPL "Use real AMPL models and AMPLS Gurobi" OFF)
if(SANDO_USE_AMPL)
  add_compile_definitions(SANDO_USE_AMPL=1)
  set(AMPLS_ROOT "/opt/ampls-api" CACHE PATH "Matching AMPLS sources and solver library bundle")
  set(AMPLS_DRIVER_DIR "${AMPLS_ROOT}/libs/ampls/linux64")
  set(AMPLS_GUROBI_DIR "${AMPLS_ROOT}/libs/gurobi/lib/linux64")
  set(GUROBI_INCLUDE_DIRS "${AMPLS_ROOT}/libs/gurobi/include")
  find_library(AMPLS_DRIVER NAMES gurobi-lib PATHS "${AMPLS_DRIVER_DIR}" NO_DEFAULT_PATH REQUIRED)
  find_library(AMPLS_GUROBI NAMES gurobi130 PATHS "${AMPLS_GUROBI_DIR}" NO_DEFAULT_PATH REQUIRED)
  find_package(Threads REQUIRED)
  add_library(sando_ampl_backend STATIC
    src/sando/ampl_model.cpp src/sando/ampl_centering.cpp src/sando/ampls_runtime.cpp src/sando/planning_instance.cpp
    src/sando/instance_reservoir.cpp src/sando/frozen_planning_observation.cpp src/sando/corridor_policy.cpp
    "${AMPLS_ROOT}/cpp/ampls/src/ampls.cpp"
    "${AMPLS_ROOT}/cpp/ampls/src/csvReader.cpp"
    "${AMPLS_ROOT}/cpp/gurobi/src/gurobi_interface.cpp"
    "${AMPLS_ROOT}/cpp/gurobi/src/gurobi_callback.cpp")
  target_include_directories(sando_ampl_backend PUBLIC
    "${CMAKE_CURRENT_SOURCE_DIR}/include" "${AMPLS_ROOT}/libs/gurobi/include"
    PRIVATE "${AMPLS_ROOT}/cpp/ampls/include" "${AMPLS_ROOT}/cpp/gurobi/include")
  target_compile_definitions(sando_ampl_backend PUBLIC SANDO_USE_AMPL=1)
  target_compile_options(sando_ampl_backend PRIVATE -fno-fast-math)
  target_link_libraries(sando_ampl_backend PUBLIC "${AMPLS_DRIVER}" "${AMPLS_GUROBI}" Threads::Threads ${CMAKE_DL_LIBS} nlohmann_json::nlohmann_json Eigen3::Eigen)
  set(CMAKE_INSTALL_RPATH "${AMPLS_DRIVER_DIR};${AMPLS_GUROBI_DIR}")
  set(GUROBI_LIBRARIES sando_ampl_backend)
  add_executable(label_planning_instances src/sando/label_planning_instances.cpp)
  target_link_libraries(label_planning_instances sando_ampl_backend)
  target_compile_options(label_planning_instances PRIVATE -fno-fast-math)
  install(TARGETS label_planning_instances DESTINATION lib/${PROJECT_NAME})
  add_executable(replay_integer_planning src/sando/replay_integer_planning.cpp)
  target_link_libraries(replay_integer_planning sando_ampl_backend)
  target_compile_options(replay_integer_planning PRIVATE -fno-fast-math)
  install(TARGETS replay_integer_planning DESTINATION lib/${PROJECT_NAME})
  add_executable(corridor_policy_probe tests/ampls/corridor_policy_probe.cpp)
  target_link_libraries(corridor_policy_probe sando_ampl_backend)
  target_compile_options(corridor_policy_probe PRIVATE -fno-fast-math)
  install(TARGETS corridor_policy_probe DESTINATION lib/${PROJECT_NAME})
else()
# Native Gurobi reference backend
list(APPEND CMAKE_MODULE_PATH "${CMAKE_SOURCE_DIR}")
find_package(GUROBI REQUIRED)

# check if gurobi is found
if(GUROBI_FOUND)
message(STATUS "GUROBI FOUND")
else(GUROBI_FOUND)
message(FATAL_ERROR "GUROBI NOT FOUND!")
endif(GUROBI_FOUND)
FILE(GLOB GurobiSOFiles $ENV{GUROBI_HOME}/lib/libgurobi*[0-9].so)
set(GUROBI_LIBRARIES "$ENV{GUROBI_HOME}/lib/libgurobi_c++.a;${GurobiSOFiles};$ENV{GUROBI_HOME}/lib/")
endif()

list(APPEND CMAKE_MODULE_PATH "${CMAKE_SOURCE_DIR}")

# OpenMP
find_package(OpenMP REQUIRED)
if (OPENMP_FOUND)
    set (CMAKE_C_FLAGS "${CMAKE_C_FLAGS} ${OpenMP_C_FLAGS}")
    set (CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} ${OpenMP_CXX_FLAGS}")
    set (CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS} ${OpenMP_EXE_LINKER_FLAGS}")
endif()

# include directories
include_directories(${EIGEN3_INCLUDE_DIR} ${PCL_INCLUDE_DIRS} ${DECOMP_UTIL_INCLUDE_DIRS} ${GAZEBO_INCLUDE_DIRS} ${GUROBI_INCLUDE_DIRS} include)
link_directories(${PCL_LIBRARY_DIRS} ${BOOST_LIBRARY_DIRS} ${GAZEBO_LIBRARY_DIRS})
add_definitions(${PCL_DEFINITIONS})

# add executables
add_library(sando_planner STATIC src/sando/sando.cpp src/hgp/hgp_manager.cpp src/hgp/utils.cpp src/hgp/hgp_planner.cpp src/hgp/graph_search.cpp src/sando/utils.cpp src/sando/gurobi_solver.cpp)
# Nonfinite input checks must remain effective in every comparison group.
target_compile_options(sando_planner PRIVATE -fno-fast-math)
target_link_libraries(sando_planner ${GUROBI_LIBRARIES} ${PCL_LIBRARIES})
ament_target_dependencies(sando_planner rclcpp example_interfaces dynus_interfaces visualization_msgs Eigen3 decomp_ros_msgs sensor_msgs std_msgs decomp_rviz_plugins decomp_test_node tf2_geometry_msgs tf2 tf2_ros tf2_eigen std_srvs pcl_ros)
if(SANDO_USE_AMPL)
  target_sources(sando_planner PRIVATE src/sando/reconstruct_planning_request.cpp)
  add_executable(reconstruct_planning_request src/sando/reconstruct_planning_request_main.cpp)
  target_link_libraries(reconstruct_planning_request sando_planner)
  target_compile_options(reconstruct_planning_request PRIVATE -fno-fast-math)
  ament_target_dependencies(reconstruct_planning_request rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  install(TARGETS reconstruct_planning_request DESTINATION lib/${PROJECT_NAME})
endif()
add_executable(sando src/sando/sando_node.cpp)
target_link_libraries(sando sando_planner)
ament_target_dependencies(sando rclcpp example_interfaces dynus_interfaces visualization_msgs Eigen3 decomp_ros_msgs sensor_msgs std_msgs decomp_rviz_plugins decomp_test_node tf2_geometry_msgs tf2 tf2_ros tf2_eigen std_srvs pcl_ros)

# Add the fake_sim executable
add_executable(fake_sim src/sando/fake_sim.cpp)
target_link_libraries(fake_sim)
ament_target_dependencies(fake_sim rclcpp rclcpp_components visualization_msgs dynus_interfaces sensor_msgs gazebo_msgs sensor_msgs tf2 tf2_ros nav_msgs)

# Add the obstacle tracker
add_executable(obstacle_tracker_node src/sando/obstacle_tracker_node.cpp src/hgp/utils.cpp src/sando/utils.cpp)
target_link_libraries(obstacle_tracker_node ${PCL_LIBRARIES})
ament_target_dependencies(obstacle_tracker_node rclcpp rclcpp_components visualization_msgs Eigen3 dynus_interfaces std_msgs gazebo_msgs sensor_msgs tf2 tf2_ros pcl_conversions tf2_geometry_msgs tf2_eigen)

# Add goal to cmd_vel converter
add_executable(convert_goal_to_cmd_vel src/sando/convert_goal_to_cmd_vel.cpp)
target_link_libraries(convert_goal_to_cmd_vel)
ament_target_dependencies(convert_goal_to_cmd_vel rclcpp example_interfaces dynus_interfaces visualization_msgs Eigen3 sensor_msgs std_msgs decomp_rviz_plugins decomp_test_node tf2_geometry_msgs tf2 tf2_ros tf2_eigen)

# Add odom to state converter
add_executable(convert_odom_to_state src/sando/convert_odom_to_state.cpp)
target_link_libraries(convert_odom_to_state)
ament_target_dependencies(convert_odom_to_state rclcpp example_interfaces dynus_interfaces visualization_msgs Eigen3 sensor_msgs std_msgs decomp_rviz_plugins decomp_test_node tf2_geometry_msgs tf2 tf2_ros tf2_eigen)

# Add odom to global state converter (local->global frame via TF2)
add_executable(odom_to_global_state src/sando/odom_to_global_state.cpp)
target_link_libraries(odom_to_global_state)
ament_target_dependencies(odom_to_global_state rclcpp dynus_interfaces Eigen3 tf2 tf2_ros nav_msgs geometry_msgs)

# Add vicon to state converter
add_executable(convert_vicon_to_state src/sando/convert_vicon_to_state.cpp)
target_link_libraries(convert_vicon_to_state)
ament_target_dependencies(convert_vicon_to_state rclcpp example_interfaces dynus_interfaces visualization_msgs Eigen3 decomp_ros_msgs sensor_msgs std_msgs decomp_rviz_plugins decomp_test_node tf2_geometry_msgs tf2 tf2_ros tf2_eigen)

# Add the convert velodyne executable
add_executable(convert_velodyne_to_ros_time src/sando/convert_velodyne_to_ros_time.cpp)
target_link_libraries(convert_velodyne_to_ros_time)
ament_target_dependencies(convert_velodyne_to_ros_time rclcpp rclcpp_components visualization_msgs dynus_interfaces sensor_msgs gazebo_msgs sensor_msgs tf2 tf2_ros nav_msgs)

# For dynamic obstacles in Gazebo (per-model plugin, legacy)
add_library(move_model SHARED src/sim/move_model.cpp)
target_link_libraries(move_model ${GAZEBO_LIBRARIES})
ament_target_dependencies(move_model rclcpp tf2 tf2_ros geometry_msgs)

# World plugin: single plugin manages ALL dynamic obstacles (replaces N move_model instances)
add_library(dynamic_obstacles_world_plugin SHARED src/sim/dynamic_obstacles_world_plugin.cpp)
target_link_libraries(dynamic_obstacles_world_plugin ${GAZEBO_LIBRARIES})
ament_target_dependencies(dynamic_obstacles_world_plugin)

# For gazebo plugins (IMU)
add_library(imu_plugin SHARED src/sim/gazebo_ros_imu_sensor.cpp)
target_link_libraries(imu_plugin ${GAZEBO_LIBRARIES})
ament_target_dependencies(imu_plugin sensor_msgs gazebo_ros)

# For dynamic forest node
add_executable(dynamic_forest_node src/sim/dynamic_forest_node.cpp)
ament_target_dependencies(dynamic_forest_node
  rclcpp
  geometry_msgs
  gazebo_msgs
  visualization_msgs
  std_msgs
  tf2_ros
  dynus_interfaces
)

# For benchmark SFC generation
add_executable(corridor_generator_node src/sando/corridor_generator_node.cpp src/hgp/hgp_manager.cpp src/hgp/utils.cpp src/hgp/hgp_planner.cpp src/hgp/graph_search.cpp src/sando/utils.cpp
)
target_link_libraries(corridor_generator_node ${GUROBI_LIBRARIES} ${PCL_LIBRARIES})
ament_target_dependencies(corridor_generator_node rclcpp example_interfaces dynus_interfaces visualization_msgs Eigen3 decomp_ros_msgs sensor_msgs std_msgs decomp_rviz_plugins decomp_test_node tf2_geometry_msgs tf2 tf2_ros tf2_eigen std_srvs pcl_ros)

add_executable(local_traj_benchmark_node src/sando/local_traj_benchmark.cpp)
target_link_libraries(local_traj_benchmark_node sando_planner)
ament_target_dependencies(local_traj_benchmark_node rclcpp example_interfaces dynus_interfaces visualization_msgs Eigen3 decomp_ros_msgs sensor_msgs std_msgs decomp_rviz_plugins decomp_test_node tf2_geometry_msgs tf2 tf2_ros tf2_eigen std_srvs pcl_ros)

add_executable(visualize_local_trajs_node src/sando/visualize_local_trajs.cpp)
target_link_libraries(visualize_local_trajs_node sando_planner)
ament_target_dependencies(visualize_local_trajs_node rclcpp example_interfaces dynus_interfaces visualization_msgs Eigen3 decomp_ros_msgs sensor_msgs std_msgs decomp_rviz_plugins decomp_test_node tf2_geometry_msgs tf2 tf2_ros tf2_eigen std_srvs pcl_ros)

add_executable(temporal_layered_corridor_test_node src/sando/temporal_layered_corridor_test_node.cpp)
target_compile_options(temporal_layered_corridor_test_node PRIVATE -fno-fast-math -O1)
target_link_libraries(temporal_layered_corridor_test_node sando_planner)
ament_target_dependencies(temporal_layered_corridor_test_node rclcpp visualization_msgs std_msgs geometry_msgs Eigen3 decomp_util decomp_ros_msgs decomp_rviz_plugins decomp_test_node tf2 tf2_ros tf2_geometry_msgs tf2_eigen std_srvs pcl_ros pcl_conversions sensor_msgs dynus_interfaces)

# Benchmark analysis tool (C++ port of analyze_dynamic_benchmark.py)
find_package(rosbag2_cpp REQUIRED)
find_package(rosbag2_storage REQUIRED)
add_executable(analyze_benchmark src/tools/analyze_benchmark.cpp)
ament_target_dependencies(analyze_benchmark rclcpp dynus_interfaces tf2_msgs rosbag2_cpp rosbag2_storage)
target_link_libraries(analyze_benchmark nlohmann_json::nlohmann_json)

# Bag converter tool (lifetime adjustment + pointcloud z-filter)
add_executable(convert_bag src/tools/convert_bag.cpp)
ament_target_dependencies(convert_bag rclcpp visualization_msgs sensor_msgs decomp_ros_msgs rosbag2_cpp rosbag2_storage)

# install for launch and config files
install(DIRECTORY
launch
config
rviz
worlds
urdf
meshes
DESTINATION share/${PROJECT_NAME}
)

# install for executables
install(TARGETS
  sando
  fake_sim
  obstacle_tracker_node
  convert_goal_to_cmd_vel
  convert_odom_to_state
  odom_to_global_state
  convert_vicon_to_state
  convert_velodyne_to_ros_time
  dynamic_forest_node
  corridor_generator_node
  local_traj_benchmark_node
  visualize_local_trajs_node
  temporal_layered_corridor_test_node
  analyze_benchmark
  convert_bag
  DESTINATION lib/${PROJECT_NAME}
)

# install for libraries
install(TARGETS
  move_model
  imu_plugin
  dynamic_obstacles_world_plugin
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION bin
)

# Python modules (none — scripts are installed directly below)

# install Python executables
install(PROGRAMS
  scripts/goal_sender.py
  scripts/goal_relay.py
  scripts/goal_monitor_node.py
  scripts/generate_random_forest.py
  scripts/rviz_obstacles_node.py
  scripts/chaser_goal_forwarder.py
  benchmarking/dynamic_obstacle_benchmark_node.py
  benchmarking/unc_benchmark_node.py
  DESTINATION lib/${PROJECT_NAME}
)

if(SANDO_USE_AMPL)
  enable_testing()
  add_executable(segment_time_test tests/ampl_model/test_segment_time.cpp)
  target_include_directories(segment_time_test PRIVATE include)
  target_compile_options(segment_time_test PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME segment_time_consistency COMMAND segment_time_test)

  add_executable(planning_instance_test tests/ampl_model/test_planning_instance.cpp)
  target_link_libraries(planning_instance_test sando_ampl_backend)
  target_compile_options(planning_instance_test PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME planning_instance_roundtrip COMMAND planning_instance_test)

  add_executable(instance_reservoir_test tests/ampl_model/test_instance_reservoir.cpp)
  target_link_libraries(instance_reservoir_test sando_ampl_backend)
  target_compile_options(instance_reservoir_test PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME instance_reservoir_sampling COMMAND instance_reservoir_test)

  add_executable(frozen_observation_test tests/ampl_model/test_frozen_planning_observation.cpp)
  target_link_libraries(frozen_observation_test sando_ampl_backend)
  target_compile_options(frozen_observation_test PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME frozen_planning_observation COMMAND frozen_observation_test)

  add_executable(candidate_costs_test tests/ampl_model/test_candidate_costs.cpp src/sando/label_planning_instances.cpp)
  target_compile_definitions(candidate_costs_test PRIVATE SANDO_LABEL_PLANNING_INSTANCES_NO_MAIN=1)
  target_link_libraries(candidate_costs_test sando_ampl_backend)
  target_compile_options(candidate_costs_test PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME candidate_costs_complete COMMAND candidate_costs_test)

  add_executable(corridor_policy_test tests/ampl_model/test_corridor_policy.cpp)
  target_link_libraries(corridor_policy_test sando_ampl_backend)
  target_compile_options(corridor_policy_test PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME corridor_policy_features COMMAND corridor_policy_test)

  add_executable(timing_policy_test tests/ampl_model/test_timing_policy.cpp)
  target_include_directories(timing_policy_test PRIVATE include)
  target_compile_options(timing_policy_test PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(timing_policy_test Eigen3)
  add_test(NAME timing_policy_inference COMMAND timing_policy_test)

  add_executable(integer_replay_test tests/ampl_model/test_integer_replay.cpp)
  target_link_libraries(integer_replay_test sando_ampl_backend)
  target_compile_options(integer_replay_test PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME integer_replay_methods COMMAND integer_replay_test)

  add_executable(assignment_probe tests/ampls/assignment_probe.cpp)
  target_link_libraries(assignment_probe sando_planner)
  target_compile_options(assignment_probe PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(assignment_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  add_test(NAME assignment_qp_equivalence COMMAND assignment_probe)
  set_tests_properties(assignment_qp_equivalence PROPERTIES TIMEOUT 180)

  add_executable(online_corridor_probe tests/ampls/online_corridor_probe.cpp)
  target_link_libraries(online_corridor_probe sando_planner)
  target_compile_options(online_corridor_probe PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(online_corridor_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  add_test(NAME online_corridor_candidates COMMAND online_corridor_probe)
  set_tests_properties(online_corridor_candidates PROPERTIES TIMEOUT 180)

  add_executable(reconstruct_request_probe tests/ampls/reconstruct_request_probe.cpp)
  target_link_libraries(reconstruct_request_probe sando_planner)
  target_compile_options(reconstruct_request_probe PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(reconstruct_request_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  add_test(NAME reconstruct_planning_request COMMAND reconstruct_request_probe)
  set_tests_properties(reconstruct_planning_request PROPERTIES TIMEOUT 180)

  add_executable(infeasibility_group_probe tests/ampls/infeasibility_group_probe.cpp)
  target_link_libraries(infeasibility_group_probe sando_planner)
  target_compile_options(infeasibility_group_probe PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(infeasibility_group_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  add_test(NAME infeasibility_group_probe COMMAND infeasibility_group_probe
           "${CMAKE_CURRENT_SOURCE_DIR}/docker/dev-workspace/results/joint-time-v2/stage-jia/static_forest-easy-seed0/request_observation/2.json")
  set_tests_properties(infeasibility_group_probe PROPERTIES TIMEOUT 600)

  add_executable(corridor_containment_probe tests/ampls/corridor_containment_probe.cpp)
  target_link_libraries(corridor_containment_probe sando_planner)
  target_compile_options(corridor_containment_probe PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(corridor_containment_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  add_test(NAME corridor_containment_probe COMMAND corridor_containment_probe
           "${CMAKE_CURRENT_SOURCE_DIR}/docker/dev-workspace/results/joint-time-v2/stage-jia/static_forest-easy-seed0/request_observation/2.json"
           "2.0")
  set_tests_properties(corridor_containment_probe PROPERTIES TIMEOUT 300)

  add_executable(null_class_decomp_probe tests/ampls/null_class_decomp_probe.cpp)
  target_link_libraries(null_class_decomp_probe sando_planner)
  target_compile_options(null_class_decomp_probe PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(null_class_decomp_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  add_test(NAME null_class_live_map_decomp COMMAND null_class_decomp_probe)
  set_tests_properties(null_class_live_map_decomp PROPERTIES TIMEOUT 180)

  add_executable(time_fixed_z_forward_probe tests/ampls/time_fixed_z_forward_probe.cpp)
  target_link_libraries(time_fixed_z_forward_probe sando_planner)
  target_compile_options(time_fixed_z_forward_probe PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(time_fixed_z_forward_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  add_test(NAME time_fixed_z_forward COMMAND time_fixed_z_forward_probe
           "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampls/fixtures/translated_trajectory.json" "91659.8128")
  set_tests_properties(time_fixed_z_forward PROPERTIES TIMEOUT 300)

  add_executable(fixed_z_parity_probe tests/ampls/fixed_z_parity_probe.cpp)
  target_link_libraries(fixed_z_parity_probe sando_planner)
  target_compile_options(fixed_z_parity_probe PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(fixed_z_parity_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)


  add_test(NAME baseline_capture_checks COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_baseline_capture.py")
  add_test(NAME baseline_arrival_checks COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_baseline_sim.py")
  add_test(NAME integer_capture_campaign COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_capture_campaign.py")
  add_test(NAME integer_label_report COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_label_report.py")
  add_test(NAME integer_evaluation_campaign COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_evaluation_campaign.py")
  add_test(NAME integer_evaluation_report COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_evaluation_report.py")
  add_test(NAME urdf_mesh_resources COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/check_urdf_meshes.py")
  add_test(NAME integer_set_loss COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_set_loss.py")
  add_test(NAME integer_expert_labels COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_expert_labels.py")
  add_test(NAME integer_label_queue COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_label_queue.py")
  add_test(NAME integer_queue_recovery COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_queue_recovery.py")
  add_test(NAME integer_post_capture_identity COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_post_capture_identity.py")
  add_test(NAME integer_throughput COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_throughput.py")
  add_test(NAME forest_collision_geometry COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_forest_geometry.py")
  add_test(NAME integer_instance_sampler COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_instance_sampler.py")
  add_test(NAME integer_dagger_aggregate COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_dagger_aggregate.py")
  add_test(NAME integer_timing_policy COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_integer_timing_policy.py")
  add_test(NAME reconstructable_request COMMAND python3 "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampl_model/test_reconstructable_request.py")
  add_executable(ampl_model_test tests/ampl_model/test_ampl_model.cpp src/sando/ampl_model.cpp)
  target_include_directories(ampl_model_test PRIVATE include)
  target_compile_options(ampl_model_test PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME ampl_model_expressions COMMAND ampl_model_test)

  add_executable(ampl_centering_test tests/ampl_model/test_ampl_centering.cpp)
  target_link_libraries(ampl_centering_test sando_ampl_backend)
  target_compile_options(ampl_centering_test PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME ampl_objective_centering COMMAND ampl_centering_test)

  add_executable(numeric_focus_probe tests/ampls/numeric_focus_probe.cpp)
  target_link_libraries(numeric_focus_probe sando_ampl_backend)
  target_compile_options(numeric_focus_probe PRIVATE -UNDEBUG -fno-fast-math)
  add_test(NAME ampl_numeric_conditioning COMMAND numeric_focus_probe "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampls/fixtures/translated_trajectory.json")
  add_test(NAME ampl_numeric_conditioning_second COMMAND numeric_focus_probe "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampls/fixtures/translated_trajectory_second.json" "64294.3349625")
  add_test(NAME ampl_numeric_centering_persistent COMMAND numeric_focus_probe
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampls/fixtures/translated_trajectory.json" "91659.8128"
    "${CMAKE_CURRENT_SOURCE_DIR}/tests/ampls/fixtures/translated_trajectory_second.json" "64294.3349625")
  set_tests_properties(ampl_numeric_conditioning ampl_numeric_conditioning_second ampl_numeric_centering_persistent PROPERTIES TIMEOUT 180)
  set_tests_properties(ampl_numeric_centering_persistent PROPERTIES ENVIRONMENT "SANDO_AMPL_MODE=persistent;SANDO_AMPL_VERIFY_UPDATES=1")

  add_executable(ampl_adapter_probe tests/ampls/adapter_probe.cpp)
  target_link_libraries(ampl_adapter_probe sando_ampl_backend)
  target_compile_options(ampl_adapter_probe PRIVATE -fno-fast-math)
  add_test(NAME ampl_adapter_real_model COMMAND ampl_adapter_probe)

  add_executable(ampl_persistent_probe tests/ampls/persistent_probe.cpp)
  target_link_libraries(ampl_persistent_probe sando_ampl_backend)
  target_compile_options(ampl_persistent_probe PRIVATE -fno-fast-math)
  add_test(NAME ampl_persistent_updates COMMAND ampl_persistent_probe)
  set_tests_properties(ampl_persistent_updates PROPERTIES ENVIRONMENT "SANDO_AMPL_VERIFY_UPDATES=1" TIMEOUT 180)

  add_executable(ampl_cold_start_probe tests/ampls/cold_start_probe.cpp)
  target_link_libraries(ampl_cold_start_probe sando_ampl_backend)
  target_compile_options(ampl_cold_start_probe PRIVATE -fno-fast-math)
  add_test(NAME ampl_cold_concurrent_start COMMAND ampl_cold_start_probe)
  set_tests_properties(ampl_cold_concurrent_start PROPERTIES TIMEOUT 180)

  add_executable(ampl_trajectory_probe tests/ampls/trajectory_probe.cpp)
  target_link_libraries(ampl_trajectory_probe sando_planner)
  target_compile_options(ampl_trajectory_probe PRIVATE -fno-fast-math)
  ament_target_dependencies(ampl_trajectory_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  add_test(NAME ampl_trajectory_formulas COMMAND ampl_trajectory_probe)
  set_tests_properties(ampl_adapter_real_model ampl_trajectory_formulas PROPERTIES TIMEOUT 180)

  add_executable(planner_startup_probe tests/ampls/planner_startup_probe.cpp)
  target_link_libraries(planner_startup_probe sando_planner)
  target_compile_options(planner_startup_probe PRIVATE -UNDEBUG -fno-fast-math)
  ament_target_dependencies(planner_startup_probe rclcpp Eigen3 decomp_ros_msgs decomp_rviz_plugins dynus_interfaces)
  add_test(NAME planner_startup_state_order COMMAND planner_startup_probe)
  set_tests_properties(planner_startup_state_order PROPERTIES TIMEOUT 180)
endif()

ament_package()
