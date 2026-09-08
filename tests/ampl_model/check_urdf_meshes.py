#!/usr/bin/env python3
"""Expand a SANDO URDF and verify that every referenced mesh exists.

Run this after sourcing the ROS workspace.  By default it expands the working
tree's quadrotor xacro; ``--urdf`` can point at an installed or alternate URDF.
"""

import argparse
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path


def _package_mesh_path(filename):
    from ament_index_python.packages import get_package_share_directory

    package_uri = filename[len("package://") :]
    package, separator, relative_name = package_uri.partition("/")
    if not separator or not package or not relative_name:
        raise ValueError(f"invalid package URI: {filename}")
    share = Path(get_package_share_directory(package))
    return share / relative_name


def _mesh_path(filename):
    if filename.startswith("package://"):
        return _package_mesh_path(filename)
    if filename.startswith("file://"):
        return Path(filename[len("file://") :])
    return Path(filename)


def check_urdf(urdf):
    try:
        import xacro
    except ImportError as error:
        raise RuntimeError("xacro is required; source the ROS workspace first") from error

    urdf = Path(urdf).resolve()
    if not urdf.is_file():
        raise RuntimeError(f"URDF/xacro does not exist: {urdf}")
    try:
        expanded = xacro.process_file(str(urdf)).toxml()
    except Exception as error:
        raise RuntimeError(f"xacro expansion failed for {urdf}: {error}") from error

    root = ElementTree.fromstring(expanded)
    meshes = []
    missing = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "mesh":
            continue
        filename = element.attrib.get("filename", "").strip()
        if not filename:
            missing.append(("<missing filename>", None))
            continue
        try:
            path = _mesh_path(filename).resolve()
        except Exception as error:
            missing.append((filename, str(error)))
            continue
        meshes.append((filename, path))
        if not path.is_file():
            missing.append((filename, str(path)))
    return meshes, missing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf", type=Path)
    args = parser.parse_args()
    urdf = args.urdf
    if urdf is None:
        urdf = Path(__file__).resolve().parents[2] / "urdf" / "quadrotor.urdf.xacro"
    try:
        meshes, missing = check_urdf(urdf)
    except Exception as error:
        print(f"FAIL: {error}", file=sys.stderr)
        return 1
    if missing:
        for filename, path in missing:
            print(f"MISSING: {filename} -> {path}", file=sys.stderr)
        return 1
    print(f"PASS: {len(meshes)} mesh path(s) exist after xacro expansion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
