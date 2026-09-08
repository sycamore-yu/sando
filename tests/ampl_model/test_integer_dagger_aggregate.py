#!/usr/bin/env python3
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_dagger_aggregate import aggregate


def item(request, split="train"):
    return {"instance": {
        "scene_id": "unknown_dynamic-n50-d0.65-seed0",
        "episode_id": "e",
        "request_id": request,
        "factor_id": "0",
        "outcome": {"capture": {"split": split, "capture_round": 0}},
    }}


def main():
    original = [item("a"), item("b")]
    student = [item("b"), item("c"), item("d", "validation")]
    result = aggregate(original, student)
    ids = [record["instance"]["request_id"] for record in result["records"]]
    assert ids == ["a", "b", "c"]
    assert result["duplicates"] == 1
    assert result["rejected_split"] == 1
    assert result["sources"] == {"original": 2, "student": 1}
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "out.jsonl"
        from integer_dagger_aggregate import write_jsonl
        write_jsonl(path, result["records"])
        assert sum(1 for _ in path.open()) == 3
    print("integer dagger aggregate tests passed")


if __name__ == "__main__":
    main()
