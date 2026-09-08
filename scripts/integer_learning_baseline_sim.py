#!/usr/bin/env python3
"""Run one reproducible integer-learning baseline Gazebo observation.

The caller chooses the static (``--dynamic-ratio 0``) or unknown-dynamic
(``--dynamic-ratio 0.65``) case.  The simulation is launched without a goal
sender; this process subscribes first, waits for odometry and the planner's
goal subscriber, then publishes the goal and records the result.
"""

import argparse
import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from integer_scene_protocol import (
    launch_spec,
    randomization_for_split,
    resolve_start,
    scene_id as protocol_scene_id,
)



SESSION = "sando_sim"
NAMESPACE = "NX01"
START = (0.0, 0.0, 2.0)
GOAL = (105.0, 0.0, 2.0)
OBSERVATION_TIMEOUT = 100.0
READINESS_TIMEOUT = 60.0
DRONE_BBOX = (0.2, 0.2, 0.2)
SETPOINT_MAX_AGE_SEC = 0.02  # 2 * config/sando.yaml dc (0.01 s)
MODEL_STATES_TOPIC = "/plug/model_states_plug"
MODEL_STATE_EVIDENCE_LIMIT = 20000


class _ModelStatesCollision:
    """Accumulate co-sampled Gazebo model poses without retaining all frames."""

    def __init__(self, obstacles, expected_count, drone_bbox=DRONE_BBOX,
                 robot_name=NAMESPACE):
        self.robot_name = robot_name
        try:
            self.robot_bbox = tuple(float(value) for value in drone_bbox)
        except (TypeError, ValueError):
            self.robot_bbox = ()
        self.obstacles = {}
        for item in obstacles if isinstance(obstacles, list) else []:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            size = [item.get(f"size_{axis}", item.get("size")) for axis in "xyz"]
            try:
                size = tuple(float(value) for value in size)
            except (TypeError, ValueError):
                size = ()
            self.obstacles[str(item["name"])] = size
        self.expected_names = [f"obstacle_{index}" for index in range(int(expected_count))]
        self.seen_models = set()
        self.samples_checked = 0
        self.incomplete_samples = 0
        self.last_receipt_time = None
        self.max_sample_interval = None
        self.clearance_samples = []
        self.first_hit_ids = []
        self.first_hit_time = None
        self.first_hit_receipt_time = None
        self.first_hit_position = None
        self.collision = False

    @staticmethod
    def _position(pose):
        try:
            point = pose.position
            values = (float(point.x), float(point.y), float(point.z))
        except AttributeError:
            try:
                values = tuple(float(value) for value in pose[:3])
            except (IndexError, TypeError, ValueError):
                return None
        if len(values) != 3 or not all(math.isfinite(value) for value in values):
            return None
        return values

    def record(self, names, poses, receipt_time, sim_time=None):
        try:
            receipt_time = float(receipt_time)
            names = list(names)
            poses = list(poses)
        except (TypeError, ValueError):
            self.incomplete_samples += 1
            return
        models = {}
        for name, pose in zip(names, poses):
            position = self._position(pose)
            if position is not None:
                models[str(name)] = position
                self.seen_models.add(str(name))
        required = [self.robot_name, *self.expected_names]
        if any(name not in models for name in required):
            self.incomplete_samples += 1
            return
        if not math.isfinite(receipt_time):
            self.incomplete_samples += 1
            return
        try:
            sim_time = float(sim_time) if sim_time is not None else None
        except (TypeError, ValueError):
            sim_time = None
        if len(self.robot_bbox) != 3 or not all(
                math.isfinite(value) and value >= 0 for value in self.robot_bbox):
            self.incomplete_samples += 1
            return
        for name in self.expected_names:
            bbox = self.obstacles.get(name, ())
            if len(bbox) != 3 or not all(math.isfinite(value) and value >= 0 for value in bbox):
                self.incomplete_samples += 1
                return
        if self.last_receipt_time is not None and receipt_time >= self.last_receipt_time:
            interval = receipt_time - self.last_receipt_time
            self.max_sample_interval = interval if self.max_sample_interval is None else max(
                self.max_sample_interval, interval)
        self.last_receipt_time = receipt_time
        robot = models[self.robot_name]
        frame_hits = []
        frame_clearance = math.inf
        for name in self.expected_names:
            obstacle = models[name]
            bbox = self.obstacles[name]
            half_sum = tuple((self.robot_bbox[axis] + bbox[axis]) / 2.0 for axis in range(3))
            gaps = tuple(max(abs(robot[axis] - obstacle[axis]) - half_sum[axis], 0.0)
                         for axis in range(3))
            frame_clearance = min(frame_clearance, math.sqrt(sum(value * value for value in gaps)))
            if all(abs(robot[axis] - obstacle[axis]) <= half_sum[axis] for axis in range(3)):
                frame_hits.append(name)
        self.samples_checked += 1
        if len(self.clearance_samples) < MODEL_STATE_EVIDENCE_LIMIT:
            self.clearance_samples.append({
                "sim_time": sim_time if sim_time is not None and math.isfinite(sim_time) else None,
                "receipt_time": receipt_time,
                "min_clearance_m": frame_clearance,
            })
        if frame_hits and not self.first_hit_ids:
            self.collision = True
            self.first_hit_ids = [int(name.split("_", 1)[1]) + 4000 for name in frame_hits]
            self.first_hit_time = sim_time if sim_time is not None and math.isfinite(sim_time) else receipt_time
            self.first_hit_receipt_time = receipt_time
            self.first_hit_position = list(robot)

    def result(self):
        missing = sorted({self.robot_name, *self.expected_names} - self.seen_models)
        definition = {
            "name": "sampled_AABB_overlap",
            "robot_bbox_full_size_m": list(self.robot_bbox),
            "obstacle_bbox_full_size_source": "/tmp/sando_obstacles.json size_x/size_y/size_z",
            "overlap_rule": "abs(robot_center - obstacle_center) <= (robot_bbox + obstacle_bbox) / 2 per axis",
            "sample_source": f"co-sampled {MODEL_STATES_TOPIC} model poses after goal",
            "continuous_collision_proof": False,
            "sample_interval_max_sec": self.max_sample_interval,
        }
        available = self.samples_checked > 0 and not missing
        return {
            "available": available,
            "collision": bool(self.collision) if available else None,
            "samples_checked": self.samples_checked,
            "incomplete_samples": self.incomplete_samples,
            "missing_models": missing,
            "first_hit_ids": self.first_hit_ids,
            "first_hit_time": self.first_hit_time if available else None,
            "first_hit_receipt_time": self.first_hit_receipt_time if available else None,
            "first_hit_position": self.first_hit_position if available else None,
            "metric_definition": definition,
            "min_clearance_samples": self.clearance_samples,
            "reason": None if available else "incomplete co-sampled model-state coverage",
        }


