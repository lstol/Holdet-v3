Stage Snapshots

## Holdet data snapshot (shared with ChatGPT)
Filename: stage_{N}_holdet.json
Produced by: engine/fetch_riders.py + engine/fetch_results.py
Frozen at: T0 (≥2 hours before stage start) for pre-stage
           Also updated post-stage after results confirmed

Contents (Holdet.dk data only):
- rider_universe: all active riders with holdet_id, price, isOut, points
- stage_results: finish positions, jersey holders, GC standings (post-stage)
- team_state: current 8-rider team, captain, bank balance
- stage_meta: stage number, type, distance, sprint/KOM locations
- timestamp: when scraped (for T0 verification)

NOT included (each system gathers independently):
- odds
- expert intel
- probability distributions