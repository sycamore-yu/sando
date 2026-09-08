"""Small, double precision corridor ranking policy shared by training and inference."""

from __future__ import annotations

import itertools
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Sequence

import torch
from torch import nn

FEATURE_SPEC = {
    "version": 1,
    "origin": "start_position",
    "spatial_scale": "max(1,max_map_extent)",
    "velocity": "segment_dt/scale",
    "acceleration": "segment_dt_squared/scale",
    "plane_count": "raw",
    "context_order": "start9_goal9_map6_dt5_factor",
}


def _finite(value: Any) -> None:
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    if isinstance(value, list):
        for child in value:
            _finite(child)
    elif isinstance(value, dict):
        for child in value.values():
            _finite(child)


def _array(value: Any, length: int, name: str) -> list[float]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{name} must have length {length}")
    result = [float(item) for item in value]
    if not all(math.isfinite(item) for item in result):
        raise ValueError(f"{name} contains a non-finite value")
    return result


def valid_assignments(instance: dict[str, Any]) -> list[tuple[int, ...]]:
    if instance.get("schema_version") != 1 or instance.get("n") != 5:
        raise ValueError("unsupported planning instance")
    if instance.get("norm") != "Linf" or instance.get("planner") != "SANDO":
        raise ValueError("unsupported planning stage")
    masks = instance.get("valid_mask")
    corridors = instance.get("corridors")
    if not isinstance(masks, list) or len(masks) != 5 or not isinstance(corridors, list) or len(corridors) != 5:
        raise ValueError("invalid corridor layers")
    choices: list[list[int]] = []
    choice_count = None
    for t in range(5):
        if not isinstance(masks[t], list) or len(masks[t]) == 0 or len(masks[t]) > 3:
            raise ValueError("each layer must have one to three choices")
        if len(corridors[t]) != len(masks[t]):
            raise ValueError("mask and corridor dimensions differ")
        if choice_count is None:
            choice_count = len(masks[t])
        elif choice_count != len(masks[t]):
            raise ValueError("corridor choice count must be consistent across time")
        layer: list[int] = []
        for p, allowed in enumerate(masks[t]):
            if not isinstance(allowed, bool):
                raise ValueError("valid_mask must contain booleans")
            planes = corridors[t][p].get("planes") if isinstance(corridors[t][p], dict) else None
            if not isinstance(planes, list) or (bool(planes) != allowed):
                raise ValueError("valid_mask does not match corridor contents")
            for plane in planes:
                _array(plane, 4, "plane")
                normal = math.hypot(math.hypot(float(plane[0]), float(plane[1])), float(plane[2]))
                if not math.isfinite(normal) or normal <= 0:
                    raise ValueError("corridor plane normal is invalid")
            if allowed:
                layer.append(p)
        choices.append(layer)
    if any(not layer for layer in choices):
        return []
    return [tuple(candidate) for candidate in itertools.product(*choices)]


def _instance_arrays(instance: dict[str, Any]) -> tuple[list[float], list[float], list[float], float, float]:
    start = _array(instance.get("start"), 9, "start")
    goal = _array(instance.get("goal"), 9, "goal")
    bounds = _array(instance.get("map_bounds"), 6, "map_bounds")
    if any(bounds[i] > bounds[i + 1] for i in range(0, 6, 2)):
        raise ValueError("map bounds are unordered")
    initial_dt = float(instance.get("initial_dt"))
    dc = float(instance.get("dc"))
    segment_dt = float(instance.get("segment_dt"))
    factor = float(instance.get("factor"))
    if not math.isfinite(initial_dt) or initial_dt < 0 or not math.isfinite(dc) or dc <= 0 or not math.isfinite(factor) or factor <= 0:
        raise ValueError("invalid segment time or factor")
    expected_dt = max(initial_dt, 2.0 * dc) * factor
    if not math.isfinite(segment_dt) or segment_dt <= 0 or abs(segment_dt - expected_dt) > 2e-6 * max(1.0, abs(expected_dt)):
        raise ValueError("segment_dt does not match segmentDuration")
    scale = max(1.0, *(bounds[i + 1] - bounds[i] for i in range(0, 6, 2)))
    if not math.isfinite(scale):
        raise ValueError("invalid map extent")
    return start, goal, bounds, segment_dt, scale


