# Stage Snapshots

Each stage produces one frozen T0 snapshot before both systems run.
Claude produces it. ChatGPT ingests it. Neither modifies it.

Filename: stage_{N}_snapshot.json
Produced by: engine/build_snapshot.py
Frozen at: T0 (≥2 hours before stage start)

Contents:
- rider_universe: all active riders with holdet_id, price, status
- odds_tier_a: implied probabilities for top 20-40 riders (normalized, overround removed)
- expert_intel: structured signals per rider (source, signal_type, direction, weight)
- stage_meta: stage number, type, distance, sprint/KOM locations
- team_state: current 8-rider team, captain, bank balance
- forward_sketches: n+2 and n+3 stage type estimates (user-set sliders)
- expert_sources: list of sources loaded with their current weights
