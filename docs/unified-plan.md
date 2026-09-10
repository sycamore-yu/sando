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

**Promote λ=1.0 Case B fix → freeze → decide Phase M expand; stamp obs hashes**

---

## Completed Evidence

- True Diff-QP (KKT); Phase E/F; online one-shot + controller_first_use + `z_id`/`corridor_method`
- Fair static 200–205: Original 6/6, Supervised 6/6, FD 5/6, True-diff λ0.1 5/6
- Case B mitigation: **True-diff λ=1.0 → 6/6**, lower F_MAX saturation
- Unknown/dynamic 200–201: Supervised 2/2, True-diff λ0.1 2/2
- `docs/final-study/` package

---

## §3 checklist (honest)

| Item | Status |
|---|---|
| 3.1 one-shot + Diff-QP | PASS |
| 3.1 Z discrete learning | N/A (frozen Z) |
| 3.2 correctness | PASS |
| 3.3 A–D fair compare | PASS (+ λ1 mitigation) |
| 3.4 generalization | PARTIAL (need more difficulty / freeze then optional 200–229) |
| 3.5 identity | PARTIAL (`z_id`/corridor_method added; full obs/map sha still open) |
| 3.6 paper package | PARTIAL |

---

## Next Automatic Action

1. Freeze λ=1.0 as primary; re-run unknown_dynamic smoke with λ1  
2. Add observation/map sha to online events when cheap  
3. Phase L Case A re-eval: if λ1 clearly ≥ supervised with no regressions → expand 200–229  
4. Only All done when §3 fully evidenced  

---

## Blocked Only If External

无外部阻塞。
