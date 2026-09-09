"""Standalone checks for stage-5 timing policy data and portable models."""
import json
import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))
from integer_timing_policy import (FEATURE_DIM, LOG_BOUNDS, build_mlp, export_model,
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
if __name__ == "__main__": unittest.main()
