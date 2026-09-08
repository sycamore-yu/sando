"""Scene families, information boundaries, and start sampling for integer capture.

Live racefix recapture keeps the legacy protocol.  This module is the
benchmark-aligned protocol: unknown-dynamic Gazebo is primary, forest
static worlds are the control, and RViz known-dynamic is a separate
privileged table.  Start randomization is for corpus generation only.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping, Sequence

FAMILIES = ("unknown_dynamic", "static_forest", "known_dynamic")
DIFFICULTIES = ("easy", "medium", "hard")
COUNT_TO_DIFFICULTY = {50: "easy", 100: "medium", 200: "hard"}
FOREST_ENV = {
    "easy": "easy_forest",
    "medium": "medium_forest",
    "hard": "hard_forest",
}
PROTOCOLS = ("legacy", "benchmark_aligned_v1")
START_SAMPLERS = ("none", "train_box_v1")
PROTOCOL_ID_ALIGNED = "benchmark_aligned_v1"
START_SAMPLER_VERSION = "box_v1"
NOMINAL_START = (0.0, 0.0, 2.0)
NOMINAL_YAW = 0.0
GOAL = (105.0, 0.0, 2.0)
START_BOX = {"x": (-1.0, 3.0), "y": (-2.0, 2.0), "z": (1.5, 2.5)}
ROBOT_BBOX_FULL_M = (0.2, 0.2, 0.2)
EXTRA_CLEARANCE_M = 0.5
MAX_START_ATTEMPTS = 32
DEFAULT_ALIGNED_FAMILIES = ("unknown_dynamic", "static_forest")


def difficulty_from_count(num_obstacles: int) -> str:
    if num_obstacles not in COUNT_TO_DIFFICULTY:
        raise ValueError("num_obstacles must be 50, 100, or 200")
    return COUNT_TO_DIFFICULTY[num_obstacles]


def launch_spec(
    family: str,
    num_obstacles: int,
    dynamic_ratio: float | None = None,
) -> dict[str, Any]:
    if family not in FAMILIES:
        raise ValueError(f"unknown scene family: {family}")
    difficulty = difficulty_from_count(num_obstacles)
    if family == "unknown_dynamic":
        ratio = 0.65 if dynamic_ratio is None else float(dynamic_ratio)
        if ratio not in (0.0, 0.65):
            raise ValueError("unknown_dynamic ratio must be 0 or 0.65")
        return {
            "family": family,
            "mode": "gazebo-dynamic",
            "env": "empty_wo_ground",
            "num_obstacles": num_obstacles,
            "dynamic_ratio": ratio,
            "publish_trajs": False,
            "trajs_topic": "/trajs_ground_truth",
            "environment_assumption": "static" if ratio == 0.0 else "dynamic",
            "information_boundary": "pointcloud_only",
            "difficulty": difficulty,
        }
    if family == "static_forest":
        return {
            "family": family,
            "mode": "gazebo",
            "env": FOREST_ENV[difficulty],
            "num_obstacles": 0,
            "dynamic_ratio": 0.0,
            "publish_trajs": False,
            "trajs_topic": "/trajs",
            "environment_assumption": "static",
            "information_boundary": "static_world_pointcloud",
            "difficulty": difficulty,
            "same_map_across_seeds": True,
        }
    return {
        "family": family,
        "mode": "rviz-only",
        "env": None,
        "num_obstacles": num_obstacles,
        "dynamic_ratio": 0.65,
        "publish_trajs": True,
        "trajs_topic": "/trajs",
        "environment_assumption": "dynamic",
        "information_boundary": "privileged_ground_truth_trajs",
        "difficulty": difficulty,
    }


def scene_id(
    family: str,
    seed: int,
    num_obstacles: int,
    dynamic_ratio: float,
    protocol: str = "legacy",
) -> str:
    if protocol not in PROTOCOLS:
        raise ValueError(f"unknown protocol: {protocol}")
    if protocol == "legacy" and family == "unknown_dynamic":
        return f"n{num_obstacles}-d{float(dynamic_ratio):g}-seed{seed}"
    if family == "static_forest":
        return f"static_forest-{difficulty_from_count(num_obstacles)}-seed{seed}"
    if family == "known_dynamic":
        return f"known_dynamic-n{num_obstacles}-d0.65-seed{seed}"
    return f"unknown_dynamic-n{num_obstacles}-d{float(dynamic_ratio):g}-seed{seed}"


def randomization_for_split(requested: str, split: str) -> str:
    if requested not in START_SAMPLERS:
        raise ValueError(f"unknown start sampler: {requested}")
    if split == "test" or requested == "none":
        return "none"
    if split not in ("train", "validation"):
        raise ValueError(f"unknown split: {split}")
    return requested


def _unit_interval(material: bytes, salt: bytes) -> float:
    digest = hashlib.sha256(material + salt).digest()
    return int.from_bytes(digest[:8], "big") / float(1 << 64)


def sample_start(scene_key: str, attempt: int = 0) -> tuple[float, float, float]:
    if attempt < 0:
        raise ValueError("attempt must be nonnegative")
    material = f"{scene_key}|{attempt}|{START_SAMPLER_VERSION}".encode()
    values = []
    for axis in ("x", "y", "z"):
        low, high = START_BOX[axis]
        values.append(low + _unit_interval(material, axis.encode()) * (high - low))
    return (values[0], values[1], values[2])


def _in_box(start: Sequence[float]) -> bool:
    for axis, value in zip(("x", "y", "z"), start):
        low, high = START_BOX[axis]
        if value < low or value > high:
            return False
    return True


def aabb_clear(
    start: Sequence[float],
    obstacles: Iterable[Mapping[str, Any]],
    robot_bbox: Sequence[float] = ROBOT_BBOX_FULL_M,
    extra: float = EXTRA_CLEARANCE_M,
) -> bool:
    if len(start) != 3 or len(robot_bbox) != 3:
        raise ValueError("start and robot bbox must have three components")
    half_robot = tuple(float(value) / 2.0 for value in robot_bbox)
    for obstacle in obstacles:
        center = (
            float(obstacle.get("x0", obstacle.get("x"))),
            float(obstacle.get("y0", obstacle.get("y"))),
            float(obstacle.get("z0", obstacle.get("z"))),
        )
        size = (
            float(obstacle["size_x"]),
            float(obstacle["size_y"]),
            float(obstacle["size_z"]),
        )
        if all(
            abs(start[axis] - center[axis])
            <= half_robot[axis] + size[axis] / 2.0 + extra
            for axis in range(3)
        ):
            return False
    return True


def accept_start(
    start: Sequence[float],
    family: str,
    obstacles: Iterable[Mapping[str, Any]] | None = None,
) -> bool:
    if family not in FAMILIES:
        raise ValueError(f"unknown scene family: {family}")
    if not _in_box(start):
        return False
    if family == "static_forest":
        # Forest worlds have no procedural JSON; the box is the launch clearing
        # near (0,0,2). Occupancy is not checked, so this is start-pose coverage
        # on the same map, not a free-space certificate.
        return True
    return aabb_clear(start, obstacles or ())


def resolve_start(
    scene_key: str,
    family: str,
    obstacles: Iterable[Mapping[str, Any]] | None,
    randomization: str,
) -> dict[str, Any]:
    if randomization == "none":
        return {
            "sampler": "none",
            "sampler_version": START_SAMPLER_VERSION,
            "proposed": list(NOMINAL_START),
            "accepted": list(NOMINAL_START),
            "yaw": NOMINAL_YAW,
            "attempts": 1,
            "rejected": [],
        }
    if randomization != "train_box_v1":
        raise ValueError(f"unknown start sampler: {randomization}")
    rejected: list[list[float]] = []
    for attempt in range(MAX_START_ATTEMPTS):
        proposed = sample_start(scene_key, attempt)
        if accept_start(proposed, family, obstacles):
            return {
                "sampler": randomization,
                "sampler_version": START_SAMPLER_VERSION,
                "proposed": list(proposed),
                "accepted": list(proposed),
                "yaw": NOMINAL_YAW,
                "attempts": attempt + 1,
                "rejected": rejected,
            }
        rejected.append(list(proposed))
    raise ValueError(f"start sampler exhausted after {MAX_START_ATTEMPTS} attempts")


def aligned_scene_configs(
    split: str,
    seeds: Sequence[int],
    counts: Sequence[int] = (50, 100, 200),
    families: Sequence[str] = DEFAULT_ALIGNED_FAMILIES,
) -> list[dict[str, Any]]:
    if split not in ("train", "validation", "test"):
        raise ValueError(f"unknown split: {split}")
    if any(family not in FAMILIES for family in families):
        raise ValueError("scene family is not supported")
    if not families:
        raise ValueError("at least one scene family is required")
    randomization = randomization_for_split("train_box_v1", split)
    rows: list[dict[str, Any]] = []
    for seed in seeds:
        if "unknown_dynamic" in families:
            for count in counts:
                rows.append(_aligned_row(split, seed, "unknown_dynamic", count, 0.65, randomization))
        if "static_forest" in families:
            for count in counts:
                rows.append(_aligned_row(split, seed, "static_forest", count, 0.0, randomization))
        if "known_dynamic" in families:
            for count in counts:
                rows.append(_aligned_row(split, seed, "known_dynamic", count, 0.65, randomization))
    return rows


def _aligned_row(
    split: str,
    seed: int,
    family: str,
    count: int,
    ratio: float,
    randomization: str,
) -> dict[str, Any]:
    spec = launch_spec(family, count, ratio)
    return {
        "split": split,
        "seed": seed,
        "num_obstacles": count,
        "dynamic_ratio": spec["dynamic_ratio"],
        "family": family,
        "protocol_id": PROTOCOL_ID_ALIGNED,
        "start_randomization": randomization,
        "information_boundary": spec["information_boundary"],
        "env": spec["env"],
        "difficulty": spec["difficulty"],
        "scene_id": scene_id(family, seed, count, spec["dynamic_ratio"], PROTOCOL_ID_ALIGNED),
    }
