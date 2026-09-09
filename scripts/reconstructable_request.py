"""Reconstructable planning-request snapshots for joint time queries.

kind=sando_reconstructable_request, schema_version=1.

The frozen goal is the planner local_E state (nine numbers: position,
velocity, acceleration), not the mission terminal.  Changing factor
requires rebuilding corridors from observation fields; this module
never calls Gurobi and never invents voxels.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

KIND = "sando_reconstructable_request"
SCHEMA_VERSION = 1
GOAL_FRAME = "local_E"
FACTOR_REL_TOL = 2e-6

IDENTITY_FIELDS = (
    "source_id",
    "config_id",
    "scene_id",
    "episode_id",
    "request_id",
    "split",
    "scene_family",
    "difficulty",
)
TIMESTAMP_FIELDS = ("planning_start_time", "observation_time", "t0")
TIME_INPUT_FIELDS = ("n", "initial_dt", "dc", "original_factor", "original_segment_dt")
SAFETY_FIELDS = (
    "v_max",
    "a_max",
    "j_max",
    "jerk_smooth_weight",
    "environment_assumption",
    "norm",
    "planner",
    "num_N",
)
CORRIDOR_FIELDS = (
    "global_path",
    "map_bounds",
    "visible_map",
    "obst_pos",
    "obst_bbox",
    "obst_max_vel",
    "sfc",
)
# Observation fields required to rebuild corridors at a new factor.
REBUILD_FIELDS = (
    "visible_map",
    "obst_pos",
    "obst_bbox",
    "global_path",
    "environment_assumption",
    "map_bounds",
    "start",
    "goal",
    "initial_dt",
    "dc",
    "n",
    "v_max",
    "a_max",
    "j_max",
)
COUNT_TO_DIFFICULTY = {50: "easy", 100: "medium", 200: "hard"}
FOREST_ENV_TO_DIFFICULTY = {
    "easy_forest": "easy",
    "medium_forest": "medium",
    "hard_forest": "hard",
}


def time_query(n: Any, initial_dt: Any, dc: Any, factor: Any) -> dict[str, Any]:
    """Same duration formula as include/sando/segment_time.hpp.

    d0 = max(initial_dt, 2 * dc)
    segment_dt = d0 * factor
    T = n * segment_dt
    layer i ends at (i + 1) * segment_dt
    """
    n_value = _positive_int(n, "n")
    initial = _finite_number(initial_dt, "initial_dt")
    dc_value = _finite_number(dc, "dc")
    factor_value = _finite_number(factor, "factor")
    if initial < 0.0:
        raise ValueError("invalid segment time inputs")
    if dc_value <= 0.0 or factor_value <= 0.0:
        raise ValueError("invalid segment time inputs")
    d0 = max(initial, 2.0 * dc_value)
    segment_dt = d0 * factor_value
    horizon = n_value * segment_dt
    if not math.isfinite(segment_dt) or segment_dt <= 0.0 or not math.isfinite(horizon):
        raise ValueError("invalid actual segment duration")
    layer_end_times = [(i + 1) * segment_dt for i in range(n_value)]
    if any(not math.isfinite(value) for value in layer_end_times):
        raise ValueError("invalid actual segment duration")
    return {
        "d0": d0,
        "segment_dt": segment_dt,
        "T": horizon,
        "layer_end_times": layer_end_times,
        "n": n_value,
        "initial_dt": initial,
        "dc": dc_value,
        "factor": factor_value,
    }


def missing_observation_fields(snapshot: Mapping[str, Any] | None) -> list[str]:
    """Sorted rebuild fields that are null/absent on a snapshot."""
    missing = []
    for name in REBUILD_FIELDS:
        if _is_missing(_field_value(snapshot, name), name):
            missing.append(name)
    return missing


def from_planning_instance(
    instance: dict[str, Any],
    run_sidecars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a reconstructable snapshot.  Does not invent voxels."""
    if not isinstance(instance, dict):
        raise ValueError("planning instance must be an object")
    record = instance.get("instance") if isinstance(instance.get("instance"), dict) else instance
    config = _sidecar(run_sidecars, "config", "config.json")
    capture = _sidecar(run_sidecars, "capture_config", "capture_config.json")
    obstacles = _sidecar(run_sidecars, "obstacles", "obstacles.json")
    capture_meta = _mapping(capture).get("metadata")
    outcome = _mapping(record.get("outcome"))
    outcome_capture = _mapping(outcome.get("capture"))
    reconstructable = _mapping(outcome.get("reconstructable"))

    identity = {name: None for name in IDENTITY_FIELDS}
    identity["source_id"] = _first_text(
        record.get("source_id"), outcome_capture.get("source_id"), _mapping(capture_meta).get("source_id")
    )
    identity["config_id"] = _first_text(
        record.get("config_id"), outcome_capture.get("config_id"), _mapping(capture_meta).get("config_id")
    )
    identity["scene_id"] = _first_text(
        record.get("scene_id"), outcome_capture.get("scene_id"), _mapping(capture_meta).get("scene_id"),
        _mapping(config).get("scene_id"),
    )
    identity["episode_id"] = _first_text(
        record.get("episode_id"), outcome_capture.get("episode_id"), _mapping(capture_meta).get("episode_id")
    )
    identity["request_id"] = _text_or_none(record.get("request_id"))
    identity["split"] = _first_text(
        outcome_capture.get("split"), _mapping(capture_meta).get("split"), record.get("split")
    )
    identity["scene_family"] = _first_text(
        outcome_capture.get("scene_family"),
        _mapping(capture_meta).get("scene_family"),
        _mapping(config).get("scene_family"),
        _family_from_scene(identity["scene_id"]),
    )
    identity["difficulty"] = _first_text(
        outcome_capture.get("difficulty"),
        _mapping(capture_meta).get("difficulty"),
        _mapping(config).get("difficulty"),
        _difficulty_from_sources(identity["scene_id"], identity["scene_family"], config),
    )

    start = _state9(record.get("start"))
    goal = _state9(record.get("goal"))
    timestamps = {name: _optional_finite(record.get(name)) for name in TIMESTAMP_FIELDS}
    n_value = _optional_positive_int(record.get("n"))
    time_inputs = {
        "n": n_value,
        "initial_dt": _optional_finite(record.get("initial_dt")),
        "dc": _optional_finite(record.get("dc")),
        "original_factor": _optional_finite(record.get("factor")),
        "original_segment_dt": _optional_finite(record.get("segment_dt")),
    }
    obst_pos, obst_bbox = _obstacles_from_sidecar(obstacles)
    environment_assumption = _first_text(
        _mapping(config).get("environment_assumption"),
        record.get("environment_assumption"),
        outcome_capture.get("environment_assumption"),
        reconstructable.get("environment_assumption"),
    )
    information_boundary = _first_text(
        outcome_capture.get("information_boundary"),
        _mapping(capture_meta).get("information_boundary"),
        _mapping(config).get("information_boundary"),
    )
    safety = {name: None for name in SAFETY_FIELDS}
    safety["v_max"] = _optional_finite(
        _first_present(record.get("v_max"), reconstructable.get("v_max"), _mapping(config).get("v_max"))
    )
    safety["a_max"] = _optional_finite(
        _first_present(record.get("a_max"), reconstructable.get("a_max"), _mapping(config).get("a_max"))
    )
    safety["j_max"] = _optional_finite(
        _first_present(record.get("j_max"), reconstructable.get("j_max"), _mapping(config).get("j_max"))
    )
    safety["jerk_smooth_weight"] = _optional_finite(
        _first_present(
            record.get("jerk_smooth_weight"),
            reconstructable.get("jerk_smooth_weight"),
            _mapping(config).get("jerk_smooth_weight"),
        )
    )
    safety["environment_assumption"] = environment_assumption or reconstructable.get(
        "environment_assumption"
    )
    safety["norm"] = _first_text(record.get("norm"), _mapping(config).get("norm"))
    safety["planner"] = _first_text(record.get("planner"), _mapping(config).get("local_planner"))
    safety["num_N"] = _optional_positive_int(_first_present(record.get("num_N"), n_value))

    corridor_build = {name: None for name in CORRIDOR_FIELDS}
    corridor_build["global_path"] = _points3(
        record.get("global_path") if record.get("global_path") is not None else reconstructable.get("global_path")
    )
    corridor_build["map_bounds"] = _bounds6(record.get("map_bounds"))
    corridor_build["visible_map"] = _visible_map(
        record.get("visible_map") if record.get("visible_map") is not None else reconstructable.get("visible_map")
    )
    corridor_build["obst_pos"] = obst_pos if obst_pos is not None else _points3(record.get("obst_pos"))
    corridor_build["obst_bbox"] = obst_bbox if obst_bbox is not None else _points3(record.get("obst_bbox"))
    corridor_build["obst_max_vel"] = _optional_finite(
        _first_present(record.get("obst_max_vel"), _mapping(config).get("obst_max_vel"))
    )
    corridor_build["sfc"] = _sfc_params(record, config)

    same_map = identity["scene_family"] == "static_forest"
    config_identity = {
        "source_id": identity["source_id"],
        "config_id": identity["config_id"],
        "protocol_id": _first_text(
            outcome_capture.get("protocol_id"),
            _mapping(capture_meta).get("protocol_id"),
            _mapping(config).get("protocol_id"),
        ),
        "model_version": _first_text(
            outcome_capture.get("model_version"),
            _mapping(capture_meta).get("model_version"),
            _mapping(config).get("model_version"),
        ),
        "information_boundary": information_boundary,
        "same_map_across_seeds": same_map if identity["scene_family"] is not None else None,
        "seed": _optional_int(_first_present(_mapping(config).get("seed"), _seed_from_scene(identity["scene_id"]))),
        "factor_id": _text_or_none(record.get("factor_id")),
    }

    snapshot = {
        "kind": KIND,
        "schema_version": SCHEMA_VERSION,
        "goal_frame": GOAL_FRAME,
        "identity": identity,
        "start": start,
        "goal": goal,
        "timestamps": timestamps,
        "time_inputs": time_inputs,
        "safety": safety,
        "corridor_build": corridor_build,
        "config_identity": config_identity,
        "information_boundary": information_boundary,
        "original_outcome": {
            "status": outcome.get("status") if "status" in outcome else None,
            "residuals": outcome.get("residuals") if "residuals" in outcome else None,
            "objective": outcome.get("objective") if "objective" in outcome else None,
        },
        "missing_fields": [],
    }
    snapshot["missing_fields"] = _schema_missing(snapshot)
    return snapshot