def _model_states_collision(snapshots, obstacles, expected_count, drone_bbox=DRONE_BBOX):
    """Test helper and offline adapter for normalized ModelStates snapshots."""
    accumulator = _ModelStatesCollision(obstacles, expected_count, drone_bbox)
    for snapshot in snapshots:
        accumulator.record(snapshot.get("names", []), snapshot.get("poses", []),
                           snapshot.get("receipt_time"), snapshot.get("sim_time"))
    return accumulator.result()


def _write_json(path, value):
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _probe(command, cwd):
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        return {
            "command": command,
            "returncode": completed.returncode,
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": command, "returncode": None, "error": str(error)}


def _file_identity(path):
    path = Path(path)
    if not path.exists():
        return {"missing": True}
    if not path.is_file():
        return {"not_a_file": True}
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "size": path.stat().st_size,
    }


def _source_identity(repo, setup_bash):
    """Capture the source and configuration identity used by this run."""
    from ament_index_python.packages import get_package_share_directory

    tracked = [
        "scripts/run_sim.py",
        "scripts/integer_learning_baseline_sim.py",
        "config/sando.yaml",
        "docker/Dockerfile.ampl",
        "docker/entrypoint_ampl.sh",
        "launch/base_sando.launch.py",
        "launch/onboard_sando.launch.py",
        "urdf/_d435.urdf.xacro",
        "urdf/_d435i.urdf.xacro",
    ]
    installed_inputs = {}
    for package in ("sando", "global_mapper_ros"):
        share = Path(get_package_share_directory(package))
        for directory in ("config", "cfg", "launch", "urdf"):
            for path in sorted((share / directory).rglob("*")):
                if path.is_file() and path.suffix in (".yaml", ".xacro", ".py", ".urdf"):
                    installed_inputs[f"{package}/{path.relative_to(share)}"] = _file_identity(path)
    build_commit = Path("/opt/sando-source.commit")
    return {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repository": str(repo),
        "host": platform.platform(),
        "python": sys.version,
        "git_head": _probe(["git", "rev-parse", "HEAD"], repo),
        "git_status": _probe(
            ["git", "status", "--short", "--untracked-files=all"], repo
        ),
        "submodules": _probe(["git", "submodule", "status", "--recursive"], repo),
        "files": {name: _file_identity(repo / name) for name in tracked},
        "installed_inputs": installed_inputs,
        "image_source_commit": build_commit.read_text().strip() if build_commit.exists() else None,
        "image_source_manifest": _file_identity("/opt/sando-source.sha256"),
        "integer_learning_source_manifest": _file_identity("/opt/sando-integer-source.json"),
        "setup_bash": str(setup_bash),
        "setup_bash_identity": _file_identity(setup_bash),
        "backend_environment": {
            name: os.environ.get(name)
            for name in (
                "SANDO_USE_AMPL",
                "SANDO_AMPL_MODE",
                "SANDO_AMPL_VERIFY_UPDATES",
                "SANDO_AMPL_TRACE",
                "SANDO_SOURCE_COMMIT",
            )
        },
    }


