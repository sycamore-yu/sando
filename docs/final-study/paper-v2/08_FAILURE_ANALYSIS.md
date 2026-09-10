# 08 Failure analysis

Source: `FAILURE_ATTRIBUTION.json` / `final/FAILURE_ANALYSIS.md`.

| Signal | Value |
|---|---|
| wrong_Z_count_learned | 0 |
| non_success_count | 243 |
| restart_Z_learning | **false** |

Dominant bucket across groups/methods: **execution_tracking** (goal with geometry collision).  
Not wrong-Z dominated → **keep frozen corridor-cost Z**; no Z retrain gate trip.
