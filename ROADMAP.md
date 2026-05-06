# Holdet v3 — Project Roadmap

**Race:** Giro d'Italia 2026
**Stage 1:** May 9 (TTT, Durazzo → Tirana, 13.7 km)
**Last updated:** Session 1 (setup)

---

## Status

| Area | Status |
|------|--------|
| Framing doc | ✅ Locked — `rules/Giro_Fantasy_Optimizer_Framing.md` |
| Scoring rules | ✅ Carried from v2 — `rules/02_rules_payoff.md` |
| Game strategy | ✅ Carried from v2 — `rules/game_strategy.md` |
| fetch_riders.py | ✅ Carried from v2 — `engine/fetch_riders.py` |
| capture_cookie.py | ✅ Carried from v2 — `engine/capture_cookie.py` |
| Rider universe | ✅ 199 riders with holdet_ids — `data/riders/` |
| Repo structure | ⏳ Needs scaffold (see Session 2 tasks) |
| expert_sources.yaml | ⏳ Needs creation |
| Dashboard | ⏳ Shell designed, needs wiring |
| Optimizer | ❌ Not started |
| Snapshot schema | ✅ Specified in framing doc Section 12 |
| Session log | ⏳ `sessions/` directory not yet created |

---

## Immediate — before Stage 1 (May 9)

- [ ] Scaffold repo structure (Session 2 — see `CLAUDE_CODE.md`)
- [ ] Create `data/intelligence/expert_sources.yaml` with default weights
- [ ] Wire dashboard to read `stage_N_holdet.json` (replace mock data)
- [ ] Add local dev server endpoint so Refresh button calls `fetch_riders.py`
- [ ] Verify `engine/fetch_riders.py` runs clean against live Holdet.dk
- [ ] Run pre-Stage 1 data fetch and commit `data/snapshots/stage_1_holdet.json`
- [ ] Claude gathers odds + expert intel for Stage 1
- [ ] Produce `stage_1_snapshot.json` for ChatGPT handoff

---

## Pre-race workflow (each stage)

1. `python3 engine/fetch_riders.py` → `stage_N_holdet.json`
2. Gather odds snapshot
3. Gather expert intel (per `expert_sources.yaml`)
4. Review Tier-A list in dashboard
5. Review and adjust expert weights in dashboard
6. Set stage-type sliders
7. Lock `stage_N_snapshot.json` → commit for ChatGPT
8. Run optimizer → CDF + candidate teams
9. Compare Claude vs ChatGPT output
10. Set captain, submit team

---

## Backlog (post-Stage 1)

- [ ] Build `engine/optimizer.py` — probability construction + team generation
- [ ] CDF output rendering in dashboard Output tab
- [ ] Forward transfer pressure display (n+2, n+3) in dashboard
- [ ] Claude vs ChatGPT comparison view in dashboard
- [ ] Post-stage data refresh (results, jerseys, GC standings)
- [ ] Captain EV display alongside candidate teams
- [ ] Depth bonus table display in Stage controls tab

---

## Session log index

| Session | Date | Summary |
|---------|------|---------|
| Session 1 | Pre-May 9 | Project setup, framing doc locked, dashboard shell designed |

