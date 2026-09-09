#!/usr/bin/env python3
"""Build an immutable release from a verified source snapshot and image ID."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from dev_identity import source_manifest


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def copy_source(source, destination, manifest):
    destination.mkdir(parents=True, exist_ok=True)
    for name, entry in manifest["files"].items():
        src, dst = source / name, destination / name
        if "files" in entry:
            copy_source(src, dst, entry)
        elif not entry.get("missing"):
            dst.parent.mkdir(parents=True, exist_ok=True)
            if "symlink" in entry:
                dst.symlink_to(entry["symlink"])
            else:
                shutil.copy2(src, dst)
                if hashlib.sha256(dst.read_bytes()).hexdigest() != entry["sha256"]:
                    raise RuntimeError(f"source changed during snapshot: {src}")


def verify_source(root, manifest):
    expected = {}

    def flatten(node, prefix=Path()):
        for name, entry in node["files"].items():
            path = prefix / name
            if "files" in entry:
                flatten(entry, path)
            elif not entry.get("missing"):
                expected[str(path)] = entry
    flatten(manifest)
    actual = {str(path.relative_to(root)) for path in root.rglob("*")
              if path.is_file() or path.is_symlink()}
    if actual != set(expected):
        raise RuntimeError("release source inventory differs from its manifest")
    for name, entry in expected.items():
        path = root / name
        if "symlink" in entry:
            if not path.is_symlink() or path.readlink().as_posix() != entry["symlink"]:
                raise RuntimeError(f"release symlink differs from manifest: {name}")
        elif (path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
              or bool(path.stat().st_mode & 0o111) != entry["executable"]):
            raise RuntimeError(f"release source differs from manifest: {name}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    base = run("docker", "image", "inspect", args.base, "--format", "{{.Id}}")
    base_tag = f"sando-learning-base:{base.removeprefix('sha256:')}"
    subprocess.run(["docker", "image", "tag", base, base_tag], check=True)
    if run("docker", "image", "inspect", base_tag, "--format", "{{.Id}}") != base:
        raise SystemExit("release base image identity changed")
    manifest = source_manifest(args.root)
    source_hash = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    expected = f"{source_hash} {base}"
    if (args.workspace / ".dev-build-identity").read_text().strip() != expected:
        raise SystemExit("source or base image differs from tested development build")
    dockerfile = f'''FROM {base_tag}
SHELL ["/bin/bash", "-c"]
RUN find /root/sando_ws/src/sando -mindepth 1 -maxdepth 1 ! -name deps -exec rm -rf {{}} +
COPY source/ /root/sando_ws/src/sando/
COPY identity.json /opt/sando-integer-source.json
WORKDIR /root/sando_ws
RUN source /opt/ros/humble/setup.bash && source /root/livox_ws/install/setup.bash && source /root/sando_ws/install/setup.bash && CMAKE_BUILD_PARALLEL_LEVEL={args.jobs} MAKEFLAGS=-j{args.jobs} colcon build --paths /root/sando_ws/src/sando --packages-select sando --build-base /root/sando_ws/build-release --install-base /root/sando_ws/install --parallel-workers 1 --cmake-args -DCMAKE_BUILD_TYPE=RelWithDebInfo -DSANDO_USE_AMPL=ON -DAMPLS_ROOT=/opt/ampls-api
'''
    identity = {"schema_version": 3, "source_id": source_hash, "base_image": base,
                "source_manifest": manifest, "build_type": "RelWithDebInfo",
                "dockerfile_sha256": hashlib.sha256(dockerfile.encode()).hexdigest()}
    release_id = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:20]
    destination = args.workspace / "freeze" / "releases" / release_id
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if json.loads((destination / "identity.json").read_text()) != identity:
            raise SystemExit("release identity conflict")
    else:
        with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
            context = Path(temporary)
            copy_source(args.root, context / "source", manifest)
            if source_manifest(args.root) != manifest:
                raise SystemExit("source changed during release snapshot")
            (context / "identity.json").write_text(json.dumps(identity, sort_keys=True, indent=2) + "\n")
            (context / "Dockerfile").write_text(dockerfile)
            shutil.move(str(context), destination)
    verify_source(destination / "source", manifest)
    if (destination / "Dockerfile").read_text() != dockerfile:
        raise SystemExit("release Dockerfile differs from its recorded build recipe")
    tag = f"sando-learning-release:{release_id}"
    subprocess.run(["docker", "build", "--tag", tag, str(destination)], check=True)
    base_layers = json.loads(run("docker", "image", "inspect", base, "--format", "{{json .RootFS.Layers}}"))
    built_layers = json.loads(run("docker", "image", "inspect", tag, "--format", "{{json .RootFS.Layers}}"))
    if built_layers[:len(base_layers)] != base_layers:
        raise SystemExit("release was built from an unexpected base image")
    result = {"identity": identity, "image": tag,
              "image_id": run("docker", "image", "inspect", tag, "--format", "{{.Id}}")}
    record = destination / "release.json"
    if record.exists() and json.loads(record.read_text()) != result:
        raise SystemExit("rebuilding the release produced a different image; retain both images for inspection")
    record.write_text(json.dumps(result, sort_keys=True, indent=2) + "\n")
    print(json.dumps({"record": str(record), "image": tag, "image_id": result["image_id"]}))


if __name__ == "__main__":
    main()
