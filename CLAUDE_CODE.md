# Claude Code — Standing Instructions

**Read this file at the start of every session.**
**Follow the session protocol at the end of every session — no exceptions.**

---

## What this project is

Holdet v3 is a decision-support engine for elite-level play in Holdet.dk's Giro d'Italia 2026 fantasy competition. It is a fantasy optimization engine, not a cycling performance predictor.

Design authority: `shared/rules/Giro_Fantasy_Optimizer_Framing.md` — read this before making any architecture decisions.

Scoring rules and game mechanics: `shared/rules/02_rules_payoff.md`

---

## Repo structure (canonical)

```
holdet-v3/
├── ROADMAP.md                         ← living project roadmap, updated every session
├── CLAUDE_CODE.md                     ← this file
├── claude/                            ← Claude's engine and dashboard (Claude only)
│   ├── engine/
│   │   ├── fetch_riders.py            ← working Holdet.dk scraper
│   │   ├── capture_cookie.py          ← Playwright cookie capture
│   │   ├── optimizer.py               ← to be built
│   │   ├── expert_sources.yaml        ← Claude's expert source weights (Claude-internal only)
│   │   └── API_NOTES.md               ← Holdet.dk API reference (Claude-internal)
│   ├── dashboard/
│   │   └── claude.html                ← Claude's decision dashboard
│   ├── output/                        ← per-stage optimization output (Claude only)
│   │   └── stage_N_claude.json
│   ├── sessions/                      ← session logs, one file per Claude Code session
│   ├── notes/                         ← Claude working notes, intel summaries, stage analysis
│   └── decisions/
│       └── decisions_log.md           ← key decisions log with rationale and date
├── chatgpt/
│   └── README.md                      ← ChatGPT/Codex domain — Claude never touches this
├── shared/                            ← Holdet.dk data and snapshots only (both systems read)
│   ├── data/
│   │   ├── riders/
│   │   │   └── giro_2026/             ← 199 riders with holdet_ids
│   │   ├── stages/
│   │   │   └── giro_2026/             ← stage roadbook, sprint/KOM positions
│   │   ├── stage_images/
│   │   │   └── giro_2026/
│   │   │       └── stage-N.jpg        ← 21 stage profile images
│   │   └── snapshots/                 ← stage_N_holdet.json
│   └── rules/                         ← single source of truth for all rules and framing docs
│       ├── 02_rules_payoff.md
│       ├── game_strategy.md
│       └── Giro_Fantasy_Optimizer_Framing.md
```

**Architecture notes:**
- `chatgpt/` is ChatGPT/Codex's directory — Claude never creates or modifies files there
- `shared/rules/` is the single source of truth for all rules and framing docs — no copies elsewhere
- `shared/` contains Holdet.dk data and snapshots only — no intelligence config, no source weights, no odds data. Schema defined in framing doc Section 12
- Expert source weights are at `claude/engine/expert_sources.yaml` — Claude-internal, never placed in shared/
- Each race gets its own subfolder under `riders/`, `stages/`, and `stage_images/` (e.g. `giro_2026/`, `tdf_2026/`). This is the canonical pattern for multi-race support.

If any of these directories or files are missing, create them before doing anything else.

---

## Sessions 2 / 2b / 2c — completed (2026-05-06)

- ✅ Restructured repo into `claude/` / `chatgpt/` / `shared/` layout
- ✅ Created `claude/engine/expert_sources.yaml` (intelligence is Claude-internal, not shared)
- ✅ Created `claude/engine/optimizer.py` stub
- ✅ Created `claude/dashboard/claude.html` stub
- ✅ Created `chatgpt/` directory with README (ChatGPT scaffolds its own structure)
- ✅ Removed duplicates and extra directories from `shared/`
- ✅ Moved sessions/, notes/, decisions/ under claude/
- ✅ Created `claude/decisions/decisions_log.md` with decisions from Sessions 1–2
- ✅ Updated framing doc with Section 13 (System Architecture)
- ✅ Updated ROADMAP.md and CLAUDE_CODE.md to reflect clean structure

## Session 3 — immediate tasks

1. **Wire dashboard to live data**
   - Replace mock rider array in `claude/dashboard/claude.html` with a fetch from `shared/data/snapshots/stage_N_holdet.json`
   - Add a minimal local server (`claude/engine/server.py`) with one endpoint:
     - `POST /refresh` → runs `fetch_riders.py`, returns JSON
   - Refresh button in dashboard calls this endpoint

2. **Verify `fetch_riders.py` runs clean**
   Run `python3 claude/engine/fetch_riders.py`, confirm output shape matches the snapshot schema in framing doc Section 12.

3. **ChatGPT onboarding**
   Draft CODEX.md standing instructions for ChatGPT. Define stage_N_chatgpt.json output schema.

4. **Follow session protocol** (see below)

---

## Session protocol — mandatory at end of every session

Every Claude Code session must end with these three steps, in order. No exceptions.

### Step 1 — Update ROADMAP.md

- Mark completed tasks as ✅
- Add any new tasks discovered during the session
- Update the "Last updated" line with session number and date
- Add a row to the session log index table

### Step 2 — Write session log

Create `claude/sessions/YYYY-MM-DD_N.md` (date + session number within that date).

Template:
```markdown
# Session N — YYYY-MM-DD

## What was built
[Bullet list of concrete deliverables]

## Decisions made
[Any architectural or design decisions, with brief rationale]

## Open questions
[Anything unresolved that needs a decision next session]

## Next session tasks
[Concrete first steps for next session — these go into ROADMAP.md too]
```

### Step 3 — Commit and push

```bash
git add .
git commit -m "session N: [one-line summary of what was done]"
git push
```

The commit message must start with `session N:` so the log is easy to scan.

---

## Daily use

```
claude/tools/Open Dashboard.app    → opens the dashboard directly (add to Dock)
claude/tools/Holdet Refresh.app    → fetches latest data, rebuilds dashboard, reopens
```

Both apps live in `claude/tools/` and are machine-specific (not committed).
To rebuild them: `osacompile -o "claude/tools/Holdet Refresh.app" -e 'do shell script "bash /Users/lassestoltenberg/Claude/Holdet-v3/claude/engine/refresh.sh"'`

Manual equivalent: `bash claude/engine/refresh.sh`

---

## Key rules (never violate these)

- Budget: 50,000,000 kr | Team: exactly 8 riders | Max 2 per real-world team
- Expert source weights are always read from `claude/engine/expert_sources.yaml` — never hardcoded, never placed in shared/
- Stage-type sliders are user-controlled — AI suggests, user overrides
- `stage_N_snapshot.json` contains only the fields specified in framing doc Section 12
- The optimizer never uses historical rider attributes — odds + expert intel only
- Captain is proposed by the optimizer but always user-overrideable
- Claude never creates or modifies files under `chatgpt/` — that directory belongs to ChatGPT/Codex
- Claude output is always written to `claude/output/` — never to `shared/`

---

## Operating model (brief)

- **Claude (this system):** Scrapes Holdet.dk, gathers own odds and intel, runs own optimization, drives dashboard
- **ChatGPT:** Ingests `stage_N_snapshot.json` (Holdet data only), gathers own odds and intel independently
- **User:** Sets sliders, confirms Tier-A, overrides at every decision point, makes all final calls
- **Claude Code:** Executes repo work, always ends sessions with protocol above

Disagreement between Claude and ChatGPT is useful signal — it traces to either different probability judgment or different optimization logic. Both are valuable.
