# decisions/

Per-stage decision records and override logs.

## File naming convention
`decision_{race_id}_stage{N}.md`

## Contents per file
- T0 snapshot reference
- System A recommendation summary
- System B recommendation summary
- Comparison result (agreement / disagreement / critical decision point)
- Final human decision
- Override records (if any) — override_type, reason, source
- Critical decision point record (if triggered)

## Constraints
- Files are append-only — no retroactive modification
- Override records must include explicit reason and source
- Critical decision point record is mandatory before acting when both systems are HIGH confidence and materially disagree
