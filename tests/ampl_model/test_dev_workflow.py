#!/usr/bin/env python3
"""Executable host-side tests for the development workflow and identity."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docker" / "dev.sh"
IDENTITY = ROOT / "docker" / "dev_identity.py"


def fake_docker(directory, image="sha256:image", container_image=None, mounts=True):
    tool = Path(directory) / "docker"
    container_image = container_image or image
    mount_lines = []
    if mounts:
        uuid = os.environ["TEST_UUID"]
        work = os.environ["TEST_WORKSPACE"]
        mount_lines = [f"{uuid}|/run/secrets/ampl_uuid|false", f"{ROOT}|/root/sando_ws/src/sando|true"]
        mount_lines += [f"{work}/{name}|/root/sando_ws/{dest}|true" for name, dest in (("build", "build-dev"), ("install", "install-dev"), ("log", "log-dev"), ("python", "dev-python"), ("results", "dev-results"))]
    script = """#!/bin/sh
set -eu
case "$1 ${2-}" in
  "image inspect") printf '%s\\n' "$FAKE_IMAGE" ;;
  "inspect sando-dev")
    if [ "${3-}" = "--format" ]; then
      case "$4" in
        *State.Running*) printf 'true\\n' ;;
        *Image*) printf '%s\\n' "$FAKE_CONTAINER_IMAGE" ;;
        *Mounts*) printf '%s\\n' "$FAKE_MOUNTS" ;;
        *) printf '{}\\n' ;;
      esac
    else printf '{}\\n'; fi ;;
  "exec sando-dev") exit 0 ;;
  *) exit 0 ;;
esac
"""
    tool.write_text(script)
    tool.chmod(0o755)
    return tool, "\n".join(mount_lines)


def run_workflow(directory, command, image="sha256:image", container_image=None, mounts=True):
    directory = Path(directory)
    uuid = directory / "uuid"; uuid.write_text("uuid")
    work = directory / "workspace"
    for name in ("build", "install", "log", "python", "results"):
        (work / name).mkdir(parents=True)
    old = os.environ.copy()
    try:
        os.environ.update(TEST_UUID=str(uuid), TEST_WORKSPACE=str(work))
        docker, mount_lines = fake_docker(directory, image, container_image, mounts)
        env = os.environ | {"PATH": f"{docker.parent}:{os.environ['PATH']}", "AMPL_UUID_FILE": str(uuid), "SANDO_DEV_IMAGE": "dev-image", "SANDO_DEV_CONTAINER": "sando-dev", "SANDO_DEV_WORKSPACE": str(work), "FAKE_IMAGE": image, "FAKE_CONTAINER_IMAGE": container_image or image, "FAKE_MOUNTS": mount_lines}
        return subprocess.run([str(SCRIPT), command, "echo", "ok"] if command == "exec" else [str(SCRIPT), command], cwd=ROOT, env=env, text=True, capture_output=True)
    finally:
        os.environ.clear(); os.environ.update(old)


def test_container_guards_apply_to_mutating_and_exec_commands():
    for command in ("up", "build", "test", "exec", "freeze"):
        with tempfile.TemporaryDirectory() as directory:
            result = run_workflow(directory, command, container_image="sha256:wrong")
            assert result.returncode == 68, (command, result.stderr)
        with tempfile.TemporaryDirectory() as directory:
            result = run_workflow(directory, command, mounts=False)
            assert result.returncode == 69, (command, result.stderr)


def git(directory, *args):
    return subprocess.check_output(["git", "-C", str(directory), *args], text=True).strip()


def test_source_fingerprint_tracks_commits_content_deletes_and_submodules():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "repo"; root.mkdir()
        git(root, "init", "-q"); git(root, "config", "user.email", "test@example.com"); git(root, "config", "user.name", "Test")
        (root / "tracked").write_text("one"); git(root, "add", "."); git(root, "commit", "-qm", "initial")
        fingerprint = lambda: subprocess.check_output(["python3", str(IDENTITY), str(root)], text=True).strip()
        clean = fingerprint()
        (root / "new").write_text("content"); assert fingerprint() != clean
        (root / "new").unlink(); assert fingerprint() == clean
        (root / "tracked").unlink(); assert fingerprint() != clean
        git(root, "add", "-A"); git(root, "commit", "-qm", "delete")
        committed_delete = fingerprint(); assert committed_delete != clean
        child = Path(directory) / "child"; child.mkdir(); git(child, "init", "-q"); git(child, "config", "user.email", "test@example.com"); git(child, "config", "user.name", "Test")
        (child / "file").write_text("one"); git(child, "add", "."); git(child, "commit", "-qm", "child")
        subprocess.check_call(["git", "-C", str(root), "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(child), "deps/child"])
        git(root, "commit", "-qm", "submodule"); before_child = fingerprint()
        checked_out_child = root / "deps/child"
        git(checked_out_child, "config", "user.email", "test@example.com"); git(checked_out_child, "config", "user.name", "Test")
        (checked_out_child / "file").write_text("two"); git(checked_out_child, "add", "."); git(checked_out_child, "commit", "-qm", "child-change")
        assert fingerprint() != before_child


def main():
    test_container_guards_apply_to_mutating_and_exec_commands()
    test_source_fingerprint_tracks_commits_content_deletes_and_submodules()
    print("development workflow tests passed")


if __name__ == "__main__":
    main()
