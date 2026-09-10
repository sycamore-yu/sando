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

**Phase M formal expand 200–229 (frozen λ=1.0) + denser-obstacle generalization**

---

## Completed Evidence

- True Diff-QP (KKT); one-shot online; controller_first_use; **planning_observation_hash + corridor_hash**
- Freeze: `docs/final-study/FREEZE.json` (λ_T=1.0)
- Pilots 200–205 A–D + λ1 mitigation 6/6 + unknown_dynamic
- Hash smoke: `phase_j_identity_hash_smoke.json`
- Phase M expand **running**: `phase_m_expand_200_229`

---

## §3 checklist

| Item | Status |
|---|---|
| 3.1 method | PASS |
| 3.2 correctness | PASS |
| 3.3 A–E fair compare | PASS (E=λ1 one-shot) |
| 3.4 generalization | IN PROGRESS (expand 200–229 + need denser configs) |
| 3.5 identity chain | PASS (hashes live-verified) |
| 3.6 paper package | IN PROGRESS |

---

## Next Automatic Action

1. Wait for Phase M expand; aggregate RESULTS  
2. Denser obstacle / alternate difficulty pilots  
3. Final §3 audit → All done only if complete  

---

## Blocked Only If External

无外部阻塞。
