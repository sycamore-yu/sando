#!/usr/bin/env python3
"""Compare continuous regression and flow timing proposals on captured factor tables."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
from collections import Counter
from pathlib import Path

import numpy as np

from integer_set_supervision import CONFIG
from integer_timing_policy import (
    build_mlp, export_model, fit_normalizer, load_model, normalize,
    raw_features, sample_logfactors,
)

IDENTITY = ('source_id', 'config_id', 'scene_id', 'episode_id', 'request_id')


def read_groups(paths, validation=False, statistics=None):
    from train_integer_corridor_policy import load_labelled
    statistics = statistics if statistics is not None else {}
    records = load_labelled(paths, validation=validation, statistics=statistics)
    groups = {}
    for record in records:
        if not record['costs_complete']:
            continue
        instance = record['instance']
        feasible = [c for c in record['candidates'] if c['classification'] == 'feasible']
        if not feasible:
            continue
        factor = float(instance['factor'])
        if not math.isfinite(factor) or not 1.0 - 1e-9 <= factor <= 5.0 + 1e-9:
            raise ValueError('captured factor is outside the timing model support [1,5]')
        key = tuple(instance[name] for name in IDENTITY)
        features = raw_features(instance)
        group = groups.setdefault(key, {'identity': key, 'instance': instance,
                                        'features': features, 'rows': []})
        if not np.allclose(group['features'], features, rtol=1e-10, atol=1e-10):
            raise ValueError('factor labels for one request have inconsistent state features')
        if any(row['factor_id'] == instance['factor_id'] for row in group['rows']):
            raise ValueError('duplicate factor label within a request')
        group['rows'].append({'factor_id': instance['factor_id'], 'factor': factor,
                              'objective': min(float(c['raw_objective']) for c in feasible)})
    result = []
    for key in sorted(groups):
        group = groups[key]
        reference = min(row['objective'] for row in group['rows'])
        tolerance = CONFIG['eps_rel'] * max(abs(reference), CONFIG['j_scale']) + CONFIG['eps_abs']
        group['targets'] = [math.log(row['factor']) for row in group['rows']
                            if row['objective'] <= reference + tolerance]
        result.append(group)
    statistics.update(requests=len(result), unpaired_requests=sum(len(g['rows']) == 1 for g in result),
                      factor_count_histogram=dict(Counter(len(g['rows']) for g in result)),
                      multiple_target_requests=sum(len(g['targets']) > 1 for g in result))
    if not result:
        raise ValueError('no feasible validated factor labels')
    return result


def read_validated_cases(paths, validation=False, statistics=None):
    return [(group['instance'], math.exp(target))
            for group in read_groups(paths, validation, statistics) for target in group['targets']]


def fit(groups, kind='regression', epochs=100, seed=0, nfe=1):
    import torch
    if epochs < 1 or kind not in ('regression', 'flow') or nfe not in (1, 4, 8):
        raise ValueError('invalid timing training configuration')
    torch.manual_seed(seed)
    np.random.seed(seed)
    features = np.stack([group['features'] for group in groups])
    mean, std = fit_normalizer(features)
    x = torch.tensor(normalize(features, mean, std), dtype=torch.float64)
    target_sets = [torch.tensor(g['targets'], dtype=torch.float64) for g in groups]
    net = build_mlp(17 if kind == 'regression' else 19)
    optimizer = torch.optim.Adam(net.parameters(), lr=1e-3)
    losses = []
    for epoch in range(epochs):
        epoch_losses = []
        for indices in torch.randperm(len(groups)).split(32):
            optimizer.zero_grad()
            if kind == 'regression':
                target = torch.stack([target_sets[i].mean() for i in indices]).reshape(-1, 1)
                loss = (net(x[indices]) - target).square().mean()
            else:
                target = torch.stack([target_sets[i][torch.randint(len(target_sets[i]), ())]
                                      for i in indices]).reshape(-1, 1)
                latent = torch.randn(len(indices), 1, dtype=torch.float64)
                time = torch.rand(len(indices), 1, dtype=torch.float64)
                state = (1 - time) * latent + time * target
                velocity = net(torch.cat((x[indices], state, time), dim=1))
                loss = (velocity - (target - latent)).square().mean()
            if not torch.isfinite(loss):
                raise ValueError('nonfinite timing loss')
            loss.backward()
            if any(p.grad is None or not torch.isfinite(p.grad).all() for p in net.parameters()):
                raise ValueError('nonfinite timing gradient')
            optimizer.step()
            epoch_losses.append(float(loss.detach()))
        losses.append({'epoch': epoch + 1, 'loss': float(np.mean(epoch_losses))})
    with torch.no_grad():
        residual = math.sqrt(float(torch.stack([(net(x[i]).reshape(()) - targets).square().mean()
                                               for i, targets in enumerate(target_sets)]).mean())) if kind == 'regression' else 0.0
    return export_model(kind, net, mean, std, residual, 1 if kind == 'regression' else nfe), losses


def train(paths, kind='regression', epochs=100, seed=0, nfe=1):
    return fit(read_groups(paths), kind, epochs, seed, nfe)[0]


def evaluate(record, groups):
    import torch
    model = load_model(record)
    rows = []
    with torch.no_grad():
        for group in groups:
            features = normalize(group['features'], record['mean'], record['std'])
            proposals = sample_logfactors(model, features).numpy()
            captured = group['rows']
            nearest = [min(captured, key=lambda row: abs(math.log(row['factor']) - proposal))
                       for proposal in proposals]
            best = min(row['objective'] for row in captured)
            selected = min(row['objective'] for row in nearest)
            rows.append({'identity': group['identity'], 'captured_factors': len(captured),
                         'proposed_factors': np.exp(proposals).tolist(),
                         'logfactor_error_squared': min((float(proposals[1]) - target) ** 2 for target in group['targets']),
                         'nearest_captured_objective': selected, 'best_captured_objective': best,
                         'nearest_captured_relative_regret': (selected - best) / max(abs(best), CONFIG['j_scale']),
                         'nearest_factor_log_distance': [abs(math.log(row['factor']) - float(value))
                                                        for row, value in zip(nearest, proposals)]})
    paired = [row for row in rows if row['captured_factors'] > 1]
    return {'scope': 'discrete replay proxy over captured feasible factors; no continuous-QP feasibility claim',
            'requests': len(rows), 'paired_requests': len(paired),
            'logfactor_mse': float(np.mean([row['logfactor_error_squared'] for row in rows])),
            'paired_nearest_captured_relative_regret': float(np.mean([row['nearest_captured_relative_regret'] for row in paired])) if paired else None,
            'rows': rows}


def hashes(paths):
    return {str(Path(path).resolve()): hashlib.sha256(Path(path).read_bytes()).hexdigest() for path in paths}


def main():
    import torch
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels', nargs='+', required=True)
    parser.add_argument('--validation', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--type', choices=('regression', 'flow'), default='regression')
    parser.add_argument('--epochs', type=int, default=100)
    parser.add_argument('--seed', type=int, choices=(0, 1, 2), default=0)
    parser.add_argument('--nfe', type=int, choices=(1, 4, 8), default=1)
    args = parser.parse_args()
    if args.output.exists():
        parser.error('output already exists')
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    before = hashes(args.labels + args.validation)
    train_stats, validation_stats = {}, {}
    groups = read_groups(args.labels, statistics=train_stats)
    validation = read_groups(args.validation, validation=True, statistics=validation_stats)
    if hashes(args.labels + args.validation) != before:
        raise ValueError('timing input files changed while loading')
    model, losses = fit(groups, args.type, args.epochs, args.seed, args.nfe)
    if hashes(args.labels + args.validation) != before:
        raise ValueError('timing input files changed during training')
    model['metadata'] = {'epochs': args.epochs, 'seed': args.seed, 'batch_size': 32,
                         'learning_rate': 1e-3, 'training_files': {str(Path(p).resolve()): before[str(Path(p).resolve())] for p in args.labels},
                         'validation_files': {str(Path(p).resolve()): before[str(Path(p).resolve())] for p in args.validation},
                         'sources': hashes([__file__, Path(__file__).with_name('integer_timing_policy.py')]),
                         'dependencies': {'python': platform.python_version(), 'numpy': np.__version__, 'torch': str(torch.__version__)},
                         'train_stats': train_stats, 'validation_stats': validation_stats,
                         'near_optimal': CONFIG, 'target_sampling': 'equal request weight; uniform near-optimal factor within request',
                         'status': 'complete'}
    validation_report = evaluate(model, validation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(model, stream, allow_nan=False, indent=2)
        stream.write('\n')
    args.output.with_suffix('.validation.json').write_text(json.dumps(validation_report, allow_nan=False, indent=2) + '\n')
    args.output.with_suffix('.progress.json').write_text(json.dumps(losses, allow_nan=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in validation_report.items() if k != 'rows'}))


if __name__ == '__main__':
    main()
