# QP equivalence audit (draft) — Diff-QP basis vs SANDO Bezier / MINVO

**Status:** draft audit (plan2 Phase 4 open item)  
**Scope:** control-point / polynomial basis used by Python Diff-QP  
(`prototypes/time_fixed_z_qp`, especially `diff_time_qp_kkt.py` → `run_time_qp.build_spec`)  
vs C++ SANDO `SolverGurobi` Bezier CPs, MINVO CPs, and `BasisConverter`.  
**Rule:** do **not** change production C++ constraints to fit Python; if mismatch, fix Python.

Related prior docs:

- `docs/diff-time-qp-mapping.md` (§2 flagged “node samples vs Minvo/Bezier” as open)
- `docs/fromchat/plan2.md` (§9 Phase 4 — this file + 50-instance experiment)
- `docs/im.md` / `docs/sando-flightbench-learning-plan.md` (corridor/map use `getCP0`–`getCP3`, not MINVO)

---

## Assumptions (reader)

You know SANDO solves a cubic piecewise trajectory QP, that Diff-QP is a Python Clarabel copy used for training gradients, and that “control points” are linear forms of the cubic coefficients used as conservative bounds (not free decision variables in the fixed-Z path).

---

## 1. Main verdict

| Layer | Verdict |
| --- | --- |
| **Polynomial decision variables** (cubic \(p(t)=at^3+bt^2+ct+d\) per axis/segment) | **Identical** math; layout differs (C++ `axis → 4N`, Python interleaved `(3n+axis)*4`) |
| **QP constraint CPs used by production fixed-Z Gurobi** (map, corridor, L∞ vel/acc/jerk) | **Identical** to Python Diff-QP rows: cubic **Bezier** position CPs + Bezier derivative CPs (`getVelCP` / `getAccelCP` / `getJerkCP`) |
| **MINVO / `BasisConverter`** (`A_pos_mv_*`, `M_be2mv_`, `getMinvo*ControlPoints`) | **Inconsistent** with Python Diff-QP (and with the live Gurobi *constraint* path). MINVO ≠ Bezier; algebraic gap is O(0.1–1) on random coeffs, not float noise |
| **End-to-end objective on one fixture** | **Numerically equivalent** for trajectory jerk vs Gurobi objective (rel err ≤ ~4e-6 on feasible \(f\)); Python adds a ridge term so *full* Clarabel objective ≠ Gurobi |

**One-line summary:** Diff-QP matches the **Bezier** basis that production fixed-Z Gurobi actually constrains; it does **not** match **MINVO**, and the 50-instance formal parity pack is still missing.

Correction to `docs/diff-time-qp-mapping.md` §2 wording: Python rows are **not** “samples at \(0,d/3,2d/3,d\)” of the curve. The middle two position rows are **Bezier control points** \(Q_1,Q_2\), which coincide with the formulas in `getCP1`/`getCP2`, not with \(p(d/3)\) / \(p(2d/3)\).

---

## 2. Where each basis is defined

### 2.1 C++ — power basis (shared)

| Item | Location |
| --- | --- |
| Local cubic eval \(p(\tau)=a\tau^3+b\tau^2+c\tau+d\) | `src/sando/gurobi_solver.cpp:5588–5592` (`getPos`) |
| Normalized coeffs \(A_n=a\,d^3,\ldots\) for \(u\in[0,1]\) | `gurobi_solver.cpp:5648–5663` (`getAn`…`getDn`) |
| Decision coeffs `x_[axis][4*interval + {0,1,2,3}]` | same file, `getA`…`getD` at `5631–5646` |

### 2.2 C++ — Bezier CPs used in **live QP constraints**

| Item | Location | Used by |
| --- | --- | --- |
| Position \(Q_0\ldots Q_3\) | `getCP0`–`getCP3` `5684–5710` | Map bounds `3906–3979`; fixed-Z corridors `4037–4047`; MIQP indicators `4083+` |
| Velocity Bezier CPs | `getVelCP` `5976–5997` | L∞ (and L1/L2) dynamics `4251–4284`, also Safe-FASTER path `156–182` |
| Accel / jerk Bezier CPs | `getAccelCP` `6002–6010`, `getJerkCP` `6014–6018` | same dynamics block |

Algebra (local coeffs \(a,b,c,d\), segment length \(T\)):

- \(Q_0=d\), \(Q_1=c\,T/3+d\), \(Q_2=b\,T^2/3+c\,(2T/3)+d\), \(Q_3=p(T)\)
- \(V_0=c\), \(V_1=c+bT\), \(V_2=c+2bT+3aT^2\)
- \(A_0=2b\), \(A_1=2b+6aT\); jerk \(J=6a\)

