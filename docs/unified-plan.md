# SANDO unified plan（唯一总计划 · Ultimate Goal 模式）

日期：2026-09-10  
活动分支：`feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
Engineering Baseline：`103faa1`  
权威长期任务书：`docs/fromchat/plan.md`

---

## Ultimate Goal

Learning proposes structured T/Z; hard QP keeps feasibility and executable motion;
optimizer-derived trajectory/task loss trains the learned decisions.
Deployed path is exactly **1T → real C(T) → 1Z → 1 hard QP** (fallback counted separately).

Stop and report “All done” **only** when `docs/fromchat/plan.md` §3 is fully evidenced.

---

## Current Milestone

**Close §3 gaps: FD online arm + unknown/dynamic pilot + Case B mitigation evidence**

---

## Completed Evidence

### Phases A–G, J, K (partial), L Case B
- True Diff-QP KKT + λ=0.1; Phase F 100-step models  
- Online one-shot + controller_first_use verified  
- Pilots 200–205: Original 6/6, Supervised 6/6, True-diff 5/6  
- Case B: T saturation at 2.5 online for true-diff  
- `docs/final-study/` draft package present  

### Fair compare status (§3.3)
| Arm | Online 200–205 |
|---|---|
| A Original | PASS 6/6 |
| B Supervised | PASS 6/6 |
| C FD-proxy | in progress |
| D True Diff-QP | PASS 5/6 (failure retained) |
| E final structured | = D for now (Z frozen) |

---

## Active Hypothesis

True-diff lowers latency vs Original/supervised but online feature distribution drives T→F_MAX, hurting reliability vs supervised.

---

## Current Bottleneck

§3 still open: FD online results; unknown/dynamic scenes; observation/corridor hashes; optional Case B fix (feature/clamp) before claiming scientific closure.

---

## Next Automatic Action

1. Finish FD pilots; merge into RESULTS/compare  
2. One unknown/dynamic pilot seed (true_diff + supervised)  
3. Stamp observation/corridor hash on replan events if cheap  
4. Re-audit plan §3 — only then All done  

---

## Blocked Only If External

无外部阻塞。
