#!/usr/bin/env python3
"""Compare portable nonzero timing networks in Python and the compiled evaluator."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile

import numpy as np
import torch
sys.path.insert(0, str(Path(__file__).parents[2] / 'scripts'))
from integer_timing_policy import build_mlp, export_model, load_model, normalize, sample_logfactors


def main(binary):
    torch.set_num_threads(1)
    torch.manual_seed(391)
    features = np.linspace(-.3, .7, 17)
    mean, std = np.linspace(-.1, .1, 17), np.linspace(.7, 1.3, 17)
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        feature_file = root / 'features.json'
        feature_file.write_text(json.dumps(features.tolist()))
        for kind, nfe in [('regression', 1), ('flow', 1), ('flow', 4), ('flow', 8)]:
            net = build_mlp(17 if kind == 'regression' else 19)
            with torch.no_grad(): net[-1].bias.fill_(.7 if kind == 'regression' else .3)
            record = export_model(kind, net, mean, std, residual_std=.15, nfe=nfe)
            file = root / 'model.json'
            file.write_text(json.dumps(record))
            model = load_model(record)
            with torch.no_grad(): expected = sample_logfactors(model, normalize(features, mean, std)).numpy()
            actual = np.asarray(json.loads(subprocess.check_output([binary, str(file), str(feature_file)], text=True)))
            np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
            assert np.any((actual > 0) & (actual < np.log(5))), 'fixture hides differences through clamping'
            results.append({'type': kind, 'nfe': nfe, 'max_error': float(np.max(np.abs(actual-expected)))})
            for field, value in [('feature_spec', []), ('latent_quantiles', [0,0,0]), ('residual_std', -1), ('std', [0]*17)]:
                invalid = copy.deepcopy(record); invalid[field] = value; file.write_text(json.dumps(invalid))
                try: load_model(invalid)
                except ValueError: pass
                else: raise AssertionError(f'Python accepted invalid {field}')
                completed = subprocess.run([binary, str(file), str(feature_file)], capture_output=True)
                assert completed.returncode != 0, f'C++ accepted invalid {field}'
        for kind, nfe in [('regression', 1), ('flow', 1)]:
            net = build_mlp(17 if kind == 'regression' else 19)
            with torch.no_grad(): net[-1].bias.fill_(.2 if kind == 'regression' else .15)
            record = export_model(kind, net, mean, std, residual_std=.15, nfe=nfe, output_mode='single')
            file = root / 'model.json'
            file.write_text(json.dumps(record))
            model = load_model(record)
            with torch.no_grad(): expected = sample_logfactors(model, normalize(features, mean, std), k=1).numpy()
            actual = np.asarray(json.loads(subprocess.check_output([binary, str(file), str(feature_file)], text=True)))
            np.testing.assert_allclose(actual, expected, rtol=1e-12, atol=1e-12)
            assert actual.shape == (1,)
            assert np.all((actual >= 0) & (actual <= np.log(2.5)))
            assert np.any((actual > 0) & (actual < np.log(2.5))), 'fixture hides differences through clamping'
            results.append({'type': kind, 'nfe': nfe, 'output_mode': 'single', 'max_error': float(np.max(np.abs(actual-expected)))})
            for field, value in [('logfactor_bounds', [0.0, float(np.log(5))]), ('latent_quantiles', [-1.0, 0.0, 1.0]), ('proposal_count', 3), ('output_mode', 'three')]:
                invalid = copy.deepcopy(record); invalid[field] = value; file.write_text(json.dumps(invalid))
                try: load_model(invalid)
                except ValueError: pass
                else: raise AssertionError(f'Python accepted invalid v2 {field}')
                completed = subprocess.run([binary, str(file), str(feature_file)], capture_output=True)
                assert completed.returncode != 0, f'C++ accepted invalid v2 {field}'
    print(json.dumps(results))


if __name__ == '__main__':
    main(sys.argv[1])
