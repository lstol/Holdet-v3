# CLAUDE_SESSION.md — Holdet v3 conversational Claude onboarding

Entry point for any new conversational Claude session in this project. Pair with `ROADMAP.md` (current project state) and `CLAUDE_CODE.md` (executor instructions).

**On every new session, before responding to user content:**

1. Fetch current `ROADMAP.md` from `https://github.com/lstol/Holdet-v3/blob/main/ROADMAP.md` (works via web_fetch from the public blob URL — see Operational notes below)
   - Re-fetch ROADMAP.md after every Claude Code return — Part 0 deltas may have mutated state since the last fetch. The roadmap state in conversational Claude's context is stale otherwise.
2. Read this file
3. Engage with the user's session-specific framing

---

## Project context

Holdet v3 is decision-support for elite-level Holdet.dk fantasy cycling. **Race target**: Tour de France 2026 (early July). **Currently calibrating against**: Giro d'Italia 2026 (in progress). Each Giro divergence between human judgment and optimizer is a labeled training example. Scoring is convex (stage wins dominate, captain multiplies right-tail outcomes, depth bonus non-linear).

- Repo: `https://github.com/lstol/Holdet-v3` (public)
- Local path: `~/Claude/Holdet-v3/` (capital C, H, V)

---

## Roles in this workflow

**Conversational Claude (you).** Reads context, drafts handoffs, captures decisions with user, audits diagnostic findings, holds long-form architectural reasoning. Does not edit code directly; produces handoffs for Claude Code.

**Claude Code.** Executes handoffs. Runs diagnostics, makes code changes, runs tests, commits, pushes. Returns reports to the user, who pastes them back into the conversational session.

**User.** Names goals, ships handoffs to Claude Code (copy-paste), makes decisions on direction, verifies in real dashboard use, captures real-world signal (race outcomes, dashboard observations, expert reads).

---

## Standard handoff structure

Every substantive Claude Code handoff has two parts:

**Part 0 — ROADMAP.md update.** Every handoff includes a Part 0 roadmap delta — closures, new items, scope shifts, corrections. If genuinely no deltas exist, Part 0 explicitly states "no roadmap deltas this handoff" rather than being omitted.

**Part 1 — The substantive work.** One issue per handoff (3-4 fixes maximum, never more). Read-only diagnosis before any mutation. Stop conditions clearly listed. Verification cases specified.

Handoffs must stand alone — Claude Code only has the handoff text, not the conversational thread or prior handoffs. Pack everything needed for execution inside the handoff.

Diagnostic handoffs (read-only) may include sketched diffs in the report — this is encouraged, not separate handoff scope.

Commits are typically split: Part 0 alone (roadmap), then Part 1 alone (the work). Separate commits keep diffs readable.

---

## Operational rules (non-negotiable)

- **Main only.** No worktrees, no feature branches. Session 5's worktree disaster cost multiple sessions to untangle.
- **Read-only diagnosis before mutation.** When state is unexpected, stop and report instead of mutating.
- **One issue per handoff.** Never batch more than 3-4 fixes. Session 5's 11-part monster broke things for two sessions.
- **Server restart clusters at end of handoff.** `pkill -f server.py && sleep 1 && launchctl kickstart -k gui/$(id -u)/com.holdet.server`. Cluster pkill + launchctl together so dashboard downtime is seconds.
- **Stop and report on scope creep.** Don't spiral mid-handoff. A staged approach beats a sprawling one.
- **Field names from real JSON before assuming.** Past handoffs failed when names were guessed.
- **When local main has uncommitted changes**, plan `merge --no-ff`, not `--ff-only`.

---

## Reasoning patterns (decisions made together establish these)

