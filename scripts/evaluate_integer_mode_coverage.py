#!/usr/bin/env python3
"""Measure solver trajectory mode coverage in complete integer labels."""
import argparse, hashlib, json, math
from collections import Counter
from pathlib import Path
from integer_set_supervision import near_optimal_mask, CONFIG

def points(coeff, dt):
    if (len(coeff)!=3 or any(len(row)!=20 for row in coeff) or not math.isfinite(dt) or dt<=0
            or any(not math.isfinite(value) for row in coeff for value in row)):
        raise ValueError('invalid recovered polynomial or duration')
    out=[]
    for seg in range(5):
        a=[]
        for tau in (0,.25,.5,.75,1):
            t=tau*dt; a.append(tuple(sum(coeff[k][seg*4+j]*t**(3-j) for j in range(4)) for k in range(3)))
        out.extend(a)
    return out
def distance(a,b): return max(math.dist(x,y) for x,y in zip(a,b))
def modes(candidates, threshold):
    reps=[]
    for c in sorted(candidates,key=lambda x:(float(x.get('raw_objective',math.inf)),x['assignment'])):
        curve=points(c['trajectory_coefficients'],float(c['segment_dt']))
        if not any(distance(curve,r)<=threshold for r in reps): reps.append(curve)
    return reps
def clustered_assignments(candidates, threshold):
    reps=[]; members=[]
    for c in sorted(candidates,key=lambda x:(float(x['raw_objective']),x['assignment'])):
        curve=points(c['trajectory_coefficients'],float(c['segment_dt']))
        index=next((i for i,r in enumerate(reps) if distance(curve,r)<=threshold),None)
        if index is None:
            index=len(reps); reps.append(curve); members.append(set())
        members[index].add(tuple(c['assignment']))
    return members
def main():
    p=argparse.ArgumentParser(); p.add_argument('inputs',nargs='+'); p.add_argument('--output',required=True); p.add_argument('--threshold',type=float,default=.5); p.add_argument('--model'); p.add_argument('--validation',action='store_true'); p.add_argument('--full-corpus',action='store_true'); a=p.parse_args()
    if not math.isfinite(a.threshold) or a.threshold <= 0: p.error('threshold must be finite and positive')
    from train_integer_corridor_policy import load_labelled
    stats={}; validated=load_labelled(a.inputs,validation=a.validation,statistics=stats)
    identity=('source_id','config_id','scene_id','episode_id','request_id','factor_id')
    keys={tuple(r['instance'][k] for k in identity) for r in validated if r['costs_complete']}
    records=[]; missing=0
    for path in a.inputs:
        for line in Path(path).read_text().splitlines():
            if not line.strip(): continue
            r=json.loads(line)
            if tuple(r['instance'][k] for k in identity) not in keys: continue
            cs=[c for c in r['candidates'] if c['classification']=='feasible']
            if any(not c.get('trajectory_coefficients') or c.get('segment_dt') is None for c in cs):
                missing+=1; continue
            if cs: records.append((r,cs))
    result={'schema_version':2,'partial':not a.full_corpus,'definition':'greedy objective-ordered clusters at 25 sampled trajectory positions','threshold_m':a.threshold,'thresholds_m':sorted({.05,.1,.5,a.threshold}),'near_optimal':{'eps_rel':CONFIG['eps_rel'],'j_scale':CONFIG['j_scale'],'eps_abs':CONFIG['eps_abs']},'records_read':stats['total'],'complete_instances':len(keys),'excluded':stats['excluded'],'unknown_or_incomplete':stats['total']-len(keys),'missing_coefficients':missing,'instances_with_usable_coefficients':len(records),'modes':{}}
    model=None
    if a.model:
        from integer_corridor_policy import CorridorPolicy
        import torch
        torch.set_num_threads(2)
        model=CorridorPolicy.load(a.model); model.eval(); result['model_sha256']=hashlib.sha256(Path(a.model).read_bytes()).hexdigest()
    rankings=[set(model.rank(raw['instance'])[:3]) if model else set() for raw,cs in records]
    for threshold in result['thresholds_m']:
        hist=Counter(); near_hist=Counter(); ge2=[]; near_ge2=[]; topk_hits=topk_near=total=hit=near_total=near_hit=0
        for (raw, cs), ranked in zip(records,rankings):
            reps=clustered_assignments(cs,threshold); mask=near_optimal_mask(cs); near=[c for c,keep in zip(cs,mask) if keep]; near_reps=clustered_assignments(near,threshold)
            hist[len(reps)]+=1; near_hist[len(near_reps)]+=1
            if len(reps)>=2: ge2.append([raw['instance'][k] for k in identity])
            if len(near_reps)>=2: near_ge2.append([raw['instance'][k] for k in identity])
            if model:
                covered=sum(bool(group & ranked) for group in reps); near_covered=sum(bool(group & ranked) for group in near_reps)
                total+=len(reps); hit+=covered; near_total+=len(near_reps); near_hit+=near_covered
                topk_hits += covered>0; topk_near += near_covered>0
        result['modes'][str(threshold)]={'all_feasible_histogram':dict(hist),'near_optimal_histogram':dict(near_hist),'mode_ge2_ids':ge2,'near_optimal_mode_ge2_ids':near_ge2,'topk3_instances_hitting_mode':topk_hits if model else None,'topk3_near_optimal_instances_hitting_mode':topk_near if model else None,'topk3':{'modes_hit':hit,'modes_total':total,'mode_coverage':hit/total if total else None,'near_optimal_modes_hit':near_hit,'near_optimal_modes_total':near_total,'near_optimal_mode_coverage':near_hit/near_total if near_total else None} if model else None}
    result['source_hashes']={str(Path(x)):hashlib.sha256(Path(x).read_bytes()).hexdigest() for x in a.inputs}
    Path(a.output).write_text(json.dumps(result,indent=2)+'\n'); return 0
if __name__=='__main__': raise SystemExit(main())
