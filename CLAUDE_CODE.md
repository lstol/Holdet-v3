# Claude Code — Standing Instructions

**Read this file at the start of every session.** Pair with `ROADMAP.md` (current project state — fetch / read on session start; authoritative for status of all work items) and `CLAUDE_SESSION.md` (conversational Claude's onboarding — see for cross-reference on the workflow).

---

## Session start procedure

Before executing any work:

1. Read this file.
2. Read `ROADMAP.md` to ground in current state — what's recently closed, what's in flight, what's queued.
3. Receive the handoff from the user. Handoffs are self-contained — everything you need to execute is inside the handoff itself. You do not need conversational thread or prior handoffs.

---

## What this project is

Holdet v3 is a decision-support engine for elite-level play in Holdet.dk's fantasy cycling competitions. **Race target**: Tour de France 2026 (early July). **Currently calibrating against**: Giro d'Italia 2026.

Design authority: `shared/rules/Giro_Fantasy_Optimizer_Framing.md` — read before making any architecture decisions.
Scoring rules: `shared/rules/02_rules_payoff.md`.

---

## Repo structure (canonical)

```
holdet-v3/
├── ROADMAP.md                         ← living project state — authoritative
├── CLAUDE_CODE.md                     ← this file (executor instructions)
├── CLAUDE_SESSION.md                  ← conversational Claude's onboarding
├── claude/
│   ├── engine/
│   │   ├── server.py                  ← Flask server, port 5050
│   │   ├── optimizer.py               ← four-strategy SA optimizer
│   │   ├── scraper.py                 ← Playwright scrapers (TV2, Feltet, TV2 standings)
│   │   ├── fetch_riders.py            ← Holdet.dk API client
│   │   ├── expert_sources.yaml        ← per-source weights (Claude-internal)
│   │   └── API_NOTES.md
│   ├── dashboard/
│   │   └── claude.html                ← single-page dashboard
│   ├── output/                        ← per-stage optimizer output
│   ├── sessions/                      ← session logs (one file per Claude Code session)
│   ├── notes/
│   ├── decisions/
│   │   └── decisions_log.md
│   ├── diagnostics/                   ← re-runnable diagnostic scripts
│   └── logs/
├── chatgpt/                           ← ChatGPT/Codex domain — never modify
└── shared/
    ├── data/
    │   ├── riders/giro_2026/
    │   ├── stages/giro_2026/
    │   ├── stage_images/giro_2026/
    │   └── snapshots/                 ← stage_N_*.json files (holdet, intel, odds, results, standings, ingemann)
    └── rules/
        ├── 02_rules_payoff.md
        ├── game_strategy.md
        └── Giro_Fantasy_Optimizer_Framing.md
```

**Architecture invariants:**

- `chatgpt/` is ChatGPT/Codex's directory — never create or modify files there
- `shared/rules/` is the single source of truth for rules and framing docs
- `shared/data/` contains Holdet.dk data and snapshots only — no intelligence config, no source weights, no odds data
- Expert source weights live at `claude/engine/expert_sources.yaml` — Claude-internal, never under `shared/`
- Each race gets its own subfolder under `riders/`, `stages/`, `stage_images/`. Canonical pattern for multi-race support.
- Claude output writes to `claude/output/` — never to `shared/`

If any directory is missing, create it before doing anything else.

---

## How handoffs work

Conversational Claude drafts handoffs; you execute them. Standard handoff structure:

**Part 0 — ROADMAP.md update.** Every handoff includes a Part 0 delta — closures of completed items, new items added, scope shifts, corrections. If Part 0 is genuinely empty, the handoff says so explicitly.

**Part 1 — The substantive work.** One issue per handoff (3-4 fixes maximum, never more). Includes:
- Scope (which files, what changes)
- Implementation guidance (sometimes with sketched diff)
- Verification cases (numbered, mechanically checkable)
- Stop conditions (when to halt and report rather than mutating)
- Commit message format

Diagnostic handoffs (read-only) may include sketched diffs in your report — proposing changes is encouraged, commit only after user confirms. This is a standing rule.

---

## Handoff execution protocol

When you receive a handoff:

1. **Read the entire handoff first.** Don't start executing partway through. Note the stop conditions before you start.

2. **Apply Part 0 (ROADMAP delta).** For each delta:
   a. Verify pre-apply state by grepping for the specific item ID in `ROADMAP.md`. Report what's currently there (e.g. "S17-21: not present" or "S17-21: shows as 🟡 in flight on line 187").
   b. Apply the delta only if the current state genuinely differs from the target. "Already applied" means the exact ID + status icon + delivered note are present — section existing or wording being similar is NOT sufficient grounds to skip.
   c. If a delta conflicts with current state in ways that suggest concurrent edits, surface and stop.
   d. Commit Part 0 alone with the message specified in the handoff (typically `roadmap: ...`).

   After Part 0 commit, fetch ROADMAP.md from GitHub raw and verify each delta is now present. State this verification step in the report.

3. **Execute Part 1.** Follow the handoff's scope, implementation guidance, and verification cases. Respect stop conditions absolutely — when in doubt, stop and report.

4. **Verify.** Run all listed verification cases. Capture results to surface in the report. Do not commit if any verification fails or any stop condition triggers — surface the finding instead.

5. **Commit Part 1 alone.** Separate from Part 0 — separate diff = readable diff. Use the commit message specified in the handoff.

6. **Restart server if needed.** When `optimizer.py`, `server.py`, or related Python files changed, restart at the very end:
   ```
   pkill -f server.py && sleep 1 && launchctl kickstart -k gui/$(id -u)/com.holdet.server
   ```
   Cluster `pkill` + `launchctl` together so dashboard downtime is seconds, not minutes. Verify server is up: `curl http://localhost:5050/`.

7. **Return report to user** in standard format (see below).

---

## Standard report-back format

Reports are returned in chat for the user to paste back to conversational Claude. Use this structure:

```
[Brief one-line summary if the result is unambiguous, or skip if findings are nuanced]

Both commits pushed:
| Commit  | Scope                          |
|---------|--------------------------------|
| abc1234 | Part 0 — ROADMAP delta         |
| def5678 | Part 1 — [substantive change]  |

Verifications
| Check                          | Result        |
|--------------------------------|---------------|
| V1 [description]               | ✅ [outcome]  |
| V2 [description]               | ❌ [reason]   |

[Implementation summary — what files changed, what the change does in 2-4 sentences]

Roadmap state after Part 0
- [One-line summary: which IDs are now closed, which are in flight, which were just added.
  Example: "S17-21 Phase 1 + 1.5 closed; S17-2 + S17-23 closed; S17-22 in flight; no other state changes."]

Findings worth surfacing
- [Anything surprising, opaque, or worth flagging — e.g. unexpected line counts, runtime concerns, side findings]

Decisions deferred to user
- [Anything the handoff explicitly left for user to decide post-execution, e.g. "Tier A merge call: recommend X, awaiting confirmation"]

Pre-existing main working-tree files (riders.json, etc.) untouched throughout.
```

Adapt as needed — drop sections that aren't relevant. The fixed elements are: commits, verifications, anything that diverged from the handoff plan.

---

## Operational rules (non-negotiable)

These match the rules in `CLAUDE_SESSION.md`. In case of conflict, that file is source of truth.

- **Never use git worktrees.** Every change goes directly to main. If a worktree exists, merge and delete it before doing anything else.
- **Read-only diagnosis before mutation.** When state is unexpected, stop and report instead of mutating.
- **One issue per handoff.** Never batch more than 3-4 fixes.
- **Stop and report on scope creep.** Don't spiral mid-handoff. Respect the stop-conditions section.
- **Server restart clusters at end of handoff.** Cluster `pkill` + `launchctl` so downtime is seconds.
- **Verify field names from real JSON before assuming.** Past handoffs failed when names were guessed.
- **When local main has uncommitted changes**, plan `merge --no-ff`, not `--ff-only`.

---

## Diagnostic script disposition

When a diagnostic handoff produces a script (e.g., the N-curve experiment in S17-21 Phase 1.5):

- **Re-runnable and likely useful again** → commit to `claude/diagnostics/`. Self-contained (no dependencies on changing optimizer internals). Top-of-file comment documents the canonical reproducer (stage, slider state, etc.).
- **One-off, unlikely to be re-run** → leave at `/tmp/`, discard after report lands. Mention disposition in report.
- **Default when uncertain**: commit. Storage is cheap, re-derivation is not.

---

## Game rules (project facts, hardcoded by Holdet.dk)

These are facts about the game, not rules for execution.

- Budget: 50,000,000 kr
- Team: exactly 8 riders
- Max 2 per real-world team
- Captain proposed by optimizer, user overrides
- Stage-type sliders are user-controlled — optimizer suggests, user decides
- The optimizer never uses historical rider attributes — odds + expert intel only

---

## Daily use

Dashboard always at `http://localhost:5050`.

Flask server starts automatically on login via LaunchAgent: `~/Library/LaunchAgents/com.holdet.server.plist`. Source: `claude/tools/com.holdet.server.plist` — uses `/usr/local/bin/python3`.

Manual control:

```
launchctl load   ~/Library/LaunchAgents/com.holdet.server.plist
launchctl unload ~/Library/LaunchAgents/com.holdet.server.plist
# or directly:
python3 claude/engine/server.py
```

Logs: `claude/logs/server.log` and `claude/logs/server-error.log`

`claude/tools/Open Dashboard.app` — opens http://localhost:5050
`claude/tools/Holdet Refresh.app` — runs holdet-refresh.sh

**Setup requirements:**

```
pip install flask anthropic pyyaml python-dotenv
pip install playwright --break-system-packages
playwright install chromium
```

`.env` must contain:

```
ANTHROPIC_API_KEY=sk-ant-...
HOLDET_COOKIE=...
HOLDET_FANTASY_TEAM_ID=...
HOLDET_CARTRIDGE=...
```

---

## Session protocol — end of session

Per-handoff Part 0 deltas update ROADMAP continuously, so end-of-session steps are simpler than the older protocol:

### Step 1 — Write session log

Create `claude/sessions/YYYY-MM-DD_N.md`:

```
# Session N — YYYY-MM-DD

## What was built
[Bullet list of concrete deliverables across all handoffs in the session]

## Decisions made
[Any architectural or design decisions with rationale, or pointers to where they're recorded]

## Open questions
[Anything unresolved — should already be in ROADMAP via Part 0 deltas]

## Next session tasks
[Concrete first steps for next session — already in ROADMAP via Part 0]
```

### Step 2 — Push

```
git push
```

If commits weren't pushed during the session (per-handoff push is fine and preferred for incremental visibility).

---

## Operating model

- **Conversational Claude** drafts handoffs; reads context, captures decisions, audits diagnostic findings. Does not edit code.
- **Claude Code (you)** executes handoffs: diagnostics, code changes, tests, commits, pushes.
- **User** sets goals, ships handoffs to you, makes decisions on direction, verifies in real dashboard use.

Disagreement between optimizer outputs and human judgement is useful signal — captured in `claude/decisions/decisions_log.md` as a learning artifact when it shows architectural insight.