def query(
    snapshot: Mapping[str, Any],
    factor: Any,
    original_instance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Query times at factor.  Same-factor copies outcome; new factor never invents maps."""
    if not isinstance(snapshot, Mapping):
        raise ValueError("snapshot must be an object")
    time_inputs = _mapping(snapshot.get("time_inputs"))
    times = time_query(time_inputs.get("n"), time_inputs.get("initial_dt"), time_inputs.get("dc"), factor)
    record = {
        "factor": times["factor"],
        "d0": times["d0"],
        "segment_dt": times["segment_dt"],
        "T": times["T"],
        "layer_end_times": times["layer_end_times"],
        "classification": None,
        "missing_fields": [],
        "status": None,
        "residuals": None,
        "objective": None,
        "original_segment_dt_matches_formula": None,
    }
    original_factor = _optional_finite(time_inputs.get("original_factor"))
    if original_factor is not None and _relative_close(times["factor"], original_factor):
        record["classification"] = "same_factor_reference"
        original = original_instance.get("instance") if isinstance(original_instance, Mapping) and isinstance(
            original_instance.get("instance"), dict
        ) else original_instance
        original_dt = None
        if isinstance(original, Mapping):
            original_dt = _optional_finite(original.get("segment_dt"))
            outcome = _mapping(original.get("outcome"))
            if "status" in outcome:
                record["status"] = outcome.get("status")
            if "residuals" in outcome:
                record["residuals"] = outcome.get("residuals")
            if "objective" in outcome:
                record["objective"] = outcome.get("objective")
        if original_dt is None:
            original_dt = _optional_finite(time_inputs.get("original_segment_dt"))
        if record["status"] is None and record["residuals"] is None and record["objective"] is None:
            stored = _mapping(snapshot.get("original_outcome"))
            record["status"] = stored.get("status")
            record["residuals"] = stored.get("residuals")
            record["objective"] = stored.get("objective")
        record["original_segment_dt"] = original_dt
        record["original_segment_dt_matches_formula"] = (
            original_dt is not None and _relative_close(times["segment_dt"], original_dt)
        )
        return record

    missing = missing_observation_fields(snapshot)
    record["missing_fields"] = missing
    if missing:
        record["classification"] = "blocked_missing_observation"
        return record
    record["classification"] = "computed_times"
    return record


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid segment time inputs")
    if value <= 0 or int(value) != value:
        raise ValueError("invalid segment time inputs")
    return int(value)


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("invalid segment time inputs")
    return float(value)


def _optional_finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _optional_positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if value <= 0 or int(value) != value:
        return None
    return int(value)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if int(value) != value:
        return None
    return int(value)


def _relative_close(left: float, right: float, tol: float = FACTOR_REL_TOL) -> bool:
    return abs(left - right) <= tol * max(1.0, abs(right), abs(left))


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _sidecar(run_sidecars: dict[str, Any] | None, *names: str) -> Any:
    if not isinstance(run_sidecars, dict):
        return None
    for name in names:
        if name in run_sidecars and run_sidecars[name] is not None:
            return run_sidecars[name]
    return None


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _text_or_none(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        if int(value) == value:
            return str(int(value))
        return str(value)
    text = str(value).strip()
    return text or None


def _first_text(*values: Any) -> str | None:
    for value in values:
        text = _text_or_none(value)
        if text is not None:
            return text
    return None


def _state9(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 9:
        return None
    numbers = [_optional_finite(item) for item in value]
    if any(item is None for item in numbers):
        return None
    return [float(item) for item in numbers]


def _bounds6(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) != 6:
        return None
    numbers = [_optional_finite(item) for item in value]
    if any(item is None for item in numbers):
        return None
    return [float(item) for item in numbers]


def _points3(value: Any) -> list[list[float]] | None:
    if not isinstance(value, list):
        return None
    points = []
    for item in value:
        if not isinstance(item, list) or len(item) != 3:
            return None
        numbers = [_optional_finite(part) for part in item]
        if any(part is None for part in numbers):
            return None
        points.append([float(part) for part in numbers])
    return points


def _visible_map(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (list, dict)) and len(value) == 0:
        return None
    return value


def _obstacles_from_sidecar(obstacles: Any) -> tuple[list[list[float]] | None, list[list[float]] | None]:
    if not isinstance(obstacles, list) or not obstacles:
        return None, None
    positions = []
    boxes = []
    for item in obstacles:
        if not isinstance(item, dict):
            return None, None
        pos = [
            _optional_finite(item.get("x0", item.get("x"))),
            _optional_finite(item.get("y0", item.get("y"))),
            _optional_finite(item.get("z0", item.get("z"))),
        ]
        box = [
            _optional_finite(item.get("size_x")),
            _optional_finite(item.get("size_y")),
            _optional_finite(item.get("size_z")),
        ]
        if any(part is None for part in pos) or any(part is None for part in box):
            return None, None
        positions.append([float(part) for part in pos])
        boxes.append([float(part) for part in box])
    return positions, boxes


def _sfc_params(record: Mapping[str, Any], config: Mapping[str, Any] | None) -> dict[str, Any] | None:
    source = _mapping(record.get("sfc")) if isinstance(record.get("sfc"), dict) else {}
    cfg = _mapping(config)
    values = {
        "sfc_size": source.get("sfc_size", record.get("sfc_size", cfg.get("sfc_size"))),
        "dyn_base_inflation_m": source.get(
            "dyn_base_inflation_m", record.get("dyn_base_inflation_m", cfg.get("dyn_base_inflation_m"))
        ),
        "inflate_unknown_boundary": source.get(
            "inflate_unknown_boundary",
            record.get("inflate_unknown_boundary", cfg.get("inflate_unknown_boundary")),
        ),
    }
    if all(value is None for value in values.values()):
        return None
    return values


def _family_from_scene(scene_id: str | None) -> str | None:
    if not scene_id:
        return None
    if scene_id.startswith("static_forest"):
        return "static_forest"
    if scene_id.startswith("unknown_dynamic") or scene_id.startswith("n"):
        return "unknown_dynamic"
    if scene_id.startswith("known_dynamic"):
        return "known_dynamic"
    return None


def _difficulty_from_sources(scene_id: str | None, family: str | None, config: Mapping[str, Any] | None) -> str | None:
    cfg = _mapping(config)
    env = _text_or_none(cfg.get("environment"))
    if env in FOREST_ENV_TO_DIFFICULTY:
        return FOREST_ENV_TO_DIFFICULTY[env]
    count = _optional_int(cfg.get("num_obstacles"))
    if family == "unknown_dynamic" and count in COUNT_TO_DIFFICULTY:
        return COUNT_TO_DIFFICULTY[count]
    if not scene_id:
        return None
    parts = scene_id.split("-")
    if family == "static_forest" or scene_id.startswith("static_forest"):
        if len(parts) >= 2 and parts[1] in ("easy", "medium", "hard"):
            return parts[1]
    for part in parts:
        if part.startswith("n") and part[1:].isdigit():
            count = int(part[1:])
            if count in COUNT_TO_DIFFICULTY:
                return COUNT_TO_DIFFICULTY[count]
    return None


def _seed_from_scene(scene_id: str | None) -> int | None:
    if not scene_id or "seed" not in scene_id:
        return None
    tail = scene_id.rsplit("seed", 1)[-1]
    if tail.isdigit():
        return int(tail)
    return None


def _field_value(snapshot: Mapping[str, Any] | None, name: str) -> Any:
    if not isinstance(snapshot, Mapping):
        return None
    if name in ("start", "goal"):
        return snapshot.get(name)
    time_inputs = _mapping(snapshot.get("time_inputs"))
    if name in TIME_INPUT_FIELDS:
        return time_inputs.get(name)
    safety = _mapping(snapshot.get("safety"))
    if name in SAFETY_FIELDS:
        return safety.get(name)
    corridor = _mapping(snapshot.get("corridor_build"))
    if name in CORRIDOR_FIELDS:
        return corridor.get(name)
    identity = _mapping(snapshot.get("identity"))
    if name in IDENTITY_FIELDS:
        return identity.get(name)
    if name == "information_boundary":
        return snapshot.get("information_boundary")
    return snapshot.get(name)


def _is_missing(value: Any, name: str) -> bool:
    if value is None:
        return True
    if name in ("start", "goal"):
        return _state9(value) is None
    if name == "map_bounds":
        return _bounds6(value) is None
    if name in ("initial_dt", "dc", "v_max", "a_max", "j_max", "jerk_smooth_weight", "obst_max_vel"):
        return _optional_finite(value) is None
    if name in ("n", "num_N"):
        return _optional_positive_int(value) is None
    if name in ("visible_map",):
        return _visible_map(value) is None
    if name == "global_path":
        points = _points3(value)
        return points is None or len(points) == 0
    if name in ("obst_pos", "obst_bbox"):
        return _points3(value) is None
    if name == "sfc":
        return not isinstance(value, dict) or all(item is None for item in value.values())
    if isinstance(value, str):
        return not value.strip()
    return False


def _schema_missing(snapshot: Mapping[str, Any]) -> list[str]:
    missing = []
    identity = _mapping(snapshot.get("identity"))
    for name in IDENTITY_FIELDS:
        if _is_missing(identity.get(name), name):
            missing.append(name)
    for name in ("start", "goal"):
        if _is_missing(snapshot.get(name), name):
            missing.append(name)
    timestamps = _mapping(snapshot.get("timestamps"))
    for name in TIMESTAMP_FIELDS:
        if _is_missing(timestamps.get(name), name):
            missing.append(name)
    time_inputs = _mapping(snapshot.get("time_inputs"))
    for name in TIME_INPUT_FIELDS:
        if _is_missing(time_inputs.get(name), name):
            missing.append(name)
    safety = _mapping(snapshot.get("safety"))
    for name in SAFETY_FIELDS:
        if _is_missing(safety.get(name), name):
            missing.append(name)
    corridor = _mapping(snapshot.get("corridor_build"))
    for name in CORRIDOR_FIELDS:
        if _is_missing(corridor.get(name), name):
            missing.append(name)
    if _is_missing(snapshot.get("information_boundary"), "information_boundary"):
        missing.append("information_boundary")
    config_identity = snapshot.get("config_identity")
    if not isinstance(config_identity, dict):
        missing.append("config_identity")
    return sorted(set(missing))