def normalized_planes(instance: dict[str, Any]) -> list[list[list[list[float]]]]:
    start, _, _, _, scale = _instance_arrays(instance)
    result: list[list[list[list[float]]]] = []
    for layer in instance["corridors"]:
        encoded_layer: list[list[list[float]]] = []
        for corridor in layer:
            encoded: list[list[float]] = []
            for plane in corridor["planes"]:
                norm = math.hypot(math.hypot(float(plane[0]), float(plane[1])), float(plane[2]))
                unit = [float(plane[i]) / norm for i in range(3)]
                shifted = (float(plane[3]) / norm - sum(unit[i] * start[i] for i in range(3))) / scale
                if not all(math.isfinite(value) for value in (*unit, shifted)):
                    raise ValueError("normalized plane is non-finite")
                encoded.append(unit + [shifted])
            encoded_layer.append(encoded)
        result.append(encoded_layer)
    return result


def context_features(instance: dict[str, Any]) -> list[float]:
    start, goal, bounds, dt, scale = _instance_arrays(instance)
    features: list[float] = []
    for state in (start, goal):
        features.extend((state[i] - start[i]) / scale for i in range(3))
        features.extend(state[i] * dt / scale for i in range(3, 6))
        features.extend(state[i] * dt * dt / scale for i in range(6, 9))
    features.extend((bounds[i] - start[i // 2]) / scale for i in range(6))
    features.extend([dt] * 5)
    features.append(float(instance["factor"]))
    if len(features) != 30 or not all(math.isfinite(x) for x in features):
        raise ValueError("invalid context features")
    return features


def _layer_json(module: nn.Linear) -> dict[str, Any]:
    return {
        "weight": module.weight.detach().cpu().tolist(),
        "bias": module.bias.detach().cpu().tolist(),
    }


class CorridorPolicy(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.plane1 = nn.Linear(4, 32, dtype=torch.float64)
        self.plane2 = nn.Linear(32, 32, dtype=torch.float64)
        self.score1 = nn.Linear(355, 128, dtype=torch.float64)
        self.score2 = nn.Linear(128, 64, dtype=torch.float64)
        self.score3 = nn.Linear(64, 1, dtype=torch.float64)

    def _encode_corridor(self, planes: Sequence[Sequence[float]]) -> torch.Tensor:
        if not planes:
            raise ValueError("cannot encode an empty corridor")
        values = torch.as_tensor(planes, dtype=torch.float64)
        hidden = torch.relu(self.plane2(torch.relu(self.plane1(values))))
        return torch.cat((hidden.mean(dim=0), hidden.max(dim=0).values, torch.tensor([float(len(planes))], dtype=torch.float64)))

    def _feature_matrix(self, instance: dict[str, Any], assignments: Sequence[Sequence[int]]) -> torch.Tensor:
        if not assignments:
            return torch.empty((0, 355), dtype=torch.float64)
        planes = normalized_planes(instance)
        encodings = [[self._encode_corridor(corridor) if corridor else None
                      for corridor in layer] for layer in planes]
        context = torch.as_tensor(context_features(instance), dtype=torch.float64)
        result = torch.stack([torch.cat((*[encodings[t][int(assignment[t])] for t in range(5)], context)) for assignment in assignments])
        if result.shape[1] != 355 or not torch.isfinite(result).all():
            raise ValueError("invalid policy feature matrix")
        return result

    def score_all(self, instance: dict[str, Any]) -> tuple[list[tuple[int, ...]], torch.Tensor]:
        assignments = valid_assignments(instance)
        features = self._feature_matrix(instance, assignments)
        hidden = torch.relu(self.score1(features))
        hidden = torch.relu(self.score2(hidden))
        scores = self.score3(hidden).reshape(-1)
        if not torch.isfinite(scores).all():
            raise ValueError("non-finite network score")
        return assignments, scores

    def features(self, instance: dict[str, Any], assignment: Sequence[int]) -> torch.Tensor:
        assignments = valid_assignments(instance)
        candidate = tuple(int(x) for x in assignment)
        if candidate not in assignments:
            raise ValueError("assignment is invalid")
        return self._feature_matrix(instance, [candidate])[0]

    def score_assignment(self, instance: dict[str, Any], assignment: Sequence[int]) -> torch.Tensor:
        assignments, scores = self.score_all(instance)
        try:
            return scores[assignments.index(tuple(int(x) for x in assignment))]
        except ValueError as error:
            raise ValueError("assignment is invalid") from error

    def scores(self, instance: dict[str, Any]) -> list[tuple[tuple[int, ...], float]]:
        with torch.no_grad():
            assignments, scores = self.score_all(instance)
            return [(assignment, float(score)) for assignment, score in zip(assignments, scores)]

    def rank(self, instance: dict[str, Any]) -> list[tuple[int, ...]]:
        return [assignment for assignment, _ in sorted(self.scores(instance), key=lambda item: (-item[1], item[0]))]

    def to_json(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        result = {
            "schema_version": 1,
            "kind": "sando_corridor_policy",
            "n": 5,
            "norm": "Linf",
            "feature_spec": FEATURE_SPEC.copy(),
            "layers": {
                "plane1": _layer_json(self.plane1),
                "plane2": _layer_json(self.plane2),
                "score1": _layer_json(self.score1),
                "score2": _layer_json(self.score2),
                "score3": _layer_json(self.score3),
            },
            "metadata": metadata or {},
        }
        _finite(result)
        return result

    @classmethod
    def from_json(cls, value: dict[str, Any] | str | Path) -> "CorridorPolicy":
        if isinstance(value, (str, Path)):
            with Path(value).open() as stream:
                value = json.load(stream)
        _finite(value)
        if not isinstance(value, dict) or value.get("schema_version") != 1 or value.get("kind") != "sando_corridor_policy" or value.get("n") != 5 or value.get("norm") != "Linf":
            raise ValueError("invalid corridor policy identity")
        if value.get("feature_spec") != FEATURE_SPEC or not isinstance(value.get("metadata"), dict):
            raise ValueError("invalid corridor policy feature specification")
        shapes = {"plane1": (4, 32), "plane2": (32, 32), "score1": (355, 128), "score2": (128, 64), "score3": (64, 1)}
        layers = value.get("layers")
        if not isinstance(layers, dict) or set(layers) != set(shapes):
            raise ValueError("layers must be an object")
        result = cls()
        for name, (input_size, output_size) in shapes.items():
            layer = layers.get(name)
            if not isinstance(layer, dict) or "weight" not in layer or "bias" not in layer:
                raise ValueError(f"missing layer {name}")
            weight = layer["weight"]
            bias = layer["bias"]
            if not isinstance(weight, list) or len(weight) != output_size or any(not isinstance(row, list) or len(row) != input_size for row in weight) or not isinstance(bias, list) or len(bias) != output_size:
                raise ValueError(f"wrong dimensions for layer {name}")
            if any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)) for row in weight for item in row) or any(isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)) for item in bias):
                raise ValueError(f"non-finite or non-numeric values for layer {name}")
            module = getattr(result, name)
            with torch.no_grad():
                module.weight.copy_(torch.as_tensor(weight, dtype=torch.float64))
                module.bias.copy_(torch.as_tensor(bias, dtype=torch.float64))
        return result

    @classmethod
    def load(cls, path: str | Path) -> "CorridorPolicy":
        return cls.from_json(path)
