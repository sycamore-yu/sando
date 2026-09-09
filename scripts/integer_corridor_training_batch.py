"""Ragged batching helpers for offline corridor-policy training.

The inference implementation remains the reference.  This module only caches
parameter-independent geometry and batches the two neural-network stages.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import torch

from integer_corridor_policy import CorridorPolicy, context_features, normalized_planes, valid_assignments


@dataclass(frozen=True)
class PreparedRecord:
    """Cached non-parameter data for one validated training record."""

    assignments: tuple[tuple[int, ...], ...]
    plane_values: torch.Tensor
    plane_offsets: tuple[tuple[int, int], ...]
    candidate_corridors: torch.Tensor
    context: torch.Tensor

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "PreparedRecord":
        instance = record["instance"]
        assignments = tuple(tuple(int(value) for value in assignment)
                            for assignment in record["assignments"])
        if assignments != tuple(valid_assignments(instance)):
            raise ValueError("record assignment ordering differs from the policy")
        planes = normalized_planes(instance)
        values: list[list[float]] = []
        offsets: list[tuple[int, int]] = []
        corridor_ids: dict[tuple[int, int], int] = {}
        for time_index, layer in enumerate(planes):
            for choice_index, corridor in enumerate(layer):
                if not corridor:
                    continue
                start = len(values)
                values.extend(corridor)
                offsets.append((start, len(values)))
                corridor_ids[(time_index, choice_index)] = len(offsets) - 1
        if not offsets:
            raise ValueError("a usable record must contain a non-empty corridor")
        candidate_indices = []
        for assignment in assignments:
            try:
                candidate_indices.append([corridor_ids[(t, int(choice))] for t, choice in enumerate(assignment)])
            except KeyError as error:
                raise ValueError("assignment refers to an empty corridor") from error
        return cls(
            assignments=assignments,
            plane_values=torch.as_tensor(values, dtype=torch.float64),
            plane_offsets=tuple(offsets),
            candidate_corridors=torch.as_tensor(candidate_indices, dtype=torch.long),
            context=torch.as_tensor(context_features(instance), dtype=torch.float64),
        )


def prepare_records(records: Sequence[dict[str, Any]], device: str | torch.device | None = None) -> list[PreparedRecord]:
    """Cache normalized geometry, context, and candidate indexing once."""

    result = [PreparedRecord.from_record(record) for record in records]
    if device is not None:
        target = torch.device(device)
        result = [PreparedRecord(r.assignments, r.plane_values.to(target), r.plane_offsets,
                                 r.candidate_corridors.to(target), r.context.to(target)) for r in result]
    return result


def _batched_features(policy: CorridorPolicy, prepared: Sequence[PreparedRecord]) -> tuple[torch.Tensor, tuple[int, ...]]:
    if not prepared:
        raise ValueError("cannot score an empty batch")
    plane_values = torch.cat([record.plane_values for record in prepared], dim=0)
    hidden = torch.relu(policy.plane2(torch.relu(policy.plane1(plane_values))))

    corridor_offset = 0
    candidate_indices = []
    contexts = []
    counts = []
    lengths = torch.as_tensor([end - start for record in prepared for start, end in record.plane_offsets],
                              dtype=torch.long, device=hidden.device)
    pooled_mean = torch.segment_reduce(hidden, "mean", lengths=lengths)
    # Preserve Tensor.max's first-index subgradient for exact ties, without
    # a device synchronization or a separate operation for each corridor.
    detached = hidden.detach()
    maxima = torch.segment_reduce(detached, "max", lengths=lengths)
    matches = detached == torch.repeat_interleave(maxima, lengths, dim=0,
                                                  output_size=hidden.shape[0])
    indices = torch.arange(hidden.shape[0], device=hidden.device, dtype=hidden.dtype)
    eligible_indices = indices[:, None].expand_as(hidden).masked_fill(~matches, float("inf"))
    first = torch.segment_reduce(eligible_indices, "min", lengths=lengths).long()
    pooled_max = hidden[first, torch.arange(hidden.shape[1], device=hidden.device)]
    encoded = torch.cat((pooled_mean, pooled_max, lengths.to(hidden.dtype)[:, None]), dim=1)
    for record in prepared:
        count = len(record.assignments)
        counts.append(count)
        candidate_indices.append(record.candidate_corridors + corridor_offset)
        contexts.append(record.context.expand(count, -1))
        corridor_offset += len(record.plane_offsets)

    candidates = torch.cat(candidate_indices, dim=0)
    corridor_features = encoded.index_select(0, candidates.reshape(-1))
    corridor_features = corridor_features.reshape(candidates.shape[0], candidates.shape[1], -1)
    features = torch.cat((corridor_features.reshape(candidates.shape[0], -1),
                          torch.cat(contexts, dim=0)), dim=1)
    if features.shape[1] != 355 or not torch.isfinite(features).all():
        raise ValueError("invalid policy feature matrix")
    return features, tuple(counts)


def batched_scores(policy: CorridorPolicy, prepared: Sequence[PreparedRecord]) -> list[torch.Tensor]:
    """Score prepared records in one plane-encoder and one candidate-MLP pass."""

    features, counts = _batched_features(policy, prepared)
    hidden = torch.relu(policy.score1(features))
    hidden = torch.relu(policy.score2(hidden))
    scores = policy.score3(hidden).reshape(-1)
    if not torch.isfinite(scores).all():
        raise ValueError("non-finite network score")
    return list(torch.split(scores, counts))
