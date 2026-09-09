# Stage8 queryer coverage (backfill primary set)

Same-factor reference queries succeed on all 10 backfill items (with or without run sidecars).

Loading run `obstacles.json` / `config.json` removes `obst_pos`, `obst_bbox`, and
`environment_assumption` from the missing set.

New-factor queries (e.g. `1.37`) remain **`blocked_missing_observation`** on all items.
Remaining missing fields: `visible_map`, `global_path`, `v_max`, `a_max`, `j_max`.

Part1 must re-capture or patch reconstructable observation (especially voxel map + global path
+ dynamics limits) before multi-T enumeration and stage7 `time_only` / `joint` arms.
