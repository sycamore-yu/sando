"""Check that baseline acceptance rejects stale and late observations, without ROS."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

path = Path(__file__).resolve().parents[2] / "scripts/integer_learning_baseline_sim.py"
spec = importlib.util.spec_from_file_location("baseline_sim", path)
sim = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sim)

monitor = SimpleNamespace(goal_sent_at=10., goal_reached_at=30., goal_reached=True,
                          last_odom_at=30.1, last_position=[105., 0., 2.],
                          max_displacement=105.)
assert sim._verified_goal(monitor, 30.2)
monitor.last_odom_at = 29.9
assert not sim._verified_goal(monitor, 30.2), "pre-event position must not certify arrival"
monitor.last_odom_at = 30.1
assert not sim._verified_goal(monitor, 32.), "old odometry must not certify arrival"
monitor.goal_reached_at = 110.001
monitor.last_odom_at = 110.002
assert not sim._verified_goal(monitor, 110.003), "late event must not pass the 100s cap"
monitor.goal_reached_at = 30.
monitor.last_odom_at = 30.1
monitor.last_position = [float("nan"), 0., 2.]
assert not sim._verified_goal(monitor, 30.2)
monitor.last_position = [0., 0., 2.]
assert not sim._verified_goal(monitor, 30.2), "an event at the start is not a completed flight"

base = {"SANDO_CORRIDOR_METHOD": "learned", "SANDO_CORRIDOR_POLICY": "old",
        "SANDO_REPLAN_METRICS": "old-metrics", "OTHER": "preserved"}
environment = sim._evaluation_environment(base, "original")
assert environment["SANDO_CORRIDOR_METHOD"] == "original"
assert "SANDO_CORRIDOR_POLICY" not in environment and "SANDO_REPLAN_METRICS" not in environment
assert environment["OTHER"] == "preserved"
environment = sim._evaluation_environment(base, "previous")
assert environment["SANDO_CORRIDOR_METHOD"] == "previous"
environment = sim._evaluation_environment(base, "bc", "/tmp/policy.json", "/tmp/metrics.json")
assert environment["SANDO_CORRIDOR_METHOD"] == "learned"
assert environment["SANDO_CORRIDOR_POLICY"] == "/tmp/policy.json"
assert environment["SANDO_REPLAN_METRICS"] == "/tmp/metrics.json"
try:
    sim._evaluation_environment(base, "cost")
except ValueError:
    pass
else:
    raise AssertionError("learned method without policy accepted")

touching = sim._model_states_collision(
    [{"receipt_time": 0.0, "sim_time": 7.0,
      "names": ["NX01", "obstacle_0"],
      "poses": [[1.0, 0.0, 0.0], [0.0, 0.0, 0.0]]}],
    [{"name": "obstacle_0", "size_x": 1.0, "size_y": 1.0, "size_z": 1.0}],
    1,
    drone_bbox=(1.0, 1.0, 1.0),
)
assert touching["available"] and touching["collision"]
assert touching["first_hit_ids"] == [4000]
assert touching["first_hit_time"] == 7.0 and touching["first_hit_receipt_time"] == 0.0
assert touching["metric_definition"]["sample_source"].startswith("co-sampled")

moving = sim._model_states_collision(
    [{"receipt_time": 1.0, "sim_time": 1.0,
      "names": ["NX01", "obstacle_0"],
      "poses": [[10.0, 0.0, 0.0], [0.0, 0.0, 0.0]]},
     {"receipt_time": 3.0, "sim_time": 2.0,
      "names": ["NX01", "obstacle_0"],
      "poses": [[2.0, 0.0, 0.0], [2.0, 0.0, 0.0]]}],
    [{"name": "obstacle_0", "size_x": 0.2, "size_y": 0.2, "size_z": 0.2}],
    1,
    drone_bbox=(0.2, 0.2, 0.2),
)
assert moving["available"] and moving["collision"]
assert moving["first_hit_time"] == 2.0 and moving["samples_checked"] == 2
assert moving["metric_definition"]["sample_interval_max_sec"] == 2.0

missing = sim._model_states_collision([], [], 2)
assert not missing["available"] and missing["collision"] is None
assert "NX01" in missing["missing_models"]

missing_obstacle = sim._model_states_collision(
    [{"receipt_time": 1.0, "names": ["NX01"], "poses": [[0.0, 0.0, 0.0]]}],
    [{"name": "obstacle_0", "size": 1.0}], 1)
assert not missing_obstacle["available"] and missing_obstacle["collision"] is None

invalid_bbox = sim._model_states_collision(
    [{"receipt_time": 1.0, "names": ["NX01", "obstacle_0"],
      "poses": [[0.0, 0.0, 0.0], [0.0, 0.0, 0.0]]}],
    [{"name": "obstacle_0", "size_x": float("nan"), "size_y": 1.0, "size_z": 1.0}], 1)
assert not invalid_bbox["available"] and invalid_bbox["collision"] is None

stale = sim._Monitor.__new__(sim._Monitor)
stale.goal_sent_at = 10.0
stale.latest_setpoint = [1.0, 0.0, 0.0]
stale.latest_setpoint_at = 100.0
stale.latest_setpoint_received_at = 9.0
stale.setpoint_stale_excluded = 0
stale.tracking_error_samples = []
stale.odom_samples = stale.odom_samples_after_goal = 0
stale.last_position = stale.last_odom_at = stale.max_displacement = None
stale.odom_trace = []
odom = SimpleNamespace(
    header=SimpleNamespace(stamp=SimpleNamespace(sec=100, nanosec=0)),
    pose=SimpleNamespace(pose=SimpleNamespace(position=SimpleNamespace(x=0.0, y=0.0, z=0.0))),
)
stale._on_odom(odom)
assert not stale.tracking_error_samples
assert stale.setpoint_stale_excluded == 1

print("PASS: arrival checks, co-sampled AABB geometry, model coverage and stale setpoints")

import inspect
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from integer_scene_protocol import launch_spec
from run_sim import generate_gazebo_dynamic_yaml, generate_gazebo_yaml, generate_rviz_only_yaml

assert "use_dyn_obs" in inspect.signature(generate_gazebo_yaml).parameters
assert "environment_assumption" in inspect.signature(generate_gazebo_yaml).parameters
assert "depth_topic" in inspect.signature(generate_gazebo_yaml).parameters
assert "use_benchmark" in inspect.signature(generate_rviz_only_yaml).parameters
assert "publish_trajs" in inspect.signature(generate_gazebo_dynamic_yaml).parameters
assert launch_spec("static_forest", 50)["env"] == "easy_forest"
assert launch_spec("known_dynamic", 200)["information_boundary"] == "privileged_ground_truth_trajs"
assert sim.randomization_for_split("train_box_v1", "test") == "none"
print("PASS: aligned launch signatures and information boundaries")

# Static flights must activate the goal timer even without a benchmark CSV file.
import shlex
import sys
sys.path.insert(0, str(path.parent))
import yaml
launch = yaml.safe_load(sim._launch_yaml(Path('/tmp/setup.bash'),
    {'family': 'static_forest', 'env': 'easy_forest'}, (0., 0., 2.), 0, 61,
    '/tmp/recorded forest.world'))
commands = [command for window in launch['windows'] for pane in window['panes']
            for command in pane['shell_command']]
base_command = next(command for command in commands if 'base_sando.launch.py' in command)
onboard_command = next(command for command in commands if 'onboard_sando.launch.py' in command)
assert 'world_file:=/tmp/recorded forest.world' in shlex.split(base_command)
assert 'use_benchmark:=true' in shlex.split(onboard_command)
assert 'global_planner:=astar_heat' in shlex.split(onboard_command)

inherited_timing = {**base, 'SANDO_TIMING_POLICY': 'old', 'SANDO_TIMING_NFE': '8'}
assert 'SANDO_TIMING_POLICY' not in sim._evaluation_environment(inherited_timing, 'original')
environment = sim._evaluation_environment(inherited_timing, 'cost', '/tmp/policy.json',
                                         timing_policy='/tmp/timing.json', timing_nfe=4)
assert environment['SANDO_TIMING_POLICY'] == '/tmp/timing.json'
assert environment['SANDO_TIMING_NFE'] == '4'

forest_touching = sim._model_states_collision(
    [{"receipt_time": 0.0, "names": ["NX01", "tree17"],
      "poses": [[0., 0., 0.], [0., 0., 0.]]}],
    [{"name": "tree17", "size": 1.}], ["tree17"])
assert forest_touching["collision"] and forest_touching["first_hit_names"] == ["tree17"]
assert forest_touching["first_hit_ids"] == [4000]
assert not sim._simulation_health({"runner_exception": "IndexError: bad sample"}, "")["valid"]
assert sim._simulation_health({"readiness": {"ready": True, "goal_subscribers": 1}, "ground_truth": {"available": True}, "success": False}, "")["valid"]

assert not sim._simulation_health({"readiness": {"ready": True, "goal_subscribers": 2}, "ground_truth": {"available": True}}, "")["valid"]
