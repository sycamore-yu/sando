# 09 Limitations

1. Geometry-aware collision rates are high for **all** methods (~70–100%); collision-free goal is often near 0 on medium density. Learning does not fix execution safety here.
2. Formal sample is 30 seeds × 3 groups; hard static and medium dynamic matrices were not run in this closeout.
3. Original oneshot_append is structurally ~0 (MIQP); fair comparisons emphasize latency, goal, and collision-free rates.
4. DiffOpt closed-loop does not outperform Supervised on these tests — do not overclaim DiffOpt as an online win.
5. Legacy forest seeds 200–229 are repeated maps and are **not** used for map-generalization claims.
6. Attribution is coarse (primary bucket); some residual `other` cases remain.