def _kill_own_session():
    """Stop only the tmux session owned by this runner."""
    try:
        subprocess.run(
            ["tmux", "kill-session", "-t", SESSION],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _session_exists():
    try:
        return subprocess.run(
            ["tmux", "has-session", "-t", SESSION],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _capture_logs(output_dir):
    log_path = output_dir / "tmux.log"
    sections = []
    try:
        listed = subprocess.run(
            ["tmux", "list-panes", "-t", SESSION, "-F", "#{window_index}.#{pane_index}"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if listed.returncode != 0:
            sections.append("tmux list-panes failed:\n" + listed.stderr.strip())
        else:
            for target in filter(None, listed.stdout.splitlines()):
                captured = subprocess.run(
                    [
                        "tmux",
                        "capture-pane",
                        "-p",
                        "-J",
                        "-S",
                        "-",
                        "-t",
                        f"{SESSION}:{target}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
                sections.append(f"===== pane {target} =====\n{captured.stdout}")
                if captured.returncode != 0:
                    sections.append("capture stderr: " + captured.stderr.strip())
    except (OSError, subprocess.TimeoutExpired) as error:
        sections.append(f"tmux log capture failed: {error}")
    log_path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return str(log_path.name)


def _copy_generated_files(output_dir):
    """Copy run_sim's fixed temporary files before the tmux session is torn down."""
    copied = {}
    for source_name, output_name in (
        ("/tmp/sando_obstacles.json", "obstacles.json"),
        ("/tmp/sando_world.world", "generated_world.world"),
    ):
        source = Path(source_name)
        destination = output_dir / output_name
        if source.is_file():
            shutil.copy2(source, destination)
            copied[output_name] = str(destination.name)
        else:
            copied[output_name] = None
    return copied


def _spin_once(rclpy, node):
    try:
        rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        raise


def _make_goal(goal, node):
    from geometry_msgs.msg import PoseStamped

    message = PoseStamped()
    message.header.frame_id = "map"
    message.header.stamp = node.get_clock().now().to_msg()
    message.pose.position.x = goal[0]
    message.pose.position.y = goal[1]
    message.pose.position.z = goal[2]
    message.pose.orientation.w = 1.0
    return message


class _Monitor:
    """Small ROS monitor; all metrics come from received messages."""

    def __init__(self, node, obstacles, expected_count, start=START):
        from nav_msgs.msg import Odometry
        from rclpy.qos import (DurabilityPolicy, HistoryPolicy, QoSProfile,
                               ReliabilityPolicy)
        from std_msgs.msg import Empty
        from geometry_msgs.msg import PointStamped
        from gazebo_msgs.msg import ModelStates

        self.node = node
        self.start = list(start)
        self.odom_samples = 0
        self.odom_samples_after_goal = 0
        self.last_position = None
        self.max_displacement = None
        self.last_odom_at = None
        self.goal_sent_at = None
        self.goal_reached_at = None
        self.goal_reached = False
        self.latest_setpoint = None
        self.latest_setpoint_at = None
        self.latest_setpoint_received_at = None
        self.setpoint_stale_excluded = 0
        self.tracking_error_samples = []
        self.model_states_collision = _ModelStatesCollision(obstacles, expected_count)
        self.odom_trace = []
        self.odom_topics = [f"/{NAMESPACE}/visual_slam/odom", f"/{NAMESPACE}/odom"]
        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        # Subscribe before the simulation is launched and before the goal is
        # published.  The second topic is a compatibility fallback for images
        # configured with the short odom topic name.
        self.odom_subscriptions = [
            node.create_subscription(Odometry, topic, self._on_odom, qos)
            for topic in self.odom_topics
        ]
        self.goal_reached_subscription = node.create_subscription(
            Empty, f"/{NAMESPACE}/goal_reached", self._on_goal_reached, qos
        )
        self.setpoint_subscription = node.create_subscription(
            PointStamped, f"/{NAMESPACE}/setpoint_vis", self._on_setpoint, qos
        )
        model_qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )
        self.model_states_subscription = node.create_subscription(
            ModelStates, MODEL_STATES_TOPIC, self._on_model_states, model_qos
        )

    @staticmethod
    def _stamp(message):
        stamp = message.header.stamp
        return float(stamp.sec) + 1e-9 * float(stamp.nanosec)

    def _on_setpoint(self, message):
        point = message.point
        values = [float(point.x), float(point.y), float(point.z)]
        if all(math.isfinite(value) for value in values):
            self.latest_setpoint = values
            self.latest_setpoint_at = self._stamp(message)
            self.latest_setpoint_received_at = time.monotonic()

    def _on_model_states(self, message):
        receipt_time = time.monotonic()
        sim_time = self.node.get_clock().now().nanoseconds * 1e-9
        if self.goal_sent_at is None or receipt_time < self.goal_sent_at:
            return
        self.model_states_collision.record(message.name, message.pose, receipt_time, sim_time)

    def _on_odom(self, message):
        now = time.monotonic()
        position = message.pose.pose.position
        current = [float(position.x), float(position.y), float(position.z)]
        odometry_time = self._stamp(message)
        displacement = math.sqrt(
            sum((current[index] - getattr(self, "start", START)[index]) ** 2 for index in range(3))
        )
        self.odom_samples += 1
        self.last_position = current
        self.last_odom_at = now
        after_goal = self.goal_sent_at is not None and now >= self.goal_sent_at
        if after_goal:
            self.odom_samples_after_goal += 1
            self.odom_trace.append({
                "timestamp": odometry_time if math.isfinite(odometry_time) else None,
                "position": [value if math.isfinite(value) else None for value in current],
            })
        if after_goal and self.latest_setpoint is not None:
            age = odometry_time - self.latest_setpoint_at
            fresh = self.latest_setpoint_received_at is not None \
                and self.latest_setpoint_received_at >= self.goal_sent_at \
                and math.isfinite(age) and 0.0 <= age <= SETPOINT_MAX_AGE_SEC
            if not fresh:
                self.setpoint_stale_excluded += 1
            if fresh:
                error = math.dist(current, self.latest_setpoint)
                if math.isfinite(error):
                    self.tracking_error_samples.append({
                        "wall_time": now,
                        "odometry_time": odometry_time,
                        "setpoint_time": self.latest_setpoint_at,
                        "age_sec": age,
                        "error_m": error,
                    })
        self.max_displacement = (
            displacement
            if self.max_displacement is None
            else max(self.max_displacement, displacement)
        )

    def _on_goal_reached(self, _message):
        now = time.monotonic()
        if self.goal_sent_at is not None and now >= self.goal_sent_at and not self.goal_reached:
            self.goal_reached = True
            self.goal_reached_at = now


def _verified_goal(monitor, now):
    """Require a timely event and a fresh finite position received after it."""
    if (monitor.goal_sent_at is None or monitor.goal_reached_at is None
            or monitor.last_odom_at is None or monitor.last_position is None):
        return False
    return bool(
        monitor.goal_reached
        and 0 <= monitor.goal_reached_at - monitor.goal_sent_at <= OBSERVATION_TIMEOUT
        and monitor.goal_reached_at <= monitor.last_odom_at <= monitor.goal_sent_at + OBSERVATION_TIMEOUT
        and 0 <= now - monitor.last_odom_at <= 1.0
        and all(math.isfinite(value) for value in monitor.last_position)
        and math.dist(monitor.last_position, GOAL) <= 1.0
        and monitor.max_displacement is not None
        and math.isfinite(monitor.max_displacement)
        and monitor.max_displacement >= 1.0
    )


def _wait_until_ready(rclpy, node, monitor, goal_publisher, deadline):
    while time.monotonic() < deadline:
        _spin_once(rclpy, node)
        if monitor.odom_samples and goal_publisher.get_subscription_count() > 0:
            return True, None
    details = {
        "odom_samples": monitor.odom_samples,
        "goal_subscribers": goal_publisher.get_subscription_count(),
    }
    return False, "ROS readiness timeout: " + json.dumps(details, sort_keys=True)



def _obstacle_snapshot(family, seed, num_obstacles, dynamic_ratio):
    if family in ("unknown_dynamic", "known_dynamic"):
        from run_sim import _generate_obstacle_json
        return _generate_obstacle_json(
            num_obstacles, seed, 5.0, 100.0, -6.0, 6.0, 0.5, 4.5,
            dynamic_ratio=dynamic_ratio,
        )
    return []


def _launch_yaml(setup_bash, spec, start_pos, seed, ros_domain_id):
    from run_sim import (
        generate_gazebo_dynamic_yaml,
        generate_gazebo_yaml,
        generate_rviz_only_yaml,
    )
    family = spec["family"]
    if family == "unknown_dynamic":
        launch_yaml = generate_gazebo_dynamic_yaml(
            setup_bash,
            goal=GOAL,
            env="empty_wo_ground",
            start_pos=start_pos,
            start_yaw=0.0,
            ros_domain_id=ros_domain_id,
            use_rviz=False,
            use_gazebo_gui=False,
            num_dyn_obstacles=spec["num_obstacles"],
            dynamic_ratio=spec["dynamic_ratio"],
            seed=seed,
            send_goal=False,
            publish_trajs=False,
            trajs_topic="/trajs_ground_truth",
            depth_topic="d435/depth/color/points",
            use_benchmark=True,
            global_planner="astar_heat",
        )
        return launch_yaml.replace(
            "use_benchmark:=true ",
            f"environment_assumption:={spec['environment_assumption']} use_benchmark:=true ",
            1,
        )
    if family == "static_forest":
        return generate_gazebo_yaml(
            setup_bash,
            goal=GOAL,
            env=spec["env"],
            start_pos=start_pos,
            start_yaw=0.0,
            ros_domain_id=ros_domain_id,
            use_rviz=False,
            use_gazebo_gui=False,
            use_dyn_obs=False,
            use_benchmark=True,
            global_planner="astar_heat",
            send_goal=False,
            environment_assumption="static",
            depth_topic="d435/depth/color/points",
        )
    return generate_rviz_only_yaml(
        setup_bash,
        goal=GOAL,
        start_pos=start_pos,
        start_yaw=0.0,
        ros_domain_id=ros_domain_id,
        num_obstacles=spec["num_obstacles"],
        dynamic_ratio=spec["dynamic_ratio"],
        seed=seed,
        send_goal=False,
        use_rviz=False,
        use_benchmark=True,
        global_planner="astar_heat",
        environment_assumption="dynamic",
    )


def _run(args):
    import rclpy
    from geometry_msgs.msg import PoseStamped

    output_dir = args.output.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise RuntimeError(f"output directory is not empty: {output_dir}")

    ratio = float(args.dynamic_ratio)
    case = "static" if math.isclose(ratio, 0.0, abs_tol=1e-12) else "unknown_dynamic"
    ros_domain_id = int(os.environ.get("ROS_DOMAIN_ID", "42"))
    setup_bash = args.setup_bash.resolve()
    initial_collision = _ModelStatesCollision([], args.num_obstacles).result()
    policy_identity = None
    if args.policy is not None:
        policy_path = args.policy.resolve()
        policy_identity = {"path": str(policy_path), **_file_identity(policy_path)}
    policy_hash = (policy_identity or {}).get("sha256")
    model_version = args.method if args.method in ("original", "previous") \
        else f"{args.method}:{policy_hash}"
    repo = Path(__file__).resolve().parents[1]
    started_utc = datetime.now(timezone.utc).isoformat()
    wall_started = time.monotonic()
    result = {
        "schema_version": 1,
        "case": case,
        "started_utc": started_utc,
        "parameters": {
            "dynamic_ratio": ratio,
            "seed": args.seed,
            "num_obstacles": args.num_obstacles,
            "method": args.method,
            "policy": str(args.policy.resolve()) if args.policy is not None else None,
            "model_version": model_version,
            "metrics": str(args.metrics.resolve()) if args.metrics is not None else None,
            "start": list(START),
            "scene_family": getattr(args, "scene_family", "unknown_dynamic"),
            "protocol_id": getattr(args, "protocol_id", "legacy"),
            "goal": list(GOAL),
            "environment": "empty_wo_ground",
            "backend": "AMPL->AMPLS->Gurobi",
            "publish_trajs": False,
            "ros_domain_id": ros_domain_id,
            "observation_timeout_sec": OBSERVATION_TIMEOUT,
        },
        "success": False,
        "goal_reached": False,
        "goal_sent": False,
        "odom_samples": 0,
        "odom_samples_after_goal": 0,
        "max_displacement_m": None,
        "last_position": None,
        "goal_distance_m": None,
        "goal_time_sec": None,
        "elapsed_sec": None,
        "wall_elapsed_sec": None,
        "goal_sent_wall_unix": None,
        "observation_end_wall_unix": None,
        "error": None,
        "logs": None,
        "policy_identity": policy_identity,
        "model_version": model_version,
        "tracking_error": None,
        "ground_truth": {
            "topic": MODEL_STATES_TOPIC,
            "clock": "co-sampled robot and obstacle poses; receipt time is monotonic",
            "available": False,
            "obstacle_geometry_source": "saved obstacles.json model names and box dimensions",
            "odom_trace": [],
            "collision": initial_collision,
        },
    }
    node = None
    goal_publisher = None
    monitor = None
    rclpy_started = False
    session_started = False
    session_ownership_established = False
    try:
        family = getattr(args, "scene_family", "unknown_dynamic")
        spec = launch_spec(family, args.num_obstacles, ratio)
        split = _scene_split(args.seed)
        randomization = randomization_for_split(
            getattr(args, "start_randomization", "none"), split
        )
        protocol_id = getattr(args, "protocol_id", "legacy")
        scene = protocol_scene_id(
            family, args.seed, args.num_obstacles, spec["dynamic_ratio"], protocol_id
        )
        obstacles = _obstacle_snapshot(family, args.seed, args.num_obstacles, spec["dynamic_ratio"])
        start_record = resolve_start(scene, family, obstacles, randomization)
        start_pos = tuple(start_record["accepted"])
        assumption = spec["environment_assumption"]
        launch_yaml = _launch_yaml(setup_bash, spec, start_pos, args.seed, ros_domain_id)
        result["case"] = family
        result["parameters"]["start"] = list(start_pos)
        result["parameters"]["start_yaw"] = 0.0
        result["parameters"]["environment"] = spec["env"]
        result["parameters"]["publish_trajs"] = spec["publish_trajs"]
        result["parameters"]["trajs_topic"] = spec["trajs_topic"]
        result["parameters"]["dynamic_ratio"] = spec["dynamic_ratio"]
        result["parameters"]["information_boundary"] = spec["information_boundary"]
        result["start"] = start_record
        (output_dir / "launch.yaml").write_text(launch_yaml, encoding="utf-8")
        copied = _copy_generated_files(output_dir)
        result["artifacts"] = copied
        result["artifacts"]["launch_yaml"] = "launch.yaml"

        config = dict(result["parameters"])
        config.update({
            "planner": "astar_heat",
            "environment_assumption": assumption,
            "scene_family": family,
            "protocol_id": protocol_id,
            "information_boundary": spec["information_boundary"],
            "start": start_record,
            "policy_identity": policy_identity,
            "model_version": model_version,
        })
        _write_json(output_dir / "config.json", config)
        identity = _source_identity(repo, setup_bash)
        _write_json(output_dir / "source_identity.json", identity)
        capture_config_path = None
        if args.capture:
            manifest = Path("/opt/sando-integer-source.json")
            if not manifest.is_file():
                raise RuntimeError("capture requires a frozen integer-learning source manifest")
            split = _scene_split(args.seed)
            if args.capture_round and split != "train":
                raise ValueError("closed-loop capture is restricted to training scenes")
            scene_id = scene
            metadata = {
                "scene_id": scene_id,
                "episode_id": f"{scene_id}:capture:r{args.capture_round}",
                "source_id": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                "config_id": hashlib.sha256(json.dumps(
                    {"run": config, "installed_inputs": identity["installed_inputs"],
                     "policy_identity": policy_identity, "model_version": model_version},
                    sort_keys=True).encode()).hexdigest(),
                "policy_identity": policy_identity,
                "model_version": model_version,
                "split": split,
                "capture_round": args.capture_round,
                "scene_family": family,
                "protocol_id": protocol_id,
                "information_boundary": spec["information_boundary"],
                "start": start_record,
            }
            capture_config_path = output_dir / "capture_config.json"
            _write_json(capture_config_path, {
                "output": str(output_dir / "instances.jsonl"),
                "capacity": (
                    args.capture_capacity if getattr(args, "capture_capacity", None) is not None
                    else (5 if args.capture_round else 10)
                ),
                "sampling_protocol": getattr(args, "sampling_protocol", "uniform_reservoir_v1"),
                "seed": int.from_bytes(hashlib.sha256(
                    metadata["episode_id"].encode()).digest()[:8], "big"),
                "metadata": metadata,
            })
            result["capture"] = metadata

        rclpy.init(args=None, domain_id=ros_domain_id)
        rclpy_started = True
        from rclpy.parameter import Parameter
        node = rclpy.create_node(
            "integer_learning_baseline_monitor",
            parameter_overrides=[Parameter("use_sim_time", value=True)],
        )
        if family == "static_forest":
            obstacle_json = []
            expected_count = 0
        else:
            json_path = Path("/tmp/sando_obstacles.json")
            obstacle_json = json.loads(json_path.read_text(encoding="utf-8")) if json_path.is_file() else obstacles
            expected_count = args.num_obstacles
        monitor = _Monitor(node, obstacle_json, expected_count, start=start_pos)

        launch_env = os.environ.copy()
        launch_env["SETUP_BASH"] = str(setup_bash)
        launch_env["ROS_DOMAIN_ID"] = str(ros_domain_id)
        launch_env = _evaluation_environment(
            launch_env, args.method, args.policy, args.metrics
        )
        launch_env.pop("SANDO_CAPTURE_CONFIG", None)
        if capture_config_path is not None:
            launch_env["SANDO_CAPTURE_CONFIG"] = str(capture_config_path)
        if _session_exists():
            raise RuntimeError(
                f"refusing to use existing tmux session {SESSION!r}; "
                "the runner owns no session yet"
            )
        session_ownership_established = True
        subprocess.run(
            ["tmuxp", "load", "-d", str(output_dir / "launch.yaml")],
            env=launch_env,
            check=True,
            timeout=30,
        )
        session_started = True
        result["launch_started"] = True

        goal_publisher = node.create_publisher(
            PoseStamped,
            f"/{NAMESPACE}/term_goal",
            10,
        )
        ready, readiness_error = _wait_until_ready(
            rclpy,
            node,
            monitor,
            goal_publisher,
            time.monotonic() + READINESS_TIMEOUT,
        )
        result["readiness"] = {
            "ready": ready,
            "odom_samples": monitor.odom_samples,
            "goal_subscribers": goal_publisher.get_subscription_count(),
        }
        if not ready:
            raise RuntimeError(readiness_error)

        monitor.goal_sent_at = time.monotonic()
        result["goal_sent_wall_unix"] = time.time()
        result["goal_sent"] = True
        print("[baseline] ROS ready; goal sent; observing for at most 100 seconds", flush=True)
        for _ in range(3):
            goal_message = _make_goal(GOAL, node)
            goal_publisher.publish(goal_message)
            send_deadline = time.monotonic() + 0.3
            while time.monotonic() < send_deadline:
                _spin_once(rclpy, node)

        observation_started = monitor.goal_sent_at
        observation_deadline = observation_started + OBSERVATION_TIMEOUT
        while time.monotonic() < observation_deadline and not monitor.goal_reached:
            _spin_once(rclpy, node)
        if monitor.goal_reached:
            # Allow one post-event odometry callback so the terminal metric is
            # based on a fresh state rather than a queued pre-event sample.
            settle_deadline = min(observation_deadline, time.monotonic() + 0.5)
            while (
                time.monotonic() < settle_deadline
                and monitor.last_odom_at is not None
                and monitor.goal_reached_at is not None
                and monitor.last_odom_at < monitor.goal_reached_at
            ):
                _spin_once(rclpy, node)
        result["elapsed_sec"] = time.monotonic() - observation_started
        result["observation_end_wall_unix"] = time.time()
        result["goal_reached"] = monitor.goal_reached
        result["odom_samples_after_goal"] = monitor.odom_samples_after_goal
        final_is_finite = bool(
            monitor.last_position
            and all(math.isfinite(value) for value in monitor.last_position)
        )
        if final_is_finite:
            result["goal_distance_m"] = math.sqrt(
                sum((monitor.last_position[index] - GOAL[index]) ** 2 for index in range(3))
            )
        verified = _verified_goal(monitor, time.monotonic())
        result["success"] = verified
        if not monitor.goal_reached:
            result["error"] = "observation timeout: goal_reached was not received"
        elif not verified:
            result["error"] = "goal_reached received but odometry verification failed"
    except Exception as error:
        if session_ownership_established and not session_started and _session_exists():
            # tmuxp can fail after creating the session.  The pre-launch
            # existence check means a session found here belongs to this run.
            session_started = True
        result["error"] = f"{type(error).__name__}: {error}"
    finally:
        if result["goal_sent_wall_unix"] is not None and result["observation_end_wall_unix"] is None:
            result["observation_end_wall_unix"] = time.time()
        if monitor is not None:
            result["odom_samples"] = monitor.odom_samples
            result["odom_samples_after_goal"] = monitor.odom_samples_after_goal
            result["max_displacement_m"] = monitor.max_displacement
            result["last_position"] = monitor.last_position
            if monitor.last_position and all(
                math.isfinite(value) for value in monitor.last_position
            ):
                result["goal_distance_m"] = math.sqrt(
                    sum(
                        (monitor.last_position[index] - GOAL[index]) ** 2
                        for index in range(3)
                    )
                )
            if monitor.goal_reached_at is not None and monitor.goal_sent_at is not None:
                result["goal_time_sec"] = monitor.goal_reached_at - monitor.goal_sent_at
            if monitor.last_odom_at is not None and monitor.goal_sent_at is not None:
                result["last_odom_after_goal_sec"] = monitor.last_odom_at - monitor.goal_sent_at
            result["goal_reached"] = monitor.goal_reached
            result["success"] = result["error"] is None and _verified_goal(monitor, time.monotonic())
            errors = [sample["error_m"] for sample in monitor.tracking_error_samples]
            result["tracking_error"] = {
                "topic": f"/{NAMESPACE}/setpoint_vis",
                "available": bool(errors),
                "sample_count": len(errors),
                "fresh_sample_count": len(errors),
                "stale_excluded_count": monitor.setpoint_stale_excluded,
                "max_age_sec": SETPOINT_MAX_AGE_SEC,
                "mean_m": (sum(errors) / len(errors)) if errors else None,
                "rmse_m": (math.sqrt(sum(value * value for value in errors) / len(errors))
                           if errors else None),
                "max_m": max(errors) if errors else None,
                "samples": monitor.tracking_error_samples,
                "reason": None if errors else "unavailable: no fresh finite setpoint/odometry pairs",
            }
            collision = monitor.model_states_collision.result()
            result["ground_truth"] = {
                "topic": MODEL_STATES_TOPIC,
                "clock": "co-sampled robot and obstacle poses; receipt time is monotonic",
                "available": collision["available"],
                "obstacle_geometry_source": "saved obstacles.json model names and box dimensions",
                "odom_trace": monitor.odom_trace,
                "collision": collision,
            }
        result["wall_elapsed_sec"] = time.monotonic() - wall_started
        if session_started:
            result["logs"] = _capture_logs(output_dir)
            result["instrumentation_error"] = "SANDO_INSTRUMENTATION_ERROR" in (
                output_dir / "tmux.log").read_text(encoding="utf-8", errors="replace")
            # The generated files were copied before launch and remain
            # available even when teardown is caused by a timeout.
            _copy_generated_files(output_dir)
            _kill_own_session()
        else:
            result["logs"] = None
        if goal_publisher is not None:
            node.destroy_publisher(goal_publisher)
        if node is not None:
            node.destroy_node()
        if rclpy_started:
            rclpy.shutdown()
        _write_json(output_dir / "result.json", result)
    return 0 if result["success"] and not result.get("instrumentation_error", False) else 2


def _scene_split(seed):
    if 0 <= seed <= 39:
        return "train"
    if 100 <= seed <= 109:
        return "validation"
    if 200 <= seed <= 229:
        return "test"
    raise ValueError("scene seed is outside the locked train/validation/test split")


def _evaluation_environment(base, method, policy=None, metrics=None):
    """Build the child launch environment without inheriting policy controls."""
    environment = dict(base)
    for name in ("SANDO_CORRIDOR_METHOD", "SANDO_CORRIDOR_POLICY", "SANDO_REPLAN_METRICS"):
        environment.pop(name, None)
    if method == "original":
        selected = "original"
    elif method == "previous":
        selected = "previous"
    else:
        selected = "learned"
        if policy is None:
            raise ValueError("a policy path is required for learned corridor methods")
        environment["SANDO_CORRIDOR_POLICY"] = str(Path(policy).resolve())
    environment["SANDO_CORRIDOR_METHOD"] = selected
    if metrics is not None:
        environment["SANDO_REPLAN_METRICS"] = str(Path(metrics).resolve())
    return environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dynamic-ratio", type=float, default=0.65)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--num-obstacles", type=int, default=50)
    parser.add_argument("--setup-bash", type=Path, required=True)
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--capture-round", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--capture-capacity", type=int, default=None)
    parser.add_argument("--sampling-protocol", choices=("uniform_reservoir_v1", "uniform_plus_diverse_v1"),
                        default="uniform_reservoir_v1")
    parser.add_argument("--method", choices=("original", "previous", "bc", "cost", "closed_loop"), default="original")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--metrics", type=Path)
    parser.add_argument("--scene-family", dest="scene_family",
                        choices=("unknown_dynamic", "static_forest", "known_dynamic"),
                        default="unknown_dynamic")
    parser.add_argument("--start-randomization", choices=("none", "train_box_v1"), default="none")
    parser.add_argument("--protocol-id", default="legacy")
    args = parser.parse_args()
    if not 0.0 <= args.dynamic_ratio <= 1.0:
        parser.error("--dynamic-ratio must be between 0 and 1")
    if args.num_obstacles <= 0:
        parser.error("--num-obstacles must be positive")
    if not args.setup_bash.exists():
        parser.error(f"setup bash not found: {args.setup_bash}")
    if args.method in ("bc", "cost", "closed_loop"):
        if args.policy is None or not args.policy.is_file():
            parser.error("--policy must name a file for learned corridor methods")
    try:
        return _run(args)
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
