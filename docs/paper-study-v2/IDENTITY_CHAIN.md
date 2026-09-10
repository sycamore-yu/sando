# Online identity chain (plan2 Phase 2)

Authority: `docs/fromchat/plan2.md` §7  
Baseline: `1e4f9f9` (prior summary hashes) → this change upgrades content hashes.

## What changed

On successful append, `planning_observation_hash` and `corridor_hash` now cover real content:

| Field | Content |
|---|---|
| `map_content_hash` | SHA-256 of filtered base-map point coordinates (`SANDOMAPPTS1`) |
| `global_path_hash` | SHA-256 of global-path vertices (`SANDOPATH1`) |
| Observation hash | A/E state, T, map/path content hashes, dynamic obstacle poses/bboxes, planning limits, Z id / method |
| Corridor hash | T, Z, method, map hash, **every safe polytope hyperplane** `{p,n}` |

Still recorded separately: `trajectory_id`, publish event, `controller_first_use` event (publish ≠ consume).

## Limits (honest)

- Map hash is of the occupied/unknown point list used for corridor decomp (not a full voxel grid dump every tick).
- Corridor hash is of visualization-safe polytopes after the winning factor; assignment Z is included via `z_id`.
- Environment manifest hash is paired at the Python episode layer (`environment_manifest.json`), not yet stamped into every C++ metrics row.

## Files

- `src/sando/sando.cpp` (hash payloads)
- `include/sando/sando.hpp` (`map_content_hash`, `global_path_hash`)
- `src/sando/frozen_planning_observation.cpp` (`sha256BytesHex`)