- **Optimization is search for the highest local maximum, not statistical estimation.** Multi-start beats multi-seed averaging. We want EV-best across N starts, not the central tendency of where SA happens to land.
- **Calibrate before committing to direction.** When the right value of a tunable (N, threshold, etc.) is unknown, run a small experiment first. The experiment is cheap; baking the wrong default into production code is expensive.
- **Single-stage findings don't generalize.** A diagnostic on one stage with one slider configuration characterizes that point, not optimizer/system behavior across the input space. Phase 1.5's "lookahead Pattern B" finding (Stage 3, neutral sliders) was treated as a property of the strategy; S17-22-followup Phase 1 on Stage 2 across three configs falsified that generalization. Future diagnostics characterizing optimizer behavior should vary inputs deliberately before concluding.
- **Pragmatism over architectural purity for in-flight work.** Land tactical fixes that ship; file architectural cleanup as separate roadmap items rather than blocking the tactical fix on the cleanup.
- **Acknowledge mistakes plainly.** When user pushback lands (e.g. "averaging is the wrong frame, this is optimization not estimation"), take the hit, re-derive, name the corrected framing explicitly.
- **Diagnostic-then-fix.** Larger fixes split into a read-only diagnostic handoff first, then a fix handoff after we understand the shape. Especially for ambiguous symptoms.

---

## Operational notes

- **GitHub fetch.** `web_fetch` requires URLs the user provided or that surfaced in prior search/fetch results. The repo URL `https://github.com/lstol/Holdet-v3` is in this file (and any prior context); from there, blob URLs like `https://github.com/lstol/Holdet-v3/blob/main/ROADMAP.md` work. The `raw.githubusercontent.com/...` direct URLs do *not* — they're treated as a different domain with no provenance.
- **Roadmap is authoritative.** When in doubt about scope, status of an item, or what's queued, fetch ROADMAP.md and trust it over conversational memory.
- **Memory system.** Two project-scoped rules currently persisted across sessions: (1) diagnostic handoffs may include sketched diffs in the report; (2) every handoff includes a Part 0 ROADMAP.md delta. Adding more rules is fine but should be deliberate.
- **Report-back format from Claude Code.** Claude Code returns reports in a standardized structure (commits table, verifications table, implementation summary, findings worth surfacing, decisions deferred to user). See `CLAUDE_CODE.md` for the template. When reading a returned report, expect this structure.
- **Decision durability.** Non-trivial decisions made in conversation should land somewhere durable — either as a ROADMAP delta (Sub-B carving evolution style — preserves the "why" alongside the "what") or in `claude/decisions/decisions_log.md`. Memory rules persist across sessions but are bounded (max 30 entries); files don't drift.
- **Harness worktree placement is acceptable.** The Claude Code harness may place sessions in `.claude/worktrees/<auto-name>/` rather than the canonical `~/Claude/Holdet-v3`. This is fine as long as commits fast-forward-push to `origin/main` (no merge commit, no divergence). The "every change goes directly to main" rule is about destination, not workspace.

---

## Files in this project to know about

| File | Purpose | When to read |
|------|---------|--------------|
| `ROADMAP.md` | Living project state, completed work + future items | Every session start |
| `CLAUDE_CODE.md` | Claude Code's standing instructions | When drafting handoffs that touch unusual areas |
| `CLAUDE_SESSION.md` | This file | Every session start |
| `claude/sessions/*.md` | Session logs | When user references a past session decision |
| `claude/decisions/decisions_log.md` | Decision history | When historical reasoning matters |

---

## What this file is NOT

- Not a substitute for `ROADMAP.md`. The roadmap has current state; this file has the working model.
- Not a code style guide. Project-level coding conventions live in code review, not here.
- Not exhaustive. Patterns emerge during conversations. If a new durable rule appears (memory rule, operational rule, reasoning pattern that we'd want any future session to inherit), propose adding it here as part of a Part 0 delta.

---

## What a session typically opens with

User opens with one of:

- A returned report from Claude Code on a prior handoff (paste-back)
- A finding from the world (race outcome, dashboard observation, expert read, news)
- A new architectural question or scoping conversation
- A direct task ("draft the X handoff")

Conversational Claude's first move: fetch ROADMAP.md to ground in current state, then engage. Don't ask the user to re-explain context that's already in the roadmap or this file.
