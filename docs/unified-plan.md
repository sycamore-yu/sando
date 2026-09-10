# SANDO unified plan（唯一总计划 · Ultimate Goal 模式）

日期：2026-09-10  
活动分支：`feat/ampl-gurobi` → `personal/feat/ampl-gurobi`  
Engineering Baseline：`103faa1`  
权威长期任务书：`docs/fromchat/plan.md`

---

## Ultimate Goal

Learning proposes structured T/Z; hard QP keeps feasibility; optimizer-derived loss trains timing.
Deployed path: **1T → real C(T) → 1Z → 1 hard QP**.

---

## Status

**Section 3 Ultimate DoD: PASS (evidenced)** — see `docs/final-study/SECTION3_DOD_AUDIT.json`.

Scientific answer (RQ2/RQ3): true Diff-QP timing with λ_T=1.0 is **competitive with supervised** on frozen formal seeds 200–229 (29/30 vs 29/30), faster than Original; λ=0.1 underperformed due to online T→F_MAX saturation (Case B → mitigated).

---

## Evidence anchors

- Method/freeze: `docs/final-study/{METHOD,FREEZE,PROTOCOL,RESULTS,FAILURE,IDENTITY,REPRODUCE}.md`
- Formal expand: `docs/request-latency-v2/evidence/analysis/phase_m_expand_200_229.json`
- Identity hashes: `phase_j_identity_hash_smoke.json`
- Dense/unknown: `phase_m_dense100.json`, `phase_k_unknown_dynamic_pilots.json`

---

## Blocked Only If External

无外部阻塞。
