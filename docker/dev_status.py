#!/usr/bin/env python3
from pathlib import Path
import os
import hashlib

print("container_src", Path("/root/sando_ws/src/sando/package.xml").resolve())
print("AMPL", os.environ.get("SANDO_AMPL_EXECUTABLE"))
print("dev_build", os.environ.get("SANDO_DEV_BUILD", "/root/sando_ws/build-dev"))
print("dev_install", os.environ.get("SANDO_DEV_INSTALL", "/root/sando_ws/install-dev"))
freeze = Path("/root/sando_ws/src/sando/docker/dev-workspace/freeze")
print("freeze_record", freeze / "latest.json", "present" if (freeze / "latest.json").is_file() else "missing")
for label, path in [
    ("image_sando", "/root/sando_ws/install/sando/lib/sando/sando"),
    ("dev_sando", "/root/sando_ws/install-dev/sando/lib/sando/sando"),
]:
    p = Path(path)
    print(label, "present" if p.is_file() else "missing", path)
    if p.is_file():
        print(label, "sha256", hashlib.sha256(p.read_bytes()).hexdigest())
