#!/usr/bin/env python3
import copy
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_corridor_policy import CorridorPolicy, context_features, normalized_planes, valid_assignments
import train_integer_corridor_policy as training


def instance(choices=2):
    result = {
        "schema_version": 1, "n": 5, "norm": "Linf", "planner": "SANDO",
        "factor": 1.5, "initial_dt": .1, "dc": .05, "segment_dt": .15,
        "start": [0., 0., 1., .1, .2, .3, .01, .02, .03],
        "goal": [2., 1., 2., .2, .1, .0, .03, .02, .01],
        "map_bounds": [-3., 4., -2., 5., 0., 6.],
        "corridors": [], "valid_mask": [], "assignment_variables": [],
        "outcome": {"capture": {"split": "train", "capture_round": 0}}, "scene_id": "scene",
    }
    for t in range(5):
        result["corridors"].append([]); result["valid_mask"].append([]); result["assignment_variables"].append([])
        for p in range(choices):
            result["corridors"][t].append({"planes": [[1., 0., 0., 4.], [0., 1., 0., 4.]]})
            result["valid_mask"][t].append(True)
            result["assignment_variables"][t].append(t * choices + p + 1)
    return result


def labelled_record(x):
    assignments = valid_assignments(x)
    candidates = []
    for index, assignment in enumerate(assignments):
        feasible = index < 2
        objective = -2.0 + index if feasible else None
        candidates.append({"assignment": list(assignment), "classification": "feasible" if feasible else "infeasible",
                           "raw_objective": objective, "cost": 0.0 if index == 0 else (1.0 if index == 1 else 2.0)})
    return {"instance": x, "costs_complete": True, "candidates": candidates}


def main():
    x = instance()
    assert len(valid_assignments(x)) == 32
    policy = CorridorPolicy()
    assert policy.features(x, (0, 0, 0, 0, 0)).shape == (355,)
    assert len(normalized_planes(x)[0][0]) == 2
    five = instance(1)
    five["corridors"][0][0]["planes"] = [[1., 0., 0., float(i + 1)] for i in range(5)]
    assert len(normalized_planes(five)[0][0]) == 5
    assert len(policy.rank(x)) == 32
    masked = copy.deepcopy(x)
    masked["corridors"][0][0]["planes"] = []
    masked["valid_mask"][0][0] = False
    assert len(policy.rank(masked)) == 16

    shifted = copy.deepcopy(x)
    shift = [7., -3., 2.]
    for state_name in ("start", "goal"):
        for i in range(3): shifted[state_name][i] += shift[i]
    for axis in range(3):
        shifted["map_bounds"][2 * axis] += shift[axis]
        shifted["map_bounds"][2 * axis + 1] += shift[axis]
    for layer in shifted["corridors"]:
        for corridor in layer:
            for plane in corridor["planes"]:
                plane[3] += sum(plane[i] * shift[i] for i in range(3))
    assert all(abs(a - b) < 1e-12 for a, b in zip(context_features(x), context_features(shifted)))
    assert normalized_planes(x) == normalized_planes(shifted)

    record = labelled_record(instance(1))
    parsed = training._validated_record(record)
    assert parsed is not None and parsed["assignments"] == [tuple(c["assignment"]) for c in record["candidates"]]
    record["candidates"].reverse()
    parsed = training._validated_record(record)
    assert parsed is not None and parsed["assignments"][0] == (0, 0, 0, 0, 0)
    bad_cost = copy.deepcopy(record)
    bad_cost["candidates"][0]["cost"] = .5
    try:
        training._validated_record(bad_cost)
    except ValueError:
        pass
    else:
        raise AssertionError("bad cost accepted")
    near_tie = labelled_record(instance(2))
    near_tie["candidates"][0].update(raw_objective=100.00015, cost=1.0)
    near_tie["candidates"][1].update(raw_objective=100.0, cost=0.0)
    assert training._validated_record(near_tie)["best"] == 1

    malformed = copy.deepcopy(x); malformed["valid_mask"][0][0] = True; malformed["corridors"][0][0]["planes"] = []
    try:
        valid_assignments(malformed)
    except ValueError:
        pass
    else:
        raise AssertionError("empty corridor accepted")
    malformed = copy.deepcopy(x); malformed["segment_dt"] = float("nan")
    try:
        context_features(malformed)
    except ValueError:
        pass
    else:
        raise AssertionError("nonfinite timing accepted")
    model_json = policy.to_json()
    model_json["layers"]["score1"]["weight"] = []
    try:
        CorridorPolicy.from_json(model_json)
    except ValueError:
        pass
    else:
        raise AssertionError("malformed model accepted")
    overlap = training._validated_record(labelled_record(instance(1)))
    overlap["instance"]["scene_id"] = "same"
    other = training._validated_record(labelled_record(instance(1)))
    other["instance"]["scene_id"] = "same"
    try:
        training.check_split_disjoint([overlap], [other])
    except ValueError:
        pass
    else:
        raise AssertionError("scene overlap accepted")
    print("integer corridor policy tests passed")


if __name__ == "__main__":
    main()
