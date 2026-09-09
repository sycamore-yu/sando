#!/usr/bin/env python3
import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_forest_geometry import aabb_overlap, world_collision_geometry


def main():
    root = Path(__file__).parents[2] / "worlds"
    expected = {"easy": 42, "medium": 82, "hard": 163}
    for name, count in expected.items():
        geometry = world_collision_geometry(root / f"{name}_forest.world")
        assert len(geometry) == count
        assert geometry[0]["name"] == "ground_plane_map"
        assert geometry[0]["size_x"] == 110.0 and geometry[0]["size_y"] == 50.0 and geometry[0]["size_z"] == 0.0
        assert all(item["size_x"] > 0 and item["size_y"] > 0 for item in geometry[1:])
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
    print("forest geometry tests passed")


if __name__ == "__main__":
    main()