### 2.3 C++ — MINVO / BasisConverter (not the fixed-Z constraint basis)

| Item | Location |
| --- | --- |
| `BasisConverter` matrices \(A_{\mathrm{mv}}\), \(A_{\mathrm{be}}\), B-spline converters | `include/sando/sando_type.hpp:210–484` (ctor from `230`; Bezier→MINVO `479–483`) |
| Load \(M_{\mathrm{be2mv}}\), \(A_{\mathrm{mv}}^{-1}\) into solver | `gurobi_solver.cpp:50–53` |
| MINVO pos/vel/acc/jerk from normalized coeffs | `getMinvo*ControlPoints` `5745–5959` (`Vn = Pn * A_pos_mv_rest_inv_`) |
| Example post-check using MINVO position CPs | ~`3777–3790` (containment probe; **not** `setPolyConsts`) |

Python helper that reconstructs **MINVO** (for labeling), not Diff-QP:

- `scripts/integer_set_supervision.py:116–144` (`_MINVO_POS_BASIS_INV`, `segment_control_points`)

### 2.4 Python Diff-QP (KKT path)

| Item | Location |
| --- | --- |
| KKT layer imports `build_spec` / `solve_hard_qp` | `prototypes/time_fixed_z_qp/diff_time_qp_kkt.py:21–29`, forward `157–158` |
| Position / vel / acc / jerk **rows** | `run_time_qp.py:104–110` (`build_spec`) |
| Same formulas in torch rebuild | `diff_time_qp.py:60–89` (`_basis_mats`) |
| Map / dynamics / corridor inequalities from those rows | `run_time_qp.py:131–165` |

Python position rows (applied to \([a,b,c,d]\)):

```text
[0, 0, 0, 1]           → Q0 = d
[0, 0, T/3, 1]         → Q1 = c T/3 + d
[0, T²/3, 2T/3, 1]     → Q2 = b T²/3 + c (2T/3) + d
[T³, T², T, 1]         → Q3 = p(T)
```

These match `getCP0`–`getCP3` after expanding `getCn=cT`, `getBn=bT²` (stdlib algebraic check on random \((a,b,c,d,T)\): exact match). Vel/acc/jerk rows match `getVelCP` / `getAccelCP` / `getJerkCP` the same way.

---

## 3. What “identical / equivalent / inconsistent” means here

### Identical (constraint math)

For fixed-Z production QP:

1. Corridor faces and map bounds constrain **Bezier** position CPs (`getCP*`).
2. L∞ dynamics constrain **Bezier** vel/acc/jerk CPs (`getVelCP` / …).
3. Python Diff-QP builds the **same linear forms** of \((a,b,c,d)\).

So Diff-QP is **not** “a loose node-sample approximation” of the Gurobi constraint set; for this basis it is the **same Bezier hull**.

### Inconsistent (MINVO)

MINVO position CPs \(V = P_n A_{\mathrm{mv}}^{-1}\) differ from Bezier \(Q\) on the same polynomial (example max abs gap ~0.34 on a random cubic).  
`BasisConverter::getMinvoPosConverterFromBezier()` (`sando_type.hpp:479–483`) exists precisely because they are different bases.

Implication:

- Claiming “Python matches MINVO” is **false**.
- Claiming “Python matches production Gurobi fixed-Z constraints” is **supported at the basis level** (Bezier), pending the 50-instance pack for solver/layout/ridge residuals.
- Offline code that uses MINVO for polytope labels (`integer_set_supervision.segment_control_points`) is a **stricter / different hull** than the QP constraints — treat as a separate semantic, not as Diff-QP ground truth.

### Numerically equivalent (existing forward evidence, not Phase-4 complete)

Evidence under `prototypes/time_fixed_z_qp/evidence/`:

| Artifact | What it shows |
| --- | --- |
| `forward_compare.json` | One fixture, several \(f\): status agreement (incl. infeasible); when feasible, Python **jerk** vs Gurobi **objective** rel err \({\sim}1\text{–}4\times10^{-6}\); `all_ok: true` |
| `README.md` (2026-09-09 table) | Same gate summary; native-\(f\) Gurobi vs freezeAssignment pass |
| `diff_time_qp_kkt_probe0.json` / `phase_d_grad_validation_pack16.json` | Gradient vs FD (KKT path) — **not** C++ basis parity |
| Phase E/F train / oneshot JSONs | Training / policy metrics — **not** CP basis audit |

Gaps in that evidence vs plan2 §9.1: single (or few) instances, compares jerk/obj more than exported Bezier/MINVO CP tensors, Python ridge still present, no static/dynamic × difficulty stratified 50-pack.

