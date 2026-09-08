"""Select planning instances for the official and development sampling protocols."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Sequence

from integer_set_supervision import CONFIG


def _vector(instance: dict[str, Any], name: str, start: int, stop: int) -> tuple[float, ...]:
    values = instance.get(name)
    if not isinstance(values, list) or len(values) < stop:
        raise ValueError(f"{name} is too short")
    return tuple(float(values[i]) for i in range(start, stop))


def request_key(instance: dict[str, Any]) -> tuple[Any, ...]:
    return (instance.get("scene_id"), instance.get("episode_id"), instance.get("request_id"))


def request_feature(instance: dict[str, Any]) -> tuple[float, ...]:
    start = _vector(instance, "start", 0, 6)
    mask = instance.get("valid_mask")
    mask_bits = []
    if isinstance(mask, list):
        for row in mask:
            for allowed in row:
                mask_bits.append(1.0 if allowed else 0.0)
    return start + tuple(mask_bits)


def _distance(left: Sequence[float], right: Sequence[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def _stable_order(records: Sequence[dict[str, Any]], seed: str) -> list[int]:
    scored = []
    for index, record in enumerate(records):
        instance = record["instance"] if "instance" in record else record
        key = "|".join(map(str, request_key(instance)))
        digest = hashlib.sha256(f"{seed}:{key}:{index}".encode()).hexdigest()
        scored.append((digest, index))
    scored.sort()
    return [index for _, index in scored]


def select_instances(records: Sequence[dict[str, Any]], protocol: str, capacity: int,
                     seed: str = "uniform_reservoir_v1") -> list[dict[str, Any]]:
    if capacity <= 0:
        raise ValueError("capacity must be positive")
    if protocol == "uniform_reservoir_v1":
        order = _stable_order(records, seed)
        chosen = order[:capacity]
        return [records[index] for index in sorted(chosen)]
    if protocol != "uniform_plus_diverse_v1":
        raise ValueError("unknown sampling protocol")
    uniform_n = max(1, capacity // 2)
    uniform = select_instances(records, "uniform_reservoir_v1", min(uniform_n, len(records)), seed)
    selected = list(uniform)
    selected_keys = {request_key(item["instance"] if "instance" in item else item) for item in selected}
    remaining = []
    for record in records:
        instance = record["instance"] if "instance" in record else record
        if request_key(instance) in selected_keys:
            continue
        remaining.append(record)
    while len(selected) < min(capacity, len(records)) and remaining:
        selected_features = [request_feature(item["instance"] if "instance" in item else item) for item in selected]
        best_index = 0
        best_score = -1.0
        for index, record in enumerate(remaining):
            instance = record["instance"] if "instance" in record else record
            feature = request_feature(instance)
            score = min(_distance(feature, other) for other in selected_features)
            if score > best_score:
                best_score = score
                best_index = index
        chosen = remaining.pop(best_index)
        selected.append(chosen)
        selected_keys.add(request_key(chosen["instance"] if "instance" in chosen else chosen))
    return selected


OFFICIAL_CAPACITY_ROUND0 = int(CONFIG["official_capture_capacity_round0"])
DEV_CAPACITY_ROUND0 = int(CONFIG["dev_capture_capacity_round0"])
