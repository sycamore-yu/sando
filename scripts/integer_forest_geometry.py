"""Extract collision geometry from installed forest SDF worlds.

Cylinders keep radius/height (not only enclosing AABB) so online safety
metrics can use geometry-aware clearance instead of AABB false positives.
"""
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


def _geometry(collision):
    pose = collision.find("pose")
    if pose is not None and any(abs(value) > 1e-12 for value in _numbers(pose.text, 6, "collision pose")):
        raise ValueError("nonzero collision local pose is unsupported")
    geometry = collision.find("geometry")
    if geometry is None:
        raise ValueError("collision has no geometry")
    box = geometry.find("box")
    if box is not None:
        size = _numbers(box.findtext("size"), 3, "box size")
        return {
            "shape": "box",
            "size_x": size[0],
            "size_y": size[1],
            "size_z": size[2],
        }
    cylinder = geometry.find("cylinder")
    if cylinder is not None:
        radius = float(cylinder.findtext("radius"))
        length = float(cylinder.findtext("length"))
        if not math.isfinite(radius) or not math.isfinite(length) or radius <= 0 or length <= 0:
            raise ValueError("invalid cylinder dimensions")
        return {
            "shape": "cylinder",
            "radius": radius,
            "height": length,
            # Enclosing AABB kept for legacy AABB-proxy comparisons.
            "size_x": 2 * radius,
            "size_y": 2 * radius,
            "size_z": length,
        }
    plane = geometry.find("plane")
    if plane is not None:
        normal = _numbers(plane.findtext("normal"), 3, "plane normal")
        if normal != [0.0, 0.0, 1.0] and normal != [0.0, 0.0, -1.0]:
            raise ValueError("only horizontal planes are supported")
        size = _numbers(plane.findtext("size"), 2, "plane size")
        return {
            "shape": "plane",
            "size_x": size[0],
            "size_y": size[1],
            "size_z": 0.0,
        }
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
        geom = _geometry(collisions[0])
        if geom["size_x"] <= 0 or geom["size_y"] <= 0 or geom["size_z"] < 0:
            raise ValueError("invalid collision dimensions")
        item = {"name": model.get("name"), **geom}
        result.append(item)
    if not result:
        raise ValueError("world has no collidable models")
    return result


def aabb_overlap(center_a, size_a, center_b, size_b):
    """Conservative overlap test for co-sampled model-state positions."""
    return all(abs(float(a) - float(b)) <= (float(sa) + float(sb)) / 2.0
               for a, sa, b, sb in zip(center_a, size_a, center_b, size_b))


def _box_size(obstacle):
    if "size_x" in obstacle:
        return (float(obstacle["size_x"]), float(obstacle["size_y"]), float(obstacle["size_z"]))
    size = obstacle.get("size")
    if isinstance(size, (list, tuple)) and len(size) == 3:
        return (float(size[0]), float(size[1]), float(size[2]))
    raise ValueError("obstacle missing box size")


def robot_enclosing_sphere_radius(robot_bbox):
    """Half-diagonal of the robot AABB (conservative sphere)."""
    return 0.5 * math.sqrt(sum(float(value) * float(value) for value in robot_bbox))


def clearance_sphere_box(robot_center, robot_radius, box_center, box_size):
    """Exterior clearance; <=0 means contact/penetration."""
    gaps = [
        max(abs(float(robot_center[axis]) - float(box_center[axis])) - float(box_size[axis]) / 2.0, 0.0)
        for axis in range(3)
    ]
    return math.sqrt(sum(value * value for value in gaps)) - float(robot_radius)


def clearance_sphere_cylinder(robot_center, robot_radius, cyl_center, radius, height):
    """Upright cylinder (z-aligned) vs enclosing robot sphere."""
    dx = float(robot_center[0]) - float(cyl_center[0])
    dy = float(robot_center[1]) - float(cyl_center[1])
    dz = float(robot_center[2]) - float(cyl_center[2])
    horiz = math.hypot(dx, dy) - float(radius) - float(robot_radius)
    vert = abs(dz) - float(height) / 2.0 - float(robot_radius)
    if horiz <= 0.0 and vert <= 0.0:
        return min(horiz, vert)
    if horiz <= 0.0:
        return vert
    if vert <= 0.0:
        return horiz
    return math.hypot(horiz, vert)


def geometry_clearance(robot_center, robot_bbox, obstacle_center, obstacle):
    """Primary geometry-aware clearance for paper safety claims."""
    robot_radius = robot_enclosing_sphere_radius(robot_bbox)
    if obstacle.get("shape") == "cylinder":
        return clearance_sphere_cylinder(
            robot_center, robot_radius, obstacle_center, obstacle["radius"], obstacle["height"])
    return clearance_sphere_box(robot_center, robot_radius, obstacle_center, _box_size(obstacle))


def aabb_clearance(robot_center, robot_bbox, obstacle_center, obstacle):
    """Legacy AABB-proxy clearance (kept for false-positive comparison)."""
    box_size = _box_size(obstacle)
    half_sum = tuple((float(robot_bbox[axis]) + box_size[axis]) / 2.0 for axis in range(3))
    gaps = tuple(max(abs(float(robot_center[axis]) - float(obstacle_center[axis])) - half_sum[axis], 0.0)
                 for axis in range(3))
    return math.sqrt(sum(value * value for value in gaps))