---

## 4. Known non-basis differences (still real, but not “wrong Bezier”)

1. **Objective ridge:** Python `RIDGE=1e-8` + coefficient scales (`run_time_qp.py:28`, `205–207`). Compare Gurobi to Python **jerk** (or strip ridge), not Clarabel `problem.value`.
2. **Variable packing:** C++ per-axis contiguous; Python segment-major interleaved. Must remap before coefficient diffs.
3. **`compare_control_points` helper** (`run_time_qp.py:275–284`) compares Python CPs to Gurobi **coefficients** — misleading as a parity check; do not use as audit evidence until fixed.
4. **Solver:** Clarabel vs Gurobi can disagree at tiny residuals / borderline infeasibility even with identical matrices.

---

## 5. Still needed — plan2 Phase 4 formal 50-instance experiment

Not done yet. Required by `docs/fromchat/plan2.md` §9.1:

**Sample**

- ≥50 real `PlanningInstance`s  
- Cover static / dynamic / easy / medium (and document seed/map independence per `ENVIRONMENT_AUDIT.md`)

**For multiple factors \(f\)**, compare **C++ Gurobi fixed-Z** vs **Python Diff-QP forward** (`build_spec` + Clarabel):

| Field | Notes |
| --- | --- |
| Status agreement | optimal / infeasible |
| Objective | Gurobi obj vs Python jerk (and optionally ridge-on obj) |
| Trajectory coefficients | after layout remap |
| Position CP | Bezier `getCP*` vs Python `C @ x` |
| Velocity / accel / jerk CP | `getVelCP`… vs Python rows |
| Corridor / map / boundary / continuity residuals | both sides |
| Optional extra column | MINVO CPs from C++ — expect **systematic** mismatch vs Python; do not treat as failure of Bezier parity |

**Pass bar (draft):** on feasible pairs, Bezier CP / coeff max-abs within agreed tol (e.g. `1e-5`–`1e-4` scaled), status match, jerk/obj rel err consistent with `forward_compare` (~1e-5). Document any Clarabel/Gurobi-only disagreements separately from basis bugs.

**If a basis bug appears:** change **Python** Diff-QP only. Do not edit production C++ constraint generators to match the prototype.

---

## 6. Minimal forward-parity check (scripts that already exist)

```bash
# 1) Live C++ Gurobi fixed-Z sweep (container / install-dev)
source /root/sando_ws/src/sando/docker/dev_env.sh   # if applicable
./time_fixed_z_forward_probe \
  /path/to/tests/ampls/fixtures/translated_trajectory.json \
  91659.8128
# writes JSON lines with per-f objective / residuals

# 2) Python Clarabel at native f + FD smoke
cd prototypes/time_fixed_z_qp
python run_time_qp.py \
  --fixture ../../tests/ampls/fixtures/translated_trajectory.json \
  --gurobi-report /path/to/probe_report.json

# 3) Existing multi-f compare artifact (already recorded)
#    prototypes/time_fixed_z_qp/evidence/forward_compare.json
#    prototypes/time_fixed_z_qp/README.md

# 4) KKT Diff-QP gradient probe (not C++ basis parity)
python diff_time_qp_kkt.py --index 0
```

For a **basis** spot-check without the full 50-pack: dump one Gurobi solution’s coeffs, evaluate `getCP0`–`getCP3` / `getVelCP` formulas (or numeric doubles), and compare to `build_spec(...); (spec["C"] @ coeffs)`. Expect near machine agreement. Comparing the same coeffs through `getMinvoPosControlPointsDouble` should **fail** large — that confirms MINVO ≠ Diff-QP, not a Diff-QP bug.

---

## 7. Open checklist

- [x] Locate C++ Bezier vs MINVO call sites for fixed-Z QP  
- [x] Show Python Diff-QP rows ≡ Bezier `getCP*` / `getVelCP` / …  
- [x] Show Python Diff-QP ≢ MINVO / `BasisConverter`  
- [x] Cite existing single-fixture forward numerical evidence  
- [x] 50-instance stratified C++ vs Python formal parity (plan2 §9.1) — **50/50 pass**, max obj rel err `2.47e-6` (`evidence/phase4_parity50.json`)  
- [ ] Fix or replace `compare_control_points` so it does not compare CPs to raw coeffs  
- [ ] Optionally align Python ridge / reporting so objective column matches Gurobi without manual jerk extraction  
- [ ] Amend `docs/diff-time-qp-mapping.md` §2 “node sample” wording after Phase-4 closeout  

---

*Draft only. Production C++ constraint code is the authority; this document audits the Python prototype against it.*
