# Claude Code — Standing Instructions

**Read this file at the start of every session.**
**Follow the session protocol at the end of every session — no exceptions.**

---

## What this project is

Holdet v3 is a decision-support engine for elite-level play in Holdet.dk's Giro d'Italia 2026 fantasy competition. It is a fantasy optimization engine, not a cycling performance predictor.

Design authority: `rules/Giro_Fantasy_Optimizer_Framing.md` — read this before making any architecture decisions.

Scoring rules and game mechanics: `rules/02_rules_payoff.md`

---

## Repo structure (canonical)

```
holdet-v3/
├── ROADMAP.md                         ← living project roadmap, updated every session
├── CLAUDE_CODE.md                     ← this file
├── rules/
│   ├── 02_rules_payoff.md
│   ├── game_strategy.md
│   └── Giro_Fantasy_Optimizer_Framing.md
├── engine/
│   ├── fetch_riders.py                ← working Holdet.dk scraper
│   ├── capture_cookie.py              ← Playwright cookie capture
│   └── optimizer.py                   ← to be built
├── data/
│   ├── API_NOTES.md
│   ├── riders/                        ← 199 riders with holdet_ids
│   ├── stages/                        ← stage roadbook, sprint/KOM positions
│   ├── intelligence/
│   │   └── expert_sources.yaml        ← expert source weights (user-adjustable)
│   └── snapshots/                     ← stage_N_holdet.json, stage_N_snapshot.json
├── dashboard/
│   └── index.html                     ← decision dashboard
└── sessions/
    └── YYYY-MM-DD_N.md                ← one file per session
```

If any of these directories or files are missing, create them before doing anything else.

---

## Session 2 — immediate tasks

These are the first things to do in the next Claude Code session:

1. **Scaffold missing directories**
   Create `sessions/`, `data/snapshots/`, `dashboard/` if not present.

2. **Create `data/intelligence/expert_sources.yaml`**
   ```yaml
   sources:
     - name: "Emil Axelgaard / TV2 Sport"
       weight: 1.5
     - name: "The Inner Ring"
       weight: 1.2
     - name: "VeloNews"
       weight: 1.0
     - name: "CyclingNews"
       weight: 1.0
     - name: "ProCyclingStats"
       weight: 0.8
     - name: "FirstCycling"
       weight: 0.8
   ```

3. **Wire dashboard to live data**
   - Replace mock rider array in `dashboard/index.html` with a fetch from `data/snapshots/stage_N_holdet.json`
   - Add a minimal local server (`engine/server.py`) with one endpoint:
     - `POST /refresh` → runs `fetch_riders.py`, returns JSON
   - Refresh button in dashboard calls this endpoint

4. **Verify `fetch_riders.py` runs clean**
   Run it, confirm output shape matches the snapshot schema in framing doc Section 12.

5. **Follow session protocol** (see below)

---

## Session protocol — mandatory at end of every session

Every Claude Code session must end with these three steps, in order. No exceptions.

### Step 1 — Update ROADMAP.md

- Mark completed tasks as ✅
- Add any new tasks discovered during the session
- Update the "Last updated" line with session number and date
- Add a row to the session log index table

### Step 2 — Write session log

Create `sessions/YYYY-MM-DD_N.md` (date + session number within that date).

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

## Key rules (never violate these)

- Budget: 50,000,000 kr | Team: exactly 8 riders | Max 2 per real-world team
- Expert source weights are always read from `expert_sources.yaml` — never hardcoded
- Stage-type sliders are user-controlled — AI suggests, user overrides
- `stage_N_snapshot.json` contains only the fields specified in framing doc Section 12
- The optimizer never uses historical rider attributes — odds + expert intel only
- Captain is proposed by the optimizer but always user-overrideable

---

## Operating model (brief)

- **Claude (this system):** Scrapes Holdet.dk, gathers own odds and intel, runs own optimization, drives dashboard
- **ChatGPT:** Ingests `stage_N_snapshot.json` (Holdet data only), gathers own odds and intel independently
- **User:** Sets sliders, confirms Tier-A, overrides at every decision point, makes all final calls
- **Claude Code:** Executes repo work, always ends sessions with protocol above

Disagreement between Claude and ChatGPT is useful signal — it traces to either different probability judgment or different optimization logic. Both are valuable.
