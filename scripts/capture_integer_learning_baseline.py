#!/usr/bin/env python3
"""Record source/config/dependency identities before stage-one experiments.

This read-only probe does not certify backend or simulation acceptance. It never
reads license files, starts containers, or changes Docker permissions.
"""

import argparse
import hashlib
import json
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def probe(args, root):
    try:
        result = subprocess.run(
            args, cwd=root, capture_output=True, text=True, timeout=30, check=False
        )
        return {"command": args, "returncode": result.returncode,
                "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": args, "returncode": None, "error": str(error)}


def capture(root, image):
    paths = subprocess.check_output(
        ["git", "ls-files", "--recurse-submodules", "-z"], cwd=root
    ).decode().split("\0")
    files = {}
    for name in sorted(filter(None, paths)):
        path = root / name
        if path.is_symlink():
            files[name] = {"symlink": str(path.readlink())}
        elif path.is_file():
            files[name] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                           "executable": bool(path.stat().st_mode & 0o111)}
        else:
            files[name] = {"missing": True}
    identity = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return {
        "schema_version": 1,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repository": str(root),
        "host": platform.platform(),
        "head": probe(["git", "rev-parse", "HEAD"], root),
        "worktree": probe(["git", "status", "--short", "--untracked-files=all"], root),
        "submodules": probe(["git", "submodule", "status", "--recursive"], root),
        "tracked_content_sha256": identity,
        "tracked_files": files,
        "docker_server": probe(["docker", "version", "--format", "{{json .Server}}"], root),
        "image": probe(["docker", "image", "inspect", image, "--format",
                        '{{json .Id}} {{json .RepoDigests}}'], root),
        "acceptance": {
            "real_backend": "not_run",
            "static_unknown_simulation": "not_run",
            "dynamic_unknown_simulation": "not_run",
            "sampling_allowed": False,
            "note": "Identity capture alone never passes the baseline gate."
        }
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--image", default="sando-ampl")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.output.exists():
        parser.error("output already exists; preserve earlier baseline records")
    report = capture(root, args.image)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(args.output)
    return 0 if all(report[key]["returncode"] == 0
                    for key in ("head", "submodules", "docker_server", "image")) else 2


if __name__ == "__main__":
    raise SystemExit(main())
