#!/usr/bin/env python3
"""Content identity of the checkout, including initialized submodules."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def source_manifest(root: Path) -> dict:
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args])

    paths = set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0"))
    files = {}
    for raw in sorted(paths - {b""}):
        name = os.fsdecode(raw)
        path = root / name
        if path.is_symlink():
            files[name] = {"symlink": os.readlink(path)}
        elif path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            files[name] = {"sha256": digest.hexdigest(), "executable": bool(path.stat().st_mode & 0o111)}
        elif path.is_dir() and (path / ".git").exists():
            files[name] = source_manifest(path)
        else:
            files[name] = {"missing": True}
    return {"git_head": git("rev-parse", "HEAD").decode().strip(), "files": files}


def fingerprint(root: Path) -> str:
    return hashlib.sha256(json.dumps(source_manifest(root), sort_keys=True).encode()).hexdigest()


if __name__ == "__main__":
    print(fingerprint(Path(sys.argv[1])))
