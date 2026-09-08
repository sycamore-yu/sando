#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_instance_sampler import select_instances


def record(request, x, vx=0.0, mask=True):
    return {"instance": {
        "scene_id": "unknown_dynamic-n50-d0.65-seed0",
        "episode_id": "e",
        "request_id": str(request),
        "start": [float(x), 0.0, 2.0, float(vx), 0.0, 0.0, 0.0, 0.0, 0.0],
        "valid_mask": [[mask, not mask]] * 5,
    }}


def main():
    records = [record(i, i, i, i % 2 == 0) for i in range(12)]
    uniform = select_instances(records, "uniform_reservoir_v1", 4)
    assert len(uniform) == 4
    again = select_instances(records, "uniform_reservoir_v1", 4)
    assert [item["instance"]["request_id"] for item in uniform] == [item["instance"]["request_id"] for item in again]
    diverse = select_instances(records, "uniform_plus_diverse_v1", 6)
    assert len(diverse) == 6
    ids = [item["instance"]["request_id"] for item in diverse]
    assert len(set(ids)) == 6
    print("integer instance sampler tests passed")


if __name__ == "__main__":
    main()
