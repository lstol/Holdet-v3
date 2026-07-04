# Tour de France 2026 stage metadata

This directory is scaffolded but not yet populated. Two files are needed for full pipeline parity with Giro:

- `stages_tour2026.json` — canonical stage schedule (start/finish city, terrain type, distance, climbs)
- `stage_scoring.json` — per-stage scoring config (sprint type, intermediate sprint count, climbs)

Populating these files is TdF-MIGRATE Phase 1.6 scope. Until then, the optimizer's `get_stage_config` returns `{}` for Tour stages, which falls back to defaults. Not blocking rider-market and team-state operations.
