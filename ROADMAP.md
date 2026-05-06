# Holdet v3 — Project Roadmap

**Race:** Giro d'Italia 2026
**Stage 1:** May 9 (TTT, Durazzo → Tirana, 13.7 km)
**Last updated:** ChatGPT dashboard preservation (2026-05-06)

---

## Status

| Area | Status |
|------|--------|
| Framing doc | ✅ Locked — `shared/rules/Giro_Fantasy_Optimizer_Framing.md` |
| Scoring rules | ✅ Carried from v2 — `shared/rules/02_rules_payoff.md` |
| Game strategy | ✅ Carried from v2 — `shared/rules/game_strategy.md` |
| fetch_riders.py | ✅ Carried from v2 — `claude/engine/fetch_riders.py` |
| capture_cookie.py | ✅ Carried from v2 — `claude/engine/capture_cookie.py` |
| Rider universe | ✅ 199 riders with holdet_ids — `shared/data/riders/` |
| Repo structure | ✅ Clean — claude/ chatgpt/ shared/ layout, no duplicates |
| expert_sources.yaml | ✅ Created — `claude/engine/expert_sources.yaml` (Claude-internal only) |
| chatgpt/ scaffold | ✅ Created — explicit ChatGPT optimizer workspace under `chatgpt/src/` |
| chatgpt/dashboard | ✅ Created — static runnable dashboard + preserved React component source |
| Dashboard | ✅ `claude/dashboard/claude.html` — full expert dashboard built (Session 3) |
| server.py | ✅ `claude/engine/server.py` — local server stub with /refresh, /save-weights, /snapshot |
| claude/output/ | ✅ Created — per-stage Claude optimization output (never written to shared/) |
| Stage images | ✅ 21 images at `shared/data/stage_images/giro_2026/stage-{N}.jpg`, served via GitHub raw URL |
| giro_2026/ subfolder pattern | ✅ Canonical — riders/, stages/, stage_images/ all use race subfolders |
| sessions/notes/decisions | ✅ Under `claude/` — Claude-specific, not shared |
| decisions_log.md | ✅ `claude/decisions/decisions_log.md` — decisions from Sessions 1–2 |
| Optimizer | ❌ Not started — stub at `claude/engine/optimizer.py` |
| Snapshot schema | ✅ Specified in framing doc Section 12 |
| Session log | ✅ `sessions/` directory created |

---

## Immediate — before Stage 1 (May 9)

- [x] Scaffold repo structure into claude/ chatgpt/ shared/ layout (Session 2)
- [x] Create `claude/engine/expert_sources.yaml` with default weights (Session 2b — intelligence is Claude-internal, never in shared/)
- [x] Clean repo: remove duplicates, consolidate claude/, create chatgpt/ stub (Session 2c)
- [ ] Wire dashboard to read `stage_N_holdet.json` (replace mock data)
- [ ] Add local dev server endpoint so Refresh button calls `fetch_riders.py`
- [ ] Verify `claude/engine/fetch_riders.py` runs clean against live Holdet.dk
- [ ] Run pre-Stage 1 data fetch and commit `shared/data/snapshots/stage_1_holdet.json`
- [ ] Claude gathers odds + expert intel for Stage 1
- [ ] Produce `stage_1_snapshot.json` for ChatGPT handoff
- [x] ChatGPT onboarding: scaffold independent optimizer workspace and session log
- [x] Define initial `stage_N_chatgpt.json` output writer scaffold
- [ ] Replace ChatGPT dashboard sample data with `chatgpt/output/stage_N_chatgpt.json`

---

## Pre-race workflow (each stage)

1. `python3 claude/engine/fetch_riders.py` → `shared/data/snapshots/stage_N_holdet.json`
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

- [ ] Build `claude/engine/optimizer.py` — probability construction + team generation
- [ ] CDF output rendering in dashboard Output tab
- [ ] Forward transfer pressure display (n+2, n+3) in dashboard
- [ ] Wire /refresh endpoint to live fetch_riders.py run (test end-to-end)
- [ ] chatgpt/dashboard/chatgpt.html — post-ChatGPT onboarding
- [ ] compare.html dashboard — Claude vs ChatGPT comparison view (post-ChatGPT onboarding)
- [ ] Post-stage data refresh (results, jerseys, GC standings)
- [ ] Captain EV display alongside candidate teams
- [ ] Depth bonus table display in Stage controls tab
- [ ] Decide whether to introduce a React/shadcn/Tailwind/Recharts frontend stack for `chatgpt/dashboard/react/`

---

## Session log index

| Session | Date | Summary |
|---------|------|---------|
| Session 1 | Pre-May 9 | Project setup, framing doc locked, dashboard shell designed |
| Session 2 | 2026-05-06 | Repo restructured into claude/ chatgpt/ shared/ layout; framing doc Section 13 added |
| Session 2b | 2026-05-06 | Fix: expert_sources.yaml moved to claude/engine/ — intelligence is never shared between systems |
| Session 2c | 2026-05-06 | Clean repo: remove duplicates, create chatgpt/ stub, claude/dashboard/claude.html stub |
| Session 2d | 2026-05-06 | Move sessions/notes/decisions under claude/; create decisions_log.md |
| Session 3  | 2026-05-06 | Build claude/dashboard/claude.html (full expert dashboard) + server.py stub |
| Session 2e | 2026-05-06 | claude/output/ created; stage images wired to dashboard; framing doc updated |
| Session 2f | 2026-05-06 | giro_2026/ subfolder structure established; image display fixed; docs updated |
| ChatGPT scaffold | 2026-05-06 | ChatGPT optimizer scaffold, tests, output writer, and static dashboard created |
| ChatGPT dashboard preservation | 2026-05-06 | Proposed React expert dashboard preserved under `chatgpt/dashboard/react/` |
