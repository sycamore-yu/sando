"""Standalone checks for stage-5 timing policy data and portable models."""
import json
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_timing_policy import (FEATURE_DIM, LOG_BOUNDS, SINGLE_LOG_BOUNDS, build_mlp, export_model,
                                   fit_normalizer, load_model, raw_features, sample_logfactors)
from train_integer_timing_policy import read_groups
from test_integer_corridor_policy import instance as corridor_instance

def instance(factor, request="request"):
    return {"source_id":"source", "config_id":"config", "scene_id":"scene-seed0", "episode_id":"episode", "request_id":request, "factor_id":str(factor), "factor":factor, "initial_dt":0.2, "dc":0.1, "start":[1,2,3,.1,.2,.3,.4,.5,.6], "goal":[4,5,6,.7,.8,.9,1.,1.1,1.2]}

class TimingPolicyTest(unittest.TestCase):
    def test_raw_features_are_the_locked_17_values(self):
        values = raw_features(instance(1.0)); self.assertEqual(values.shape, (FEATURE_DIM,)); np.testing.assert_allclose(values[:3], [3,3,3]); np.testing.assert_allclose(values[-2:], [.2,.1])
    def test_complete_factor_groups_retain_near_optimal_targets_and_reject_leakage(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"labels.jsonl"; rows=[]
            for factor, objective in ((3.,120.), (1.5,100.), (2.,100.5)):
                value=corridor_instance(1); value.update(instance(factor), t0=0., observation_time=0., planning_start_time=0.)
                rows.append({"instance":value,"costs_complete":True,"candidates":[{"assignment":[0]*5,"classification":"feasible","raw_objective":objective,"cost":0.}]})
            def save(): path.write_text("\n".join(json.dumps(row) for row in rows)+"\n")
            save(); groups=read_groups([path])
            self.assertEqual(len(groups),1); np.testing.assert_allclose(sorted(np.exp(groups[0]['targets'])),[1.5,2.])
            rows[2]['costs_complete']=False
            save(); groups=read_groups([path]); self.assertEqual(len(groups[0]['rows']),2)
            rows[0]['instance']['scene_id']='scene-seed200'; save()
            with self.assertRaisesRegex(ValueError,'locked split'): read_groups([path])
    def test_normalizer_rejects_empty_features(self):
        with self.assertRaises(ValueError): fit_normalizer(np.empty((0,FEATURE_DIM)))
    def test_three_samples_are_bounded_and_k_is_fixed(self):
        import torch
        net=build_mlp(FEATURE_DIM); mean,std=fit_normalizer(np.stack([raw_features(instance(1.)),raw_features(instance(2.))])); model=load_model(export_model("regression",net,mean,std)); samples=sample_logfactors(model,np.zeros(FEATURE_DIM),k=3)
        self.assertEqual(tuple(samples.shape),(3,)); self.assertTrue(bool(torch.isfinite(samples).all())); self.assertGreaterEqual(float(samples.min()),LOG_BOUNDS[0]); self.assertLessEqual(float(samples.max()),LOG_BOUNDS[1])
        with self.assertRaises(ValueError): sample_logfactors(model,np.zeros(FEATURE_DIM),k=2)
    def test_flow_has_gradient_and_serialization_is_deterministic(self):
        import torch
        net=build_mlp(FEATURE_DIM+2); x=torch.zeros((1,FEATURE_DIM),dtype=torch.float64); state=torch.zeros((1,1),dtype=torch.float64,requires_grad=True); time=torch.full((1,1),.5,dtype=torch.float64); net(torch.cat((x,state,time),dim=1)).sum().backward()
        self.assertTrue(any(p.grad is not None and torch.isfinite(p.grad).all() for p in net.parameters())); mean=np.zeros(FEATURE_DIM); std=np.ones(FEATURE_DIM); first=json.dumps(export_model("flow",net,mean,std),sort_keys=True); second=json.dumps(export_model("flow",net,mean,std),sort_keys=True); self.assertEqual(first,second); model=load_model(json.loads(first)); samples=sample_logfactors(model,np.zeros(FEATURE_DIM),k=3); self.assertEqual(tuple(samples.shape),(3,)); self.assertTrue(bool(torch.isfinite(samples).all()))
    def test_rejects_nonfinite_features_and_wrong_dim(self):
        with self.assertRaises(ValueError): raw_features({**instance(1.), "start": [float("nan")] + [0] * 8})
        with self.assertRaises(ValueError): raw_features({**instance(1.), "start": [0] * 8})
        with self.assertRaises(ValueError): fit_normalizer(np.zeros((2, 16)))
        net=build_mlp(FEATURE_DIM); mean,std=np.zeros(FEATURE_DIM),np.ones(FEATURE_DIM)
        model=load_model(export_model("regression",net,mean,std))
        with self.assertRaises(ValueError): sample_logfactors(model, np.zeros(16), k=3)
        with self.assertRaises(ValueError): sample_logfactors(model, np.full(FEATURE_DIM, np.nan), k=3)
    def test_v1_export_stays_three_proposal_schema(self):
        net=build_mlp(FEATURE_DIM); mean,std=np.zeros(FEATURE_DIM),np.ones(FEATURE_DIM)
        default=export_model("regression",net,mean,std)
        explicit=export_model("regression",net,mean,std,output_mode="three")
        self.assertEqual(default, explicit)
        self.assertEqual(default["schema_version"], 1)
        self.assertNotIn("output_mode", default)
        self.assertNotIn("proposal_count", default)
        self.assertEqual(default["latent_quantiles"], [-1.0, 0.0, 1.0])
        self.assertEqual(default["logfactor_bounds"], list(LOG_BOUNDS))
        samples=sample_logfactors(load_model(default), np.zeros(FEATURE_DIM), k=3)
        self.assertEqual(tuple(samples.shape), (3,))
        with self.assertRaises(ValueError): sample_logfactors(load_model(default), np.zeros(FEATURE_DIM), k=1)
    def test_single_schema_returns_one_bounded_logfactor(self):
        import math, torch
        net=build_mlp(FEATURE_DIM); mean,std=np.zeros(FEATURE_DIM),np.ones(FEATURE_DIM)
        record=export_model("regression",net,mean,std,output_mode="single")
        self.assertEqual(record["schema_version"], 2)
        self.assertEqual(record["output_mode"], "single")
        self.assertEqual(record["proposal_count"], 1)
        self.assertEqual(record["latent_quantiles"], [0.0])
        self.assertEqual(record["logfactor_bounds"], list(SINGLE_LOG_BOUNDS))
        with torch.no_grad(): samples=sample_logfactors(load_model(record), np.zeros(FEATURE_DIM), k=1)
        self.assertEqual(tuple(samples.shape), (1,))
        self.assertGreaterEqual(float(samples.min()), SINGLE_LOG_BOUNDS[0])
        self.assertLessEqual(float(samples.max()), SINGLE_LOG_BOUNDS[1])
        with self.assertRaises(ValueError): sample_logfactors(load_model(record), np.zeros(FEATURE_DIM), k=3)
        with torch.no_grad(): net[-1].bias.fill_(10.0)
        with torch.no_grad(): clamped=sample_logfactors(load_model(export_model("regression",net,mean,std,output_mode="single")), np.zeros(FEATURE_DIM), k=1)
        self.assertAlmostEqual(float(clamped[0]), math.log(2.5), places=15)
        flow=export_model("flow",build_mlp(FEATURE_DIM+2),mean,std,nfe=1,output_mode="single")
        with torch.no_grad(): one=sample_logfactors(load_model(flow), np.zeros(FEATURE_DIM), k=1)
        self.assertEqual(tuple(one.shape), (1,))
        self.assertGreaterEqual(float(one[0]), SINGLE_LOG_BOUNDS[0])
        self.assertLessEqual(float(one[0]), SINGLE_LOG_BOUNDS[1])
    def test_rejects_corrupt_schema_and_wrong_bounds(self):
        import math
        net=build_mlp(FEATURE_DIM); mean,std=np.zeros(FEATURE_DIM),np.ones(FEATURE_DIM)
        v1=export_model("regression",net,mean,std)
        v2=export_model("regression",net,mean,std,output_mode="single")
        bad=dict(v1); bad["schema_version"]=99
        with self.assertRaises(ValueError): load_model(bad)
        bad=dict(v1); bad["logfactor_bounds"]=[0.0, math.log(2.5)]
        with self.assertRaises(ValueError): load_model(bad)
        bad=dict(v1); bad["latent_quantiles"]=[0.0]
        with self.assertRaises(ValueError): load_model(bad)
        bad=dict(v2); bad["logfactor_bounds"]=list(LOG_BOUNDS)
        with self.assertRaises(ValueError): load_model(bad)
        bad=dict(v2); bad["latent_quantiles"]=[-1.0, 0.0, 1.0]
        with self.assertRaises(ValueError): load_model(bad)
        bad=dict(v2); bad["output_mode"]="three"
        with self.assertRaises(ValueError): load_model(bad)
        bad=dict(v2); bad["proposal_count"]=3
        with self.assertRaises(ValueError): load_model(bad)
        bad=dict(v2); bad["proposal_count"]=True
        with self.assertRaises(ValueError): load_model(bad)
        bad=dict(v2); del bad["output_mode"]
        with self.assertRaises(ValueError): load_model(bad)
if __name__ == "__main__": unittest.main()
