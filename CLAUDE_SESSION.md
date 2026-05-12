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
- **Watch for latent invariants exposed by new input paths.** Six instances of this pattern this session: S17-24 (all-zero odds invariant exposed by ✕ buttons), S17-27 (alphabetically-last-snapshot-has-rider-data invariant exposed by per-stage team save), S17-29 (zero-means-missing invariant exposed when top10 odds genuinely unavailable for sprint stages), S17-30 (`AbortController` timeout invariant exposed by structural SA runtime floor), S17-31 (zero-means-missing invariant's second half — don't impute missing data from win — exposed by the same Stage 4 conditions that caught S17-29), and S17-25 (per-rider stage breakdown — Session 15 D₂ correctly diagnosed the gap, but the implementation waited for endpoint discovery, which only came when the user surfaced the Holdet UI screenshot in Session 17). Before shipping any feature that creates a new state-writing path, explicitly enumerate the readers of that state and the invariants they assume. **Additional pattern observation:** fixes themselves can satisfy only part of an invariant. S17-29 enforced the guard at input; S17-31 enforced the no-imputation-at-fallback rule. After landing an invariant-defending fix, audit whether all code paths that touch the invariant respect it, not just the one the symptom surfaced through. **Pattern variant (S17-25):** when a diagnostic correctly identifies a gap but the fix requires an external dependency (an endpoint we don't know about, an API we can't authenticate to, data only accessible via a different surface), the deferred fix carries forward as a known limitation until the dependency resolves. The retrospective question: "is this gap solvable with currently-known dependencies, or are we waiting on something external?" If external, queue with explicit unblock condition. Total: 5 invariant-pattern items + 1 deferred-discovery item.
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
- **Odds invariant — zero means missing.** Across the codebase, treat `win_pct == 0`, `top3_pct == 0`, `top10_pct == 0` (and any future bucket) as missing data, not as zero probability. Odds are never zero by intent; the source of zero is either the ✕ clear button, a parse failure, or a never-gathered bucket. Code paths must either: (a) fall through to a derived fallback (e.g., `build_probabilities` derives top10 from win when top10 is missing), or (b) exclude the row from the affected calculation entirely. Never propagate zero as a literal probability. Specifically: guards like `if value is not None` are insufficient; they leak `0` into downstream calculations. Use `if (value or 0) > 0` instead. Origin: S17-29 diagnostic surfaced that `optimizer.py:306-309` violated this invariant, causing SA gradient collapse on positions 4-15 when top10 was cleared. The invariant is now project-wide; future code touching odds consumers must respect it.

  **Extrapolation principle for missing odds.** When a rider's odds for a position bucket are missing (per the zero-means-missing invariant), the probability model extrapolates from the nearest-in-nature observed bucket, not from win alone. Top10 from top3 (close in nature) preferred over top10 from win (further removed). Win-only fallback only when no closer signal exists. Calibration constants for the extrapolation ratios are documented in `optimizer.py` and recalibrated periodically from empirical stage data (S17-32). This preserves comparability across riders with different data completeness — a rider with sparse odds isn't artificially penalized in EV, but the extrapolation is disclosed and bounded rather than fabricated.
- **Dashboard verification protocol (post-deploy, for any change touching optimizer / odds / results panels):**
  1. **Page load.** Open dashboard with browser console open. No console errors during initial render.
  2. **Odds round-trip.** Paste win / top3 / top10 → `parse-ok` status → all three columns populated → optimizer button enabled.
  3. **Clear round-trip.** Click ✕ on one bucket → column shows `—` (not "0") → disk shows that bucket = 0 → other buckets preserved on disk.
  4. **Optimizer round-trip on a good state.** "Run optimizer" on a stage with non-empty odds → all expected strategy cards render with EV breakdowns → no fetch errors → no console errors.
  5. **Optimizer pre-flight on cleared state.** "Run optimizer" on a stage where every win-odds row was cleared → immediate error message (no 120s timeout) → user can recover by re-pasting odds.
  6. **"How it unfolded".** Target a completed stage → breakdown renders all columns; `—` only where the underlying data field is genuinely 0/missing.
  7. **Optimizer output sanity check** (post-deploy, for any change touching `build_probabilities`, `simulate_stage`, `compute_objective`, or odds consumers). After V4 (full optimizer round-trip), inspect the strategy output JSON. For each strategy, verify:
     - `ev_estimate` falls within plausible bounds (typically 800k–2M for current Giro stage profile; adjust band as race-day calibration accumulates).
     - `ev_net = ev_estimate − transfer_cost` is within similar bounds.
     - Captain assignment is non-empty and consistent with the strategy's optimization target.
     - No strategy returns NaN/Infinity in any EV field.

     Surface-level UX checks (V1–V6) do not exercise the optimizer's internal math. A regression in `build_probabilities`'s normalization, `simulate_stage`'s MC, or `compute_objective`'s weighting will surface here when EVs collapse or balloon in an order-of-magnitude way. **Origin:** S17-29 — `is not None` vs `> 0` guard on top3/top10 silently zeroed positions 4–15 contribution; pre-fix EVs were under-counted ~30–50% and V1–V6 wouldn't have caught it. **Expected-bounds calibration:** keep the 800k–2M band loose for now; tighten as Giro stages 5–21 accumulate. If a stage returns EVs outside the band, that's a "look at this" signal, not a hard failure — race profile may legitimately differ (TT stages, mountain stages with smaller field).
  8. **Stage results breakdown sanity check** (post-deploy, for any change touching `fetch_stage_results` or the rider-breakdown ingestion path). For each rider in `stage_N_results.json`, the sum of per-bonus fields plus `stage_pts` should equal the rider's aggregate `priceChange` reported by the round-history endpoint. Specifically:

     ```
     sprint_pts + jersey_bonus + gc_bonus + team_bonus + stage_placement + penalty == priceChange
     ```

     The captain bonus is tracked separately (`captain_bonus`) and added to `total` independently. If the equality fails for any rider, the field-mapping table has a missing or mis-routed Danish action label. **Origin:** S17-25 Phase 2 — surfacing a future regression where Holdet adds a new action category (e.g., a new jersey type or scoring rule mid-season) would cause silent under-counting if the mapping table doesn't account for it. V8 makes mapping completeness measurable.
  Page-load-only verification (the V1 pattern that missed S17-20's bug surface) does not exercise these paths. End-to-end round-trip is the standard for any change touching these areas.

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
