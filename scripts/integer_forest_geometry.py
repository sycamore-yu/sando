"""Extract conservative collision AABBs from the installed forest SDF worlds."""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from pathlib import Path


def _numbers(text, count, name):
    try:
        values = [float(value) for value in (text or "").split()]
    except ValueError as error:
        raise ValueError(f"invalid {name}") from error
    if len(values) != count or any(not math.isfinite(value) for value in values):
        raise ValueError(f"invalid {name}")
    return values


def _dimension(collision):
    pose = collision.find("pose")
    if pose is not None and any(abs(value) > 1e-12 for value in _numbers(pose.text, 6, "collision pose")):
        raise ValueError("nonzero collision local pose is unsupported")
    geometry = collision.find("geometry")
    if geometry is None:
        raise ValueError("collision has no geometry")
    box = geometry.find("box")
    if box is not None:
        return _numbers(box.findtext("size"), 3, "box size")
    cylinder = geometry.find("cylinder")
    if cylinder is not None:
        radius = float(cylinder.findtext("radius")); length = float(cylinder.findtext("length"))
        if not math.isfinite(radius) or not math.isfinite(length) or radius <= 0 or length <= 0:
            raise ValueError("invalid cylinder dimensions")
        return [2 * radius, 2 * radius, length]
    plane = geometry.find("plane")
    if plane is not None:
        normal = _numbers(plane.findtext("normal"), 3, "plane normal")
        if normal != [0.0, 0.0, 1.0] and normal != [0.0, 0.0, -1.0]:
            raise ValueError("only horizontal planes are supported")
        size = _numbers(plane.findtext("size"), 2, "plane size")
        return [size[0], size[1], 0.0]
    raise ValueError("unsupported collision geometry")


def world_collision_geometry(world: str | Path, static: bool = True):
    root = ET.parse(world).getroot()
    result = []
    for model in root.findall("./world/model"):
        if not model.get("name") or any(item["name"] == model.get("name") for item in result):
            raise ValueError("forest model names must be unique and nonempty")
        model_pose = _numbers(model.findtext("pose", "0 0 0 0 0 0"), 6, "model pose")
        if any(abs(value) > 1e-12 for value in model_pose[3:]):
            raise ValueError("rotated model collision AABB is unsupported")
        for link in model.findall("./link"):
            if any(abs(value) > 1e-12 for value in _numbers(link.findtext("pose", "0 0 0 0 0 0"), 6, "link pose")):
                raise ValueError("nonzero link local pose is unsupported")
        if static and model.findtext("static", "0").strip() not in ("1", "true"):
            raise ValueError(f"model {model.get('name')} is not static")
        collisions = model.findall("./link/collision")
        if len(collisions) != 1:
            raise ValueError(f"model {model.get('name')} must have one collision")
        size = _dimension(collisions[0])
        if any(value < 0 for value in size) or size[0] <= 0 or size[1] <= 0:
            raise ValueError("invalid collision dimensions")
        result.append({"name": model.get("name"), "size_x": size[0], "size_y": size[1], "size_z": size[2]})
    if not result:
        raise ValueError("world has no collidable models")
    return result


def aabb_overlap(center_a, size_a, center_b, size_b):
    """Conservative overlap test for co-sampled model-state positions."""
    return all(abs(float(a) - float(b)) <= (float(sa) + float(sb)) / 2.0
               for a, sa, b, sb in zip(center_a, size_a, center_b, size_b))
