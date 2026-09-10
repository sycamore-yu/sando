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

**Phase L Case B analysis + Original/FD arms → then decide expand vs deeper attribution**

---

## Completed Evidence

### Milestone 0 / Phases A–F, G probe, J partial
见 git history + `docs/final-study/`.

### Phase K pilots PASS (supervised vs true_diff, seeds 200–205)
- Run: `docker/dev-workspace/results/request-latency-v3/online/phase_k_pilots`
- Tracked: `docs/request-latency-v2/evidence/analysis/phase_k_pilots_compare.json`
- Supervised: **6/6** task success; mean P50≈24.0 ms  
- True Diff-QP: **5/6** task success (seed201 timeout retained); mean P50≈21.7 ms  
- One-shot `fallback=0`; controller_first_use wired

### Phase L decision (automatic)
**Case B** — true-diff not clearly better than supervised on task success.  
Do **not** expand to 200–229 yet. Attribution focus: T saturation / feature gap / feasibility — not Z.

### docs/final-study/ (draft filled with current evidence)
METHOD, PROTOCOL, RESULTS, FAILURE, IDENTITY, REPRODUCE — not “All done” until §3 complete (Original/FD online, unknown/dynamic scenes, corridor hash, etc.).

---

## Active Hypothesis

Optimizer-trained timing reduces planning latency slightly but does not yet improve task success vs supervised; online T often hits F_MAX=2.5.

---

## Current Bottleneck

§3 gaps: Original + FD online arms; unknown/dynamic generalization; observation/corridor hashes; richer trajectory-quality table; Case B attribution depth.

---

## Next Automatic Action

1. Finish Original (and FD) online pilots 200–205; merge into RESULTS  
2. Case B attribution: T histogram online vs pack; feature mismatch note  
3. Unknown/dynamic small pilot if Original finishes  
4. Only declare All done when plan §3 checklist is fully evidenced  

---

## Blocked Only If External

无外部阻塞。
