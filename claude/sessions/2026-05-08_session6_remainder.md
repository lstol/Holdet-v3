# Session 6 remainder — 2026-05-08

## What was built
- `renderSliders()`: labels now compute from `targetStage` — shows "Stage 2 / Stage 3 / Stage 4" etc.; out-of-range shows "—"
- `loadCurrentTeam()`: fetches `/current-team?target_stage=N`, stores in `window.CURRENT_TEAM_DATA`
- `buildCurrentTeamCard()`: renders locked team as dashed card with rider prices and tiers
- `renderOptimizerOutput()`: current team card inserted second from left after Ingemann
- `loadCurrentTeam()` called on init and on every `setTargetStage()`
