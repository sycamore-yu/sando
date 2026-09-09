# Stage8 queryer coverage (backfill primary set)
Same-factor reference queries succeed on all 10 backfill items.
New-factor queries (e.g. 1.37) are **blocked_missing_observation** on all items.
Union of missing fields: `visible_map`, `obst_pos`, `obst_bbox`, `global_path`, `environment_assumption`, `v_max`, `a_max`, `j_max`.

Part1 must re-capture or patch reconstructable observation before multi-T enumeration.
