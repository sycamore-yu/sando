#!/usr/bin/env python3
from pathlib import Path
import os
import hashlib

print("container_src", Path("/root/sando_ws/src/sando/package.xml").resolve())
print("AMPL", os.environ.get("SANDO_AMPL_EXECUTABLE"))
for label, path in [
    ("image_sando", "/root/sando_ws/install/sando/lib/sando/sando"),
    ("dev_sando", "/root/sando_ws/install-dev/sando/lib/sando/sando"),
]:
    p = Path(path)
    print(label, "present" if p.is_file() else "missing", path)
    if p.is_file():
        print(label, "sha256", hashlib.sha256(p.read_bytes()).hexdigest())
