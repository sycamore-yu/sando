#!/usr/bin/env python3
"""Compare the exported PyTorch policy with the Eigen executable on synthetic inputs."""
import argparse
import copy
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile

import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from integer_corridor_policy import CorridorPolicy, context_features, normalized_planes


def fixture(seed, choices):
    rng = random.Random(seed)
    expression = {"constant": 0.0, "linear": [], "quadratic": []}
    instance = {
        "schema_version": 1, "n": 5, "norm": "Linf", "planner": "SANDO",
        "scene_id": "synthetic", "episode_id": str(seed), "request_id": "0",
        "factor_id": "0", "source_id": "synthetic", "config_id": "synthetic",
        "factor": 1.5, "initial_dt": .1, "dc": .2, "segment_dt": .6,
        "planning_start_time": 1.0, "observation_time": .9, "t0": 1.1,
        "start": [2., -1., 1., .1, .2, .3, .01, .02, .03],
        "goal": [4., 1., 2., .2, .1, 0., .03, .02, .01],
        "map_bounds": [-3., 7., -2., 5., 0., 6.],
        "corridors": [], "valid_mask": [], "assignment_variables": [],
        "coefficients": [[copy.deepcopy(expression) for _ in range(20)] for _ in range(3)],
        "model": {"name": "synthetic", "revision": 0, "objective_sense": 1,
                  "objective": expression, "variables": [], "constraints": []},
        "runtime": {"output_flag": 0, "log_to_console": 0, "threads": 1, "time_limit": 1.0},
        "outcome": {},
    }
    for t in range(5):
        corridors, mask, variables = [], [], []
        for p in range(choices):
            planes = [[rng.uniform(-2., 2.) for _ in range(3)] + [rng.uniform(3., 9.)]
                      for _ in range(6 + t + p)]
            if choices > 1 and t == 2 and p == 0:
                planes = []
            corridors.append({"planes": planes})
            mask.append(bool(planes))
            identifier = t * choices + p + 1
            variables.append(identifier)
            instance["model"]["variables"].append({
                "id": identifier, "name": f"s{p}_{t}", "lb": 0., "ub": 1.,
                "objective": 0., "type": "B"})
        instance["corridors"].append(corridors)
        instance["valid_mask"].append(mask)
        instance["assignment_variables"].append(variables)
    return instance


def check(probe):
    torch.set_num_threads(1)
    errors = []
    with tempfile.TemporaryDirectory(prefix="sando-policy-parity-") as directory:
        directory = Path(directory)
        for seed in (0, 1, 2):
            torch.manual_seed(seed)
            policy = CorridorPolicy()
            if seed == 2:
                with torch.no_grad():
                    for parameter in policy.parameters():
                        parameter.zero_()
            model_path = directory / "model.json"
            model_path.write_text(json.dumps(policy.to_json({"purpose": "synthetic_parity"}), allow_nan=False))
            for choices in (1, 2, 3):
                instance = fixture(seed, choices)
                path = directory / "instance.json"
                path.write_text(json.dumps(instance, allow_nan=False))
                result = subprocess.run([str(probe), str(model_path), str(path)],
                                        text=True, capture_output=True, check=True, timeout=60)
                cpp = json.loads(result.stdout)
                np.testing.assert_allclose(cpp["context"], context_features(instance), rtol=1e-12, atol=1e-12)
                planes = normalized_planes(instance)
                for t in range(5):
                    for p in range(choices):
                        np.testing.assert_allclose(cpp["normalized_planes"][t][p], planes[t][p], rtol=1e-12, atol=1e-12)
                        if planes[t][p]:
                            encoded = policy._encode_corridor(planes[t][p]).detach().numpy()
                            np.testing.assert_allclose(cpp["layers"][t][p], encoded, rtol=1e-10, atol=1e-12)
                python_scores = policy.scores(instance)
                assert [list(a) for a, _ in python_scores] == cpp["assignments"]
                cpp_scores = [item["score"] for item in cpp["scores"]]
                scores = [value for _, value in python_scores]
                np.testing.assert_allclose(cpp_scores, scores, rtol=1e-10, atol=1e-12)
                cpp_rank = [tuple(item["assignment"]) for item in sorted(
                    cpp["scores"], key=lambda item: (-item["score"], item["assignment"]))]
                assert cpp_rank == policy.rank(instance), "Python/Eigen ranking differs"
                errors.append(float(np.max(np.abs(np.asarray(cpp_scores) - scores))))
    return {"fixtures": len(errors), "max_score_absolute_error": max(errors), "rank_match": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.probe.resolve()), sort_keys=True))
