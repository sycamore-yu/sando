# SANDO unified plan（唯一总计划 · Ultimate Goal 模式）

日期：2026-09-10  
活动分支：`feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
Engineering Baseline：`103faa1`  
权威长期任务书：`docs/fromchat/plan.md`

---

## Ultimate Goal

Learning proposes structured T/Z; hard QP keeps feasibility; optimizer-derived loss trains timing.
Deployed path: **1T → real C(T) → 1Z → 1 hard QP**.

“All done” **only** when `docs/fromchat/plan.md` §3 is fully evidenced.

---

## Current Milestone

**Case B follow-through: mitigate online T saturation OR deepen attribution; close remaining §3 items**

---

## Completed Evidence (high level)

- True Diff-QP (KKT) + λ=0.1; FD ablation; Phase F 100-step  
- Online one-shot + controller_first_use identity  
- Fair static pilots 200–205: Original 6/6, Supervised 6/6, FD 5/6, True-diff 5/6  
- Unknown/dynamic pilot 200–201: Supervised 2/2, True-diff 2/2  
- Phase L **Case B** (T→F_MAX saturation)  
- `docs/final-study/` package (draft→filled with current evidence)

---

## §3 checklist (honest)

| Item | Status |
|---|---|
| 3.1 one-shot + true Diff-QP route | PASS |
| 3.1 Z discrete learning | N/A (Z frozen; not failure-dominant) |
| 3.2 QP/residual/grads/C(T)/containment | PASS (prior phases) |
| 3.3 A–D fair compare | PASS (E=D with frozen Z) |
| 3.4 multi-scene beyond seed200 | PARTIAL (static 200–205 + unknown_dyn 200–201; more difficulty configs thin) |
| 3.5 identity chain | PARTIAL (publish/controller_first_use live; obs/corridor hashes still open) |
| 3.6 paper package | PARTIAL (`docs/final-study/` present; not claiming All done) |

---

## Next Automatic Action

1. Case B mitigation probe: reduce online F_MAX saturation (e.g. feature check / soft prior) without deepening net  
2. Stamp observation/corridor hash on replan events  
3. Optional: more difficulty configs  
4. Re-audit §3 — only then All done  

---

## Blocked Only If External

无外部阻塞。
