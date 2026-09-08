#!/usr/bin/env python3
import copy
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_set_supervision import (
    EPS_ABS,
    EPS_REL,
    J_SCALE,
    near_optimal_mask,
    set_supervision_loss,
    mixed_segment_counterexample,
    assignments_from_mask,
    good_set_from_trajectories,
)


def test_single_good_matches_cross_entropy():
    scores = [2.0, 0.5, -1.0]
    good = [False, True, False]
    loss = set_supervision_loss(scores, good)
    expected = math.log(sum(math.exp(v) for v in scores)) - scores[1]
    assert abs(loss - expected) < 1e-12


def test_all_good_zero_loss():
    scores = [1.5, -0.2, 4.0]
    assert abs(set_supervision_loss(scores, [True, True, True])) < 1e-12


def test_empty_good_set_raises():
    try:
        set_supervision_loss([0.0, 1.0], [False, False])
    except ValueError as error:
        assert "empty good set" in str(error)
    else:
        raise AssertionError("empty good set accepted")


def test_translation_and_permutation_invariance():
    scores = [0.3, -1.2, 2.2, 0.0]
    good = [True, False, True, False]
    shifted = [value + 7.5 for value in scores]
    permuted = [scores[i] for i in (2, 0, 3, 1)]
    permuted_good = [good[i] for i in (2, 0, 3, 1)]
    base = set_supervision_loss(scores, good)
    assert abs(base - set_supervision_loss(shifted, good)) < 1e-12
    assert abs(base - set_supervision_loss(permuted, permuted_good)) < 1e-12


def test_invalid_candidates_are_masked():
    scores = [10.0, 0.0, 1.0]
    loss = set_supervision_loss(scores, [False, True, False], [False, True, True])
    expected = math.log(math.exp(0.0) + math.exp(1.0)) - 0.0
    assert abs(loss - expected) < 1e-12


def test_near_zero_and_extreme_objectives():
    zero = [
        {"classification": "feasible", "raw_objective": 0.0},
        {"classification": "feasible", "raw_objective": EPS_ABS / 2},
        {"classification": "infeasible", "raw_objective": None},
    ]
    assert near_optimal_mask(zero) == [True, True, False]
    huge = [
        {"classification": "feasible", "raw_objective": 1e6},
        {"classification": "feasible", "raw_objective": 1e6 * (1 + EPS_REL / 2)},
        {"classification": "feasible", "raw_objective": 1e6 * (1 + 5 * EPS_REL)},
    ]
    assert near_optimal_mask(huge) == [True, True, False]
    tiny = [
        {"classification": "feasible", "raw_objective": 0.0},
        {"classification": "feasible", "raw_objective": J_SCALE * EPS_REL / 2},
        {"classification": "feasible", "raw_objective": J_SCALE},
    ]
    assert near_optimal_mask(tiny)[0] is True
    assert near_optimal_mask(tiny)[2] is False


def test_torch_all_good_zero_grad():
    try:
        import torch
    except ImportError:
        print("skip torch set-loss gradient test")
        return
    from integer_set_supervision import set_supervision_loss_torch
    scores = torch.tensor([1.5, -0.2, 4.0], dtype=torch.float64, requires_grad=True)
    loss = set_supervision_loss_torch(scores, torch.tensor([True, True, True]))
    loss.backward()
    assert float(loss) < 1e-12
    assert torch.allclose(scores.grad, torch.zeros_like(scores.grad), atol=1e-12)


def test_expert_union_not_segment_mix():
    first = [(0, 0, 0, 0, 0)]
    second = [(1, 1, 1, 1, 1)]
    union = set(good_set_from_trajectories([first, second]))
    mixed = (0, 1, 0, 1, 0)
    assert mixed not in union
    product = set(assignments_from_mask([[True, True]] * 5))
    assert mixed in product
    counter = mixed_segment_counterexample()
    assert counter["mixed_in_union"] is False
    assert counter["mixed_in_segment_product"] is True


def main():
    test_single_good_matches_cross_entropy()
    test_all_good_zero_loss()
    test_empty_good_set_raises()
    test_translation_and_permutation_invariance()
    test_invalid_candidates_are_masked()
    test_near_zero_and_extreme_objectives()
    test_torch_all_good_zero_grad()
    test_expert_union_not_segment_mix()
    print("integer set loss tests passed")


if __name__ == "__main__":
    main()
