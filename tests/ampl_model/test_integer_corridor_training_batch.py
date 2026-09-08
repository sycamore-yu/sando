#!/usr/bin/env python3
"""Parity checks for the offline ragged training batch."""

import copy
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_corridor_policy import CorridorPolicy, valid_assignments
from integer_corridor_training_batch import _batched_features, batched_scores, prepare_records
import train_integer_corridor_policy as training


def instance(masks):
    result = {
        "schema_version": 1, "n": 5, "norm": "Linf", "planner": "SANDO",
        "factor": 1.5, "initial_dt": .1, "dc": .05, "segment_dt": .15,
        "start": [0., 0., 1., .1, .2, .3, .01, .02, .03],
        "goal": [2., 1., 2., .2, .1, .0, .03, .02, .01],
        "map_bounds": [-3., 4., -2., 5., 0., 6.], "corridors": [],
        "valid_mask": [], "assignment_variables": [],
        "outcome": {"capture": {"split": "train", "capture_round": 0}},
        "scene_id": "scene-seed0", "episode_id": "episode", "request_id": "request",
        "factor_id": "factor", "source_id": "source", "config_id": "config",
    }
    for time_index, layer_mask in enumerate(masks):
        layer, valid, variables = [], [], []
        for choice_index, allowed in enumerate(layer_mask):
            # The first corridor has tied max inputs; other corridors vary in length.
            count = 3 + time_index + choice_index
            planes = [[1., 0., 0., 4.]] * count if time_index == 0 and choice_index == 0 else [
                [1., 0., 0., 4. + plane_index] for plane_index in range(count)]
            layer.append({"planes": planes if allowed else []})
            valid.append(allowed)
            variables.append(time_index * 10 + choice_index)
        result["corridors"].append(layer)
        result["valid_mask"].append(valid)
        result["assignment_variables"].append(variables)
    return result


def record(value):
    assignments = valid_assignments(value)
    candidates = []
    for index, assignment in enumerate(assignments):
        feasible = index < 2
        candidates.append({"assignment": list(assignment),
                           "classification": "feasible" if feasible else "infeasible",
                           "raw_objective": float(index) if feasible else None,
                           "cost": float(index) if feasible else 2.0})
    parsed = training._validated_record({"instance": value, "costs_complete": True,
                                        "candidates": candidates})
    assert parsed is not None
    return parsed


def loss(policy, scores, records):
    ce = torch.stack([F.cross_entropy(value.reshape(1, -1), torch.tensor([item["best"]]))
                      for value, item in zip(scores, records)]).mean()
    expected = torch.stack([torch.softmax(value, dim=0).dot(training._costs(item))
                            for value, item in zip(scores, records)]).mean()
    return expected + .1 * ce


def main():
    torch.set_num_threads(1)
    torch.manual_seed(17)
    records = [record(instance(((True, True),) * 5)),
               record(instance(((True, True, False), (True, False, True),
                                (True, True, True), (False, True, True),
                                (True, True, True)))),
               record(instance(((True, True, True),) * 5))]
    prepared = prepare_records(records)

    mismatched = copy.deepcopy(records[0])
    mismatched["assignments"] = list(reversed(mismatched["assignments"]))
    try:
        prepare_records([mismatched])
    except ValueError:
        pass
    else:
        raise AssertionError("mismatched assignment ordering accepted")

    reference = CorridorPolicy()
    batched = copy.deepcopy(reference)
    expected_features = [reference._feature_matrix(item["instance"], item["assignments"])
                         for item in records]
    actual_features, counts = _batched_features(batched, prepared)
    assert counts == tuple(len(item["assignments"]) for item in records)
    actual_features = list(torch.split(actual_features, counts))
    for expected, actual in zip(expected_features, actual_features):
        assert torch.allclose(expected, actual, rtol=1e-12, atol=1e-12)

    reference_scores = [reference.score_all(item["instance"])[1] for item in records]
    batched_scores_value = batched_scores(batched, prepared)
    for expected, actual in zip(reference_scores, batched_scores_value):
        assert torch.allclose(expected, actual, rtol=1e-11, atol=1e-12)
    assert training.validation_metric(reference, records) == training.validation_metric_batched(
        batched, records, prepared)

    reference_loss = loss(reference, reference_scores, records)
    batched_loss = loss(batched, batched_scores_value, records)
    reference_loss.backward()
    batched_loss.backward()
    for expected, actual in zip(reference.parameters(), batched.parameters()):
        assert torch.allclose(expected.grad, actual.grad, rtol=1e-10, atol=1e-11)

    reference_optimizer = torch.optim.Adam(reference.parameters(), lr=1e-3)
    batched_optimizer = torch.optim.Adam(batched.parameters(), lr=1e-3)
    reference_optimizer.step()
    batched_optimizer.step()
    for expected, actual in zip(reference.parameters(), batched.parameters()):
        assert torch.allclose(expected, actual, rtol=1e-10, atol=1e-11)

    tied = CorridorPolicy()
    with torch.no_grad():
        for parameter in tied.parameters():
            parameter.zero_()
    tied_instance = records[1]["instance"]
    assignments, scores = tied.score_all(tied_instance)
    assert torch.equal(scores, torch.zeros_like(scores))
    assert tied.rank(tied_instance) == assignments
    assert torch.equal(batched_scores(tied, [prepared[1]])[0], scores)
    print("integer corridor training batch tests passed")


if __name__ == "__main__":
    main()
