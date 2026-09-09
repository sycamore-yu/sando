"""Portable factor timing policies for stage-5 experiments."""
from __future__ import annotations
import json, math
import numpy as np

FEATURE_SPEC = ("goal_position_delta", "start_velocity", "start_acceleration", "goal_velocity", "goal_acceleration", "initial_dt", "dc")
FEATURE_DIM = 17
LOG_BOUNDS = (math.log(1.0), math.log(5.0))
SINGLE_LOG_BOUNDS = (math.log(1.0), math.log(2.5))

def raw_features(instance):
    start, goal = instance["start"], instance["goal"]
    if len(start) != 9 or len(goal) != 9:
        raise ValueError("start and goal must contain nine state values")
    result = np.asarray([goal[i] - start[i] for i in range(3)] + list(start[3:6]) + list(start[6:9]) + list(goal[3:6]) + list(goal[6:9]) + [instance["initial_dt"], instance["dc"]], dtype=np.float64)
    if result.shape != (FEATURE_DIM,) or not np.isfinite(result).all():
        raise ValueError("timing features must be finite")
    return result

def fit_normalizer(features):
    values = np.asarray(features, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] != FEATURE_DIM or values.shape[0] == 0 or not np.isfinite(values).all():
        raise ValueError("features must be a non-empty finite matrix with 17 columns")
    mean, std = values.mean(axis=0), values.std(axis=0)
    std[std < 1e-12] = 1.0
    return mean, std

def normalize(features, mean, std):
    values = np.asarray(features, dtype=np.float64)
    result = (values - np.asarray(mean, dtype=np.float64)) / np.asarray(std, dtype=np.float64)
    if result.shape[-1] != FEATURE_DIM or not np.isfinite(result).all():
        raise ValueError("normalized timing features must be finite and have 17 columns")
    return result

def sample_logfactors(model, features, k=3):
    import torch
    single = model.get("schema_version") == 2
    if single:
        if k != 1: raise ValueError("timing policy requires K=1")
        q = torch.tensor([0.0], dtype=torch.float64)
        bounds = SINGLE_LOG_BOUNDS
    else:
        if k != 3: raise ValueError("timing policy requires K=3")
        q = torch.tensor([-1.0, 0.0, 1.0], dtype=torch.float64)
        bounds = LOG_BOUNDS
    x = torch.as_tensor(features, dtype=torch.float64)
    if x.shape != (FEATURE_DIM,) or not torch.isfinite(x).all():
        raise ValueError('invalid normalized timing features')
    if model["type"] == "regression":
        value = model["model"](x).reshape(())
        residual = float(model.get("residual_std", 0.0))
        values = value + residual * q
        if not torch.isfinite(values).all():
            raise ValueError('nonfinite timing prediction')
        return torch.clamp(values, *bounds)
    values = []
    for latent in q:
        state = latent
        for step in range(model.get("nfe", 1)):
            # Use the left endpoint for the explicit Euler convention shared
            # by training and inference.
            t = torch.tensor(step / model.get("nfe", 1), dtype=torch.float64)
            velocity = model["model"](torch.cat((x, state.reshape(1), t.reshape(1))))
            state = state + velocity.reshape(()) / model.get("nfe", 1)
            if not torch.isfinite(state):
                raise ValueError('nonfinite flow state')
        values.append(torch.clamp(state, *bounds))
    return torch.stack(values)

def export_model(kind, net, mean, std, residual_std=0.0, nfe=1, output_mode="three"):
    if kind not in ("regression", "flow"):
        raise ValueError("unknown timing policy type")
    if output_mode not in ("three", "single"):
        raise ValueError("unknown timing output mode")
    weights = [p.detach().cpu().numpy().tolist() for p in net.parameters()]
    if output_mode == "single":
        return {"schema_version": 2, "type": kind, "output_mode": "single", "proposal_count": 1, "feature_spec": list(FEATURE_SPEC), "mean": np.asarray(mean).tolist(), "std": np.asarray(std).tolist(), "logfactor_bounds": list(SINGLE_LOG_BOUNDS), "residual_std": float(residual_std), "nfe": int(nfe), "latent_quantiles": [0.0], "weights": weights}
    return {"schema_version": 1, "type": kind, "feature_spec": list(FEATURE_SPEC), "mean": np.asarray(mean).tolist(), "std": np.asarray(std).tolist(), "logfactor_bounds": list(LOG_BOUNDS), "residual_std": float(residual_std), "nfe": int(nfe), "latent_quantiles": [-1.0, 0.0, 1.0], "weights": weights}

def build_mlp(input_dim, output_dim=1):
    import torch
    return torch.nn.Sequential(torch.nn.Linear(input_dim, 64), torch.nn.Tanh(), torch.nn.Linear(64, 64), torch.nn.Tanh(), torch.nn.Linear(64, output_dim)).double()

def load_model(record):
    import torch
    schema = record.get("schema_version")
    if schema not in (1, 2) or record.get("type") not in ("regression", "flow"):
        raise ValueError("unsupported timing policy model")
    bounds = list(LOG_BOUNDS) if schema == 1 else list(SINGLE_LOG_BOUNDS)
    quantiles = [-1.0, 0.0, 1.0] if schema == 1 else [0.0]
    if (record.get('feature_spec') != list(FEATURE_SPEC)
            or record.get('logfactor_bounds') != bounds
            or record.get('latent_quantiles') != quantiles
            or (schema == 2 and (record.get('output_mode') != 'single'
                                 or type(record.get('proposal_count')) is not int
                                 or record.get('proposal_count') != 1))):
        raise ValueError('invalid timing feature or sampling specification')
    residual = record.get('residual_std')
    if (isinstance(residual, bool) or not isinstance(residual, (int, float))
            or not math.isfinite(residual) or residual < 0):
        raise ValueError('invalid timing residual scale')
    if len(record.get("weights", [])) != 6:
        raise ValueError("timing policy model has invalid weights")
    mean = np.asarray(record.get("mean"), dtype=np.float64)
    std = np.asarray(record.get("std"), dtype=np.float64)
    if mean.shape != (FEATURE_DIM,) or std.shape != (FEATURE_DIM,) or not np.isfinite(mean).all() or not np.isfinite(std).all() or (std <= 0).any():
        raise ValueError("timing policy model has invalid normalization")
    if (type(record.get('nfe')) is not int or record['nfe'] not in (1, 4, 8)
            or record['type'] == 'regression' and record['nfe'] != 1):
        raise ValueError("timing policy model has invalid NFE")
    net = build_mlp(FEATURE_DIM if record["type"] == "regression" else FEATURE_DIM + 2)
    with torch.no_grad():
        for parameter, values in zip(net.parameters(), record["weights"]):
            tensor = torch.tensor(values, dtype=torch.float64)
            if tensor.shape != parameter.shape or not torch.isfinite(tensor).all():
                raise ValueError("timing policy model weight shape mismatch")
            parameter.copy_(tensor)
    record = dict(record); record["model"] = net
    return record
