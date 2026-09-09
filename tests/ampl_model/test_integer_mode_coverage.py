#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parents[2]/'scripts'))
from evaluate_integer_mode_coverage import modes, points, clustered_assignments
def curve(offset):
    return {'assignment':[0,0,0,0,0],'classification':'feasible','raw_objective':offset,'segment_dt':1.,'trajectory_coefficients':[[offset]*20,[0.]*20,[0.]*20]}
def main():
    same=curve(0.); distinct=curve(1.)
    assert len(points(same['trajectory_coefficients'],1.))==25
    assert len(modes([same,curve(0.)],.05))==1
    assert len(modes([same,distinct],.05))==2
    assert len(modes([same,distinct],.5))==2
    distinct['assignment']=[1,1,1,1,1]
    duplicate=curve(0.); duplicate['assignment']=[2,2,2,2,2]
    clusters=clustered_assignments([same,distinct,duplicate],.5)
    assert len(clusters)==2
    ranked={(0,0,0,0,0),(2,2,2,2,2)}
    assert sum(bool(group & ranked) for group in clusters)==1
    try: points([[0.]*20]*3,float('nan'))
    except ValueError: pass
    else: raise AssertionError('nonfinite duration accepted')
    print('integer mode coverage tests passed')
if __name__=='__main__': main()
