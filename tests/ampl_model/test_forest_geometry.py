#!/usr/bin/env python3
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_forest_geometry import (
    aabb_clearance,
    aabb_overlap,
    geometry_clearance,
    world_collision_geometry,
)


def main():
    root = Path(__file__).parents[2] / "worlds"
    expected = {"easy": 42, "medium": 82, "hard": 163}
    for name, count in expected.items():
        geometry = world_collision_geometry(root / f"{name}_forest.world")
        assert len(geometry) == count
        assert geometry[0]["name"] == "ground_plane_map"
        assert geometry[0]["size_x"] == 110.0 and geometry[0]["size_y"] == 50.0 and geometry[0]["size_z"] == 0.0
        assert all(item["size_x"] > 0 and item["size_y"] > 0 for item in geometry[1:])
        trees = [item for item in geometry if item["name"] != "ground_plane_map"]
        assert trees and all(item.get("shape") == "cylinder" for item in trees)
        assert all("radius" in item and "height" in item for item in trees)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "bad.world"
        path.write_text("<sdf><world><model name='bad'><static>1</static><link><collision><pose>1 0 0 0 0 0</pose><geometry><mesh><uri>x</uri></mesh></geometry></collision></link></model></world></sdf>")
        try:
            world_collision_geometry(path)
        except ValueError as error:
            assert "local pose" in str(error)
        else:
            raise AssertionError("unsupported local collision pose accepted")
    assert aabb_overlap((0, 0, 0), (2, 2, 2), (1, 0, 0), (2, 2, 2))
    assert not aabb_overlap((0, 0, 0), (2, 2, 2), (2.1, 0, 0), (2, 2, 2))
    # Corner of enclosing AABB is outside the cylinder → AABB proxy hits, geometry does not.
    robot = (0.55, 0.55, 0.0)
    cyl = {"shape": "cylinder", "radius": 0.5, "height": 2.0, "size_x": 1.0, "size_y": 1.0, "size_z": 2.0}
    bbox = (0.2, 0.2, 0.2)
    assert aabb_clearance(robot, bbox, (0.0, 0.0, 0.0), cyl) <= 0.0
    assert geometry_clearance(robot, bbox, (0.0, 0.0, 0.0), cyl) > 0.0
    print("forest geometry tests passed")


if __name__ == "__main__":
    main()
