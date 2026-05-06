# Holdet v3 — Competition Protocol
# STATUS: DRAFT — rewrite of v2 protocol for v3 architecture

## What is preserved from v2
- Dual-system independence constraint (neither sees the other before lock)
- T0 snapshot discipline (identical frozen data for both systems)
- Critical decision point trigger (both HIGH confidence, material disagreement)
- Decision record structure (which system followed, overrides, reasons)
- Post-stage review dimensions

## What is changed from v2
- Probability model: odds+expert replaces affinity priors
- Shared data: Claude produces stage_N_snapshot.json, ChatGPT ingests
- Dashboard: shared with flip between Claude view and ChatGPT view
- Expert source weights: user-controlled in dashboard, not hardcoded
- Risk: presented as CDF / outcome distribution, not optimizer input
- Captain: explicit per-stage decision, not inherited

## TODO: Full rewrite required before Stage 2
See Giro_Fantasy_Optimizer_Framing.md Section 10 for workflow.
