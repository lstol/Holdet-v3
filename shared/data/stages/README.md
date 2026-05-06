# data/stages/

Layer 1 — Race-State stage profiles.

## Current files

| File | Race | Stages | Total km | Generated |
|------|------|--------|----------|-----------|
| `stages_giro2026.json` | Giro d'Italia 2026 | 21 | 3459.2 km | 2026-05-04 |

## File naming convention
`stages_{race_id}.json`
Example: `stages_giro2026.json`

## Contents per stage
- stage number, name, date
- distance, elevation profile
- terrain classification (flat / hilly / mountain / ITT / TTT)
- designated sprint locations and IDs
- designated KOM locations, IDs, and categories
- TTT flag (boolean)
- weather snapshot (at T0)

## Constraints
- Weather must be snapshotted at T0 — no live updates after freeze
- Stage profiles are read-only during execution
