# Holdet v3 — Roadmap

Living document. Replaces the prior roadmap section in the v5 onboarding doc. Tracks completed work across sessions and future planned work.

**Project**: Holdet v3 (repo at `~/Claude/Holdet-v3/`)
**Race target**: Tour de France 2026 (early July). Giro d'Italia 2026 is calibration.
**Last updated**: May 10, 2026 (Session 17 close pending; Sub-B Design Diagnostic landed).

---

## Update protocol

- Every substantive Claude Code handoff includes a Part 0 ROADMAP.md delta capturing changes since the last roadmap update — closures, new items, scope shifts, corrections. If genuinely no deltas, Part 0 explicitly states "no roadmap deltas this handoff" rather than being omitted. Standing rule.
- Update at the close of each handoff that completes scope, or when scope changes mid-session
- Each item carries: ID, status, one-line description, optional notes
- Status values: ✅ closed, 🟡 in flight, ⏳ queued, 💭 decision pending, ❌ withdrawn
- When an item closes, add a brief "delivered" note (one line) capturing what actually shipped vs. originally planned — divergence is the learning artifact

---

## Completed work

### Session 1 — repo establishment (closed, ~2026-05-05/06)[^s1]

- ✅ Holdet v3 repo established with structure carried from v2 (commit `2527374`).
- ✅ Initial roadmap and Claude Code standing instructions added (commit `afa1fe7`).

### Session 2 — repo restructure (closed, 2026-05-06; spans sub-files 2 / 2b / 2c / 2d / 2e / 2f)

- ✅ Repo restructured into `claude/` / `chatgpt/` / `shared/` top-level layout.
- ✅ `expert_sources.yaml` placed at `claude/engine/` (Claude-internal only).
- ✅ `shared/rules/` declared single source of truth for rules + framing docs; framing doc Section 13 (System Architecture) added.
- ✅ `claude/decisions/decisions_log.md`, `claude/notes/`, `claude/sessions/` established under `claude/`; ChatGPT scaffolds its own equivalents independently.
- ✅ `claude/output/` added; convention "each system writes output to its own directory, never to `shared/`."
- ✅ Stage images (21 files, `stage-1.jpg` → `stage-21.jpg`) tracked under `shared/data/stage_images/`. Dashboard switched to `<img>` with GitHub raw URL fallback for `file://` mode.
- ✅ `shared/data/` reorganised into `giro_2026/` subfolders (`riders/giro_2026/`, `stages/giro_2026/`, `stage_images/giro_2026/`) — canonical pattern for multi-race support.
- ✅ ChatGPT optimizer workspace scaffolded (`3e15312`).

### Session 3 — initial dashboard + server (closed, 2026-05-06)[^s3]

- ✅ `claude/dashboard/claude.html` — full single-page dashboard: header (stage title, bank, status, refresh), stage carousel for S1–S21, n+1/n+2/n+3 stage-type sliders with sum validator, expert-weight sliders, editable bookmaker odds table, intel notes textarea, candidate teams area, full 210-rider table with search + filter pills + dynamic Tier (A/B) + Force In/Out toggles + status badge.
- ✅ `claude/engine/server.py` — local Flask server: `POST /refresh`, `POST /save-weights`, `GET /snapshot`, `GET /files/<path>`, `GET /dashboard`.

### Session 4 — dashboard hardening + standalone mode (closed, 2026-05-07)

- ✅ `build_dashboard.py` — embeds `window.RIDERS_DATA` and `window.STAGES_DATA` inline so the dashboard works as `file://` with no server needed.
- ✅ `fetch_riders.py` verified live against Holdet.dk API; 184 active riders locked into `stage_1_holdet.json`. Two-mode filter (initial run filters active; subsequent runs preserve the locked set despite mid-race withdrawals).
- ✅ One-click refresh: `claude/engine/refresh.sh`, `claude/tools/holdet-refresh.sh`, `HoldetRefresh.app` AppleScript app, `holdet://` URL scheme registered with `lsregister`.
- ✅ Column sorting on all rider table columns (`COLS` / `getSortVal()` / `setSort()` / `renderTableHeader()`).
- ✅ All 21 stages in carousel; previously stub showed only a subset.
- ✅ `TYPE_FIT` matrix replaces unreliable `terrain_affinity` formula for tier assignment.
- ✅ Slider auto-balance (proportional redistribution to sum 100%).
- ✅ Stage-relevance odds table — top-30 ranked by `riderStageScore()` (type fit × current stage weights).
- ✅ Decision: embed data, don't fetch. Dashboard works standalone; server.py kept for future optimizer use.

### Session 5 — server rewrite + scrapers + four-strategy optimizer (closed, 2026-05-08; multi-part, two log files)[^s5]

- ✅ `claude/engine/server.py` rewritten as proper Flask app on port 5050: CORS, dotenv, `sys.executable` subprocess, LaunchAgent auto-start (`claude/tools/com.holdet.server.plist`), logging to `claude/logs/`.
- ✅ `POST /parse-odds-image` — vision endpoint accepting base64 screenshots → `claude-haiku-4-5-20251001` → JSON odds array. Cmd+V paste handler on `#odds-panel`.
- ✅ Decision: odds via screenshot paste, not API. Every major bookmaker site is Cloudflare-protected; The Odds API has no cycling catalog; web_search hits rate limits. Vision-on-screenshot is the clean path. `/gather-odds` removed.
- ✅ `claude/engine/scraper.py` — Playwright scrapers for TV2 (Axelgaard preview), Feltet (stage analysis + Ingemann team), Inner Ring (no login). `scrape_all_intel()` orchestrates concurrently.
- ✅ `claude/engine/optimizer.py` — four-strategy SA optimizer: `compute_transfer_cost`, `build_forward_probabilities` (slider-based type inference), `estimate_forward_costs` with `fast_optimize`, `compute_objective` with 4 modes (`ev`, `depth`, `low_transfer`, `lookahead`), `generate_candidate_teams` (one SA chain per strategy).
- ✅ `LOOKAHEAD_DISCOUNT = 0.7`, `TRANSFER_COST_RATE = 0.01` (1% buy price).
- ✅ Decision: four strategies always returned (no dedup, no sort by EV) — preserves each strategy's distinct recommendation.
- ✅ `POST /gather-intel` rewritten — Playwright scrape + single Haiku structuring call → `stage_N_intel.json`. `POST /gather-ingemann`, `POST /score-ingemann`, `GET /load-ingemann-scored` round trip for Ingemann benchmark card. `GET /current-team`, `GET /stage-results`.
- ✅ Stage 1 date corrected (May 8 not May 9, Nessebar → Burgas).
- ✅ Dashboard: `targetStage` separated from carousel display index; target-stage dropdown; `renderOptimizerOutput` redesigned with Ingemann card leftmost + four strategy cards with forward cost components.

### Session 6 — state persistence + intel structuring (closed, 2026-05-08)

- ✅ Slider persistence — `localStorage('holdet_sliders')` write/restore.
- ✅ Odds bucket merging fix — win-paste handler zeroes only `r.win` (preserves `top3`/`top10` from prior pastes); server-side `/parse-odds-image` already merged on `stage_N_odds.json`.
- ✅ Intel scraper improvements — TV2 search starts from Axelgaard's author profile; Feltet stage-analysis pattern simplified; multi-page cross-section search added.
- ✅ Feltet login fixed — `/login` with `wait_until='load'` → dismiss "Tillad alle" → click `a[href*="/api/auth/login"]` → jppol.dk Auth0 OAuth flow → email + password screens. Confirmed working: 5,506 chars returned for stage 2 analysis.
- ✅ Two-step `/gather-intel` — search prose first, structure JSON second (commits `a5716d2`, `b7b7c8a`, `3695491`).
- ✅ "Session 6 remainder": slider labels show actual stage numbers based on `targetStage`; `loadCurrentTeam()` + current team card rendered in optimizer output as second-from-left.

### Session 7 — stage selector polish (closed, 2026-05-08)

- ✅ Header cleanup — removed "Preparing for" / "· Next stage: N" labels; just "Next stage" + dropdown.
- ✅ Dropdown back to `<select>` with explicit colours (Safari was rendering frozen number-input).
- ✅ `initStageSelect()` populates options 1–21 using `st.date > TODAY` (today's completed stage not re-targeted); `setTargetStage` guards against NaN/0/out-of-range.
- ✅ `renderTable()` adds `r._type` guard (`const rtype = r._type || 'Lead-out'`) preventing TypeError when riders load without a type.

### Session 8 — stabilisation fixes (closed, 2026-05-08)[^s8]

- ✅ Several small fix commits between sessions 7 and 9 — refresh restored to riders-only, server-msg visibility, label wording, null-safe rider count, team URL revert to `BASE_URL`, SystemExit catch in `/refresh` to prevent server crash on auth failure, null-guard `h-stage-title` (root cause of empty rider table).

### Session 9 — rider table diagnostics + manual team entry (closed, 2026-05-08)

- ✅ Diagnostic logging in `loadRiders()` and `renderTable()` (per-row try/catch, `rid` fallback to `r.name`).
- ✅ `fetch_team_as_dict()` URL fix — was using `BASE_URL` (API backend); switched to `https://holdet.dk/da/{cartridge}/me/fantasyteams/{fantasy_team_id}`.
- ✅ Manual team entry panel — full section with "Current team" header, edit button, textarea (9 rows), captain input, Save/Cancel.
- ✅ `loadCurrentTeam()` 3-tier fallback — localStorage → `/current-team` API → empty/edit prompt.
- ✅ `POST /save-current-team` endpoint writes `team_composition` + `captain` into `stage_N_holdet.json`.

### Session 10 — Stage 2 readiness (closed, 2026-05-08)[^s10]

- ✅ Single commit `4393ccb session 10: stage 2 readiness — expert weights, optimizer, intel verified`. Verification pass before Stage 2 race; no functional changes captured in dedicated log.

### Session 11 — five fixes (closed, 2026-05-08)

- ✅ **Fix 1** — Carousel pill display-only: removed `setTargetStage()` from pill `onclick`; pills update display index without reloading optimizer/odds/intel.
- ✅ **Fix 2** — Expert weights `localStorage` persistence (mirrors slider persistence pattern).
- ✅ **Fix 3** — Inner Ring removed from `S.expertSources` and `expert_sources.yaml` due to time-pressured decision after stale-data scraping was observed (showed 2024 Giro riders). Scraper still fetches Inner Ring text but Haiku's prompt no longer assigns it a named weight. **NOT a permanent retirement** — flagged for repair under S18-7.
- ✅ **Fix 4** — Ingemann JSON extraction: regex `\{.*\}` (DOTALL) replaces strict `json.loads(raw.strip())`, plus tighter prompt ("No text before or after. No markdown fences").
- ✅ **Fix 5** — Stage results from players API. Probing nexus `/api/games/{id}/rounds/*` revealed Next.js HTML, not JSON. Players API is the only real JSON endpoint; cumulative `points` field after stage scoring. New flow: fetch players API → cross-reference with team snapshot → write `stage_N_results.json`. `fetchStageResults()` calls `renderStageResults()` directly.
- ✅ **Fix 5b** (cont) — `fetch_stage_results` falls back to live `fetch_team_as_dict()` call when snapshot's `team_composition` is empty; persists composition back into snapshot for subsequent calls.

### Session 12 — Ingemann polish + transfer cost surfacing (closed, 2026-05-08)[^s12]

- ✅ Single commit `75698a0 Session 12: ingemann body logging, rider name matching, placeholder card`.
- ✅ `db5e3e5` — `transfer_cost` added to optimizer output and card display.

### Sessions 13–14 — pre-S15 cleanup (closed, 2026-05-08/09)[^s13]

- ✅ `6ddbf16` Removed API optimizer button; renamed `/run-optimizer-py` → `/run-optimizer`; fixed Holdet snapshot.
- ✅ `1643e92` Fixed `runPyOptimizer`: button ref updated.
- ✅ `bb71b7e session 15 snapshot: pre-merge state — stage 2 odds/intel/ingemann, riders refresh, Feltet weight 1.3→1.0` — Feltet weight in `expert_sources.yaml` adjusted to 1.0 here.

### Session 15 — Stage 2 prep, multiple handoffs (closed, 2026-05-09)

- ✅ **Handoff A** (read-only diagnostic) — Two real bugs surfaced:
  - Current-stage slider was ignored (`build_probabilities` had `sliders=None` in signature but body never referenced it).
  - Forward stages couldn't differentiate riders by type — `r.get('type', 'All-rounder')` always fell through because `riders.json` carries `terrain_affinity` not a top-level `type` key. Every rider got the same `TYPE_WIN_WEIGHT` scalar; renormalisation produced uniform 1/N. Forward fast_optimize chose undifferentiated teams.
- ✅ **Handoff B** — Current team sourced from previous stage's `stage_{prev}_results.json` (post-stage scored rider list), not target-stage holdet snapshot. Case-insensitive fallback added (`Dries van Gestel` vs `Dries Van Gestel` had been silently dropping a rider 7/8). B-tail removed redundant manual Current Team panel; "How it unfolded" panel is the single source of truth.
- ✅ **Handoff D₁** — Bank display removed from header; Refresh button renamed "Refresh riders"; EV breakdown row label "Total" renamed "Net EV"; `Σ(rendered_breakdown_rows) = ev_estimate − transfer_cost = ev_net` invariant verified across all four strategies.
- ✅ **Handoff D₂** — Intel panel filled its rectangle (CSS flex column fix); Ingemann button repositioned; New Rider Value column added then dropped (commit `822f08d`); depth bonus reverse-map count fix in `fetch_riders.py` (snapshot stored `riders_in_top15: 0` because computation was buggy; patched writer + back-patched `stage_1_results.json`).
- ✅ **Handoff F₁** — Slider buckets renamed across `optimizer.py` / `server.py` / `claude.html`: `sprint`/`hilly`/`hardgc`/`mixed` → `bunch_sprint`/`reduced_sprint`/`gc`/`breakaway`. Module-level `SCENARIO_TO_TERRAIN` introduced; `build_forward_probabilities` rewritten to score riders via `terrain_affinity` × scenario weights (revives forward lookahead).
- ✅ **Handoff F₂a** — Race-type tickbox added to dashboard (`use_race_type_adjustment`, default OFF). When enabled with non-uniform n1 sliders, `build_probabilities` applies a `SCENARIO_TO_TERRAIN`-derived multiplier (`clamp(match/baseline, 0.6, 1.5)`) to `win`/`top3`/`top10`/`top15`, then renormalises each bucket to its pre-multiplier sum (preserves bookmaker overround). Recomputes `finish_probs`/`finish_ev` consistently.
- ✅ **Handoff F₂b** — Forward costs and transfer-adjusted EV surfaced on every candidate card. Confirmed response shape: `team.ev_estimate`, `team.transfer_cost`, `team.ev_net = ev_estimate − transfer_cost`, `team.forward.{cost_n1, cost_n2, transfers_n1, transfers_n2, total_forward_cost}`. Established that transfer-adj EV = `ev_net − cost_n1 − 0.7 × cost_n2`. **Surfaced concern**: at certain inputs Low-transfer beats Lookahead on transfer-adj EV — Lookahead's internal objective ignores `tc_current`. Carried forward to S16-4. Also surfaced: `simulate_stage` uses unseeded `np.random.default_rng()` (~0.5% drift between identical-input runs). Carried forward to S16-3.

### Session 16 (closed)

- ✅ **S16-1** — Depth bonus curve corrected to authoritative `0/4/8/15/35/65/120/220/400` (k for 0-8 riders in top-15). Used by both forward EV and reverse-map; curves match but duplicated across `optimizer.py` and `fetch_riders.py` (cleanup deferred to S17-8).
- ✅ **S16-2** — Ingemann scraper deprecated. Diagnosis: Feltet stopped publishing the girospillet column for Giro 2026. Stopping at diagnosis was correct (Feltet upstream issue, not scraper bug); fed clean S16-2c implementation.
- ✅ **S16-2c** — `/paste-expert-team` endpoint built. Image paste → Haiku 4.5 vision → 8 riders + captain → `stage_N_ingemann.json`. Source-agnostic by design (Holdet UI, tweets, Discord, leader rosters). Schema unchanged so downstream code didn't change. Lifted name matcher (`match_rider_name` in `server.py`) added during this work.
- ✅ **S16-3** — All RNG seeded. `compute_seed(stage, sliders, force_in, force_out, use_race_type_adjustment)` derives base seed; per-strategy XOR sub-seeds (`0x1..0x4` for strategies, `0xA/0xB` for forward chains, `0xF` for proxy). Identical inputs → bit-identical outputs.
- ✅ **S16-4** — Lookahead objective refactored. Now optimizes `ev_estimate − tc_current − cost_n1 − 0.7 × cost_n2` directly, matching the user-facing transfer-adjusted EV metric. Pre-fix: Low-transfer was beating Lookahead because Lookahead's internal objective ignored `tc_current`.

### Session 17 (in progress, May 10+)

#### S17-1 — GC standing, jersey holding, dynamic bonus modeling
The dominant Session 17 piece. Eliminates the optimizer's blind spot to GC standings and jersey holdings.

- ✅ **S17-1 Sub-A Phase 1 Diagnostic** — Closed. Finding: Feltet scraper does NOT touch standings (user's prior premise was incorrect). README's claim of GC in `stage_N_holdet.json` was aspirational. Reframed Sub-A from "wire up existing scraper" to "build standings ingestion path from scratch."
- ✅ **S17-1 Sub-B Phase 1 Diagnostic** — Closed. Finding: existing `gc_bonus`/`jersey_bonus` are heuristic over stage finish probability, not standings-aware. Two layers: pre-search EV annotation (`add_stage_evs` in `optimizer.py:181-234`) and Monte Carlo simulation (`simulate_stage` lines 1180-1191). Structural error surfaced: jersey bonus given to stage WINNER, not jersey HOLDER going into stage. Verdict: Sub-B requires standings-aware replacement, not extension.
- ✅ **S17-1 Sub-A Phase 2** — Closed. Delivered: `fetch_tv2_standings(stage)` in `scraper.py` + `POST /gather-standings` endpoint in `server.py`. Pulls four classifications (samlet/sprint/bjerg/ungdom) from TV2 per stage. `stage_2_standings.json` written. Verified: Silva at GC #1, holds rosa + bianca. Includes matcher upgrade (Rule X first-and-last word match + Rule Y word-level subset, lastname-only bug fix, `_NICKNAME_ALIASES` dict). All 5 original stop-condition unmatched names resolved (0/30 vs. original 5/30). Five remaining warnings beyond top-30 are deeper-scope (hyphen tokenisation, typo similarity, transliteration variants) — flagged in commit body, not addressed.
- ✅ **S17-1 Sub-B Design Diagnostic** — Closed. Architectural read of intel pipeline. Key findings:
  - **Single consumption site at `optimizer.py:284-293`** reading `key_signals` only via 6-cell `INTEL_MULT` table at `optimizer.py:71-79`. Per-rider lift bounded: max 1.20× up, min 0.75× down.
  - **Renormalisation property** (`optimizer.py:303-306`): intel can re-rank within field but cannot inflate total probability mass.
  - **`build_forward_probabilities` does NOT consume intel.** Forward stages (n+1, n+2) are slider-derived only. Material gap for cost_n1 / cost_n2 reasoning.
  - **Stage-level intel fields (`summary`, `stage_notes`, `weather`) are dead in optimizer** — rendered in dashboard, never reach `build_probabilities`.
  - **Expert weights are LLM prompt-string nudges** — f-string-substituted into Haiku prompt at `server.py:921-976`, not numerical multipliers. Per-rider numerical lever is the hardcoded `INTEL_MULT` table. Changing YAML weights from 1.5→2.0 wouldn't change any number in the optimizer; it would only change the prompt string.
  - **Dashboard expert weight slider plumbing** not yet verified — diagnostic traced YAML→prompt clearly but didn't trace whether the dashboard slider feeds the same path, a different numerical pathway, or is partially wired. Follow-up needed (Sub-B-plumbing).
  - **Inner Ring**: still scraped, included in Haiku prompt as "background context only, no weight," produces zero numerical contribution. ~5-10s scrape cost per gather-intel call for cosmetic prose-shaping. **NOT to be retired** — to be repaired and brought into per-source UI control as part of S18-7.
  - **Documented weights stale**: v5 onboarding states TV2 1.5 / Feltet 1.3 / Inner Ring 1.2; actual current YAML is TV2 1.5 / Feltet 1.0, Inner Ring removed (S11 Fix 3, Feltet 1.3→1.0 in commit `bb71b7e` between S13-14).
  - **Clean architectural slot** identified for stage-level `stage_signals.{gc_volatility, sprint_likelihood, breakaway_likelihood}` in Haiku output schema. Consumer hook in `build_probabilities` mirrors existing `key_signals` access pattern.
  - Carving outcome: Sub-B split into Sub-B1 (extend Haiku schema) + Sub-B2 (standings-aware bonus gated by `gc_volatility`) + Sub-B3 (deferred — relative time-gap GC simulation, conditional on Sub-B2 verification gap).
- ✅ **S17-1 Sub-A2** — Closed. Delivered: button renamed "Refresh riders" → "Refresh pre-stage data" (claude.html:493); handler rewritten as two sequential awaited calls (claude.html:2010-2080) — Holdet refresh blocking, /gather-standings non-blocking with warning surface that includes unmatched-name and scrape-error counts. Stage 1 edge skipped cleanly. Reload delay 1800ms → 2200ms when standings fire so warnings are readable. No server.py changes. Sub-B2 unblocked end-to-end; standings flow confirmed working in real dashboard use. Commits c4f0557 (Part 0 candidate sources insertion) + c9aa6cc (Part 1 wiring).

#### S17-2 — Slider/race-type tickbox bug

- ✅ **S17-2 Diagnostic** — Closed. Architectural read of slider/race-type tickbox bug. Primary root cause identified: `compute_seed` (added in S16-3) hashes the entire sliders dict + use_race_type_adjustment flag verbatim. Toggling n1 sliders OR flipping the tickbox changes the SA seed — and changing the seed changes which local optimum SA settles on — even when probabilities going into the optimizer are bit-identical. Race-type math itself (`optimizer.py:348-403`) is correctly tickbox-gated; when OFF, sliders genuinely have zero effect on probability dict. Diagonal pattern (OFF + bunch_sprint ≈ ON + breakaway) not fully explained by code reading; resolution test deferred to post-fix observation. Surfaced broader concern: 300k EV spread between seed-equivalent inputs implies single-seed SA is reporting one of many local optima with meaningfully different EV — addressed by S17-21 (multi-start), into which S17-2 Tier A fix is merged with disposition (cleanup-or-drop) decided post-Phase-1 data.

#### S17-21 — Multi-start SA optimization

- ✅ **S17-21 Phase 1** — Closed. Multi-start SA implemented at N=5: XOR'd sub-seeds (`strategy_xor << 8 | chain_xor`), shared `simulate_stage` evaluation seed for fair EV-best comparison, per-strategy not cross-strategy. Diagnostic logging at INFO level. All five verifications pass (bit-identical re-run, slider perturbation under OFF mostly Scenario A, 300k reproducer confirmed, diagonal resolved, Tier A merge decision Scenario A). Runtime ~58s. Acceptance rates 0.26–0.47. Convergence finding: optimal/depth/lookahead each had `convergence_count=1` — SA landscape genuinely rugged, multi-start doing real work, N=5 likely undersamples. Commits 1cb07e1 + 8e8e7a9.
- ✅ **S17-21 Phase 1.5** — Closed. N-curve diagnostic at N ∈ {5, 10, 20, 50} on Stage 3 neutral-slider canonical reproducer. Per-strategy patterns: optimal saturates at N=10 (Pattern A); depth saturates at N=5 on this input (Pattern A, possibly stage-specific); low-transfer degenerate (Pattern C, 2-3 unique teams across N=50); lookahead non-saturating with thin-basin global optimum found 1/50 (Pattern B, hyperparameter tuning candidate). Surprise finding: low-transfer shows three-basin behavior across n1 slider configs (sprint-heavy 1,168k / neutral 1,612k / gc-heavy 1,478k) — N=50 within any single config doesn't bridge basins; basin selection is seed-payload-driven. Makes Tier A genuinely diagnostic, not hygiene. Commit b9a3c09.

#### Sub-B carving evolution (decision history, for future reference)
Originally Sub-B (single ~2-3 day implementation). Mid-S17 evaluated B1/B2 split (jersey-only / GC re-ranking); **rejected** because the GC retention shortcut underlying the split proved invalid (breakaways routinely gap GC by 5+ minutes on "flat" stages). Merged back to single Sub-B. Architecture pivoted again when the user proposed reading GC volatility from intel rather than fitting rank-transition distributions — Sub-B Design Diagnostic added to characterize the intel pipeline. Final carving (post-diagnostic): Sub-B1 (input: extend Haiku schema with stage_signals) → Sub-B2 (consumer: standings-aware bonus blended via gc_volatility) → Sub-B3 (deferred refinement: relative time-gap simulation if Sub-B2 verification shows blend formula breaks materially on high-volatility stages). A briefly-proposed Sub-B0 (retire Inner Ring) was **withdrawn** when the user clarified Inner Ring's status: disabled under time pressure, not abandoned. Its repair is folded into S18-7.

---

## In flight

- 🟡 **S17-22-followup** *(Phase 1 closed; Phase 2A in flight)* — Quality fix for multi-start convergence at operational N. S17-22 V4 reported no convergence improvement at operational N=10, but the comparison was confounded (pre-Tier-A baseline vs post-Tier-A cooling=0.99999, single seed each); best-corroborated reporting works correctly but "ship marginal, rely on UX" was always a fallback — the user wants a quality fix. Cross-references: connects to S17-22 closed (V4 inconclusive due to confounded comparison + single seed at operational N).

  **Phase 1 closed (542544f).** 600 chains (3 configs × 4 strategies × 50) on Stage 2. Case classification: optimal/depth trivially convergent (1 basin/100% across all configs); low-transfer Case D under B_sprint (414k basin @ 64% vs 741k basin @ 20%, 327k EV-inversion); lookahead Case D, input-dependent (10/78%/175k-spread at A_saved, 23/26% at B_sprint with 109k EV-inversion, 2/78% at C_uniform). `ev_best_seen − ev_best_corroborated = 0` everywhere — best-corroborated logic correctly picks EV-best among count≥2 teams. **EV-inversion** (worse-EV basin found more often than better-EV basin) is the operational pathology, not basin count per se. Phase 1.5's prior "lookahead Pattern B" finding did not reproduce here — methodological lesson folded into CLAUDE_SESSION.md.

  Two operational facts surfaced during Phase 1, worth preserving here:
  - **Stage saved slider state is NOT persisted** to `stage_N_holdet.json` or any other on-disk file. The dashboard's `localStorage('holdet_sliders')` is the only source. Reproducers needing "the sliders the user actually saw" must read from localStorage or accept dashboard defaults (n1=70/20/5/5) as a stand-in.
  - **n1 has zero observable effect on optimizer output under `race_type_adjustment=False`** (the default). Post-S17-2 Tier A, n1 was dropped from `compute_seed`'s hash inputs, and `build_probabilities` skips the adjustment block. Variation in n1 alone produces bit-identical optimizer output. Reproducers testing "slider variation" must vary n2/n3 (or enable `race_type_adjustment`) to produce observable differences.

  **Phase 2A in flight** — Objective decomposition diagnostic. Localize the EV-inversion to either pre-search `ev_estimate` (vs `simulate_stage` mean) or to `compute_objective`'s forward-cost weighting. Read-only, ~15 min. Scope: lookahead at A_saved + B_sprint, low-transfer at B_sprint. Re-uses Phase 1's persisted chain results from `/tmp/basin_landscape_results.json` — no SA re-runs. Outputs feed Phase 2B (fix) handoff design.

---

## Future work

### Critical path (gates Sub-B work)

- ⏳ **S17-1 Sub-B-plumbing** — Verify dashboard expert weight slider plumbing. ~5-min read-only follow-up to Sub-B Design Diagnostic. Read `claude.html` slider handler + `server.py` `/gather-intel` to confirm whether the dashboard slider rides the YAML→prompt-string pathway, plumbs to a different numerical pathway, or is partially wired. Result feeds S18-1 design and S18-7 architecture.

### Session 17 — week 1 remainder (rest day May 11 → Stage 7, May 15)

- ✅ **S17-22** — Closed. Multi-start SA Phase 2 (data-driven design from Phase 1.5). Four coupled changes:
  - **Uniform N=10 across all 4 strategies.** Phase 1.5 justified N=10 as floor for optimal (Pattern A saturation point). Heterogeneous N considered and rejected — robustness across untested stage types (mountain stages may shift depth/optimal classifications), simpler implementation, ~10s runtime saving not worth complexity. Total runtime ~2 minutes (4 × 10 × ~3s); well under 5-min concern threshold.
  - **Lookahead hyperparameter sweep.** Lookahead is Pattern B (thin-basin global optimum found 1/50 chains); won't be solved by N alone. Sweep at fixed N=20 against Stage 3 reproducer: (a) longer cooling tail (cooling rate 0.99997 → 0.99999), (b) higher initial T (200k → 500k), (c) lower neighbor proposal bias (currently 70%/30% → try 50/50). Pick best-by-convergence. Single fix or combinations.
  - **Best-seen vs best-corroborated reporting.** When `convergence_count` for the chosen team is below 2/N, surface both numbers — "best-seen 1,644k (1/N), best-corroborated 1,634k (2/N)". UX decision (tooltip / dashboard secondary number / pre-stage warning) made during implementation. Important for Pattern B strategies; cosmetic for A/C.
  - **Commit Phase 1.5 diagnostic script.** Move `/tmp/n_curve_diagnostic.py` to `claude/diagnostics/n_curve_diagnostic.py` with canonical-reproducer documentation header (Stage 3 + neutral n1 sliders + tickbox OFF; snapshot dependencies; N values; seed-nesting property; "re-run when" notes). Justification: S17-22 lookahead sweep + S18-1 mid-Giro re-baselining + Tour-prep recalibration will all want like-with-like comparison.

  **Delivered.** Multi-Start Phase 2 closed. Uniform N=10 across all four strategies (replacing prior per-strategy N values). Lookahead hyperparameter sweep run at N=20 across baseline + three configs:

  | config              | ev_best   | conv | unique | runtime |
  |---------------------|----------:|-----:|-------:|--------:|
  | baseline            | 1,697,654 | 1/20 |  10/20 |    61s  |
  | a_cooling_0.99999   | 1,676,060 | 2/20 |  18/20 |    72s  |
  | b_initial_T_500k    | 1,661,650 | 1/20 |  10/20 |    68s  |
  | c_bias_0.5          | 1,649,771 | 1/20 |   7/20 |    72s  |

  `cooling_rate=0.99999` selected per decision criterion (highest convergence, tiebreak ev_best). Only config achieving convergence > 1 (2/20 vs baseline 1/20). 22k ev_best gap (1,676k vs 1,698k) trades raw EV for reproducibility: baseline's 1,698k is best-seen-but-uncorroborated (1/20 chains); cooling=0.99999's 1,676k is corroborated by 2 chains. Gap is small relative to the 300k+ spread the optimizer routinely produces — exactly the case best-corroborated reporting was designed to surface. Robust 1,676k > lucky 1,698k. Best-corroborated reporting added to optimizer output JSON (`convergence` field per strategy: `chosen_team_count`, `n_chains`, `best_seen_ev`, `best_corroborated_ev`, `best_corroborated_count`, `corroboration_status` ∈ {`corroborated`, `single_chain`, `no_corroboration`}) and dashboard rendering (`tc-convergence` CSS class, `convergenceHtml()` helper).
- ✅ **S17-23** — Closed-on-arrival. Conditional follow-up that would have triggered only if Tier A failed to resolve three-basin. V3 + V4 confirmed full resolution under Tier A; the deeper-mechanism hypothesis (current_team interaction or tc_current penalty creating slider-correlated initial conditions) was wrong — seed-state-leak was the entire mechanism, just upstream of where the hypothesis pointed. Closed without work.
- ✅ **S17-20** (2026-05-11) — Per-bucket clear odds buttons. Three buttons (one per bucket: win / top3 / top10) in the odds panel. Clicking clears only the named bucket for the current target stage, both in-memory and persisted to `stage_N_odds.json`. Mirrors the bucket-isolation property of `/parse-odds-image` (Session 6 fix).
- ✅ **S17-24** (2026-05-11) — All-zero odds handling. S17-20 introduced the ability to write zeros to `stage_N_odds.json` via the ✕ buttons; prior code paths (`/parse-odds-image` filters `pct >= 1.0`) never produced that state. With all-zero odds, `build_probabilities` correctly falls back to uniform probabilities — but uniform = no SA gradient → all chains run to `max_seconds` cap → ~200s total runtime → client `AbortController` (120s) gives up before server returns. Fix: backend short-circuit in `/run-optimizer` returning 400 with clear message when odds are present-but-all-zero; frontend pre-flight in `runPyOptimizer` mirroring the check for immediate feedback. Defense-in-depth. Root cause: SA has no gradient under uniform probabilities; the symptom (fetch abort) was the client timing out on an optimizer correctly doing nothing useful under degenerate input.
- ✅ **S17-27** (2026-05-11) — `/refresh` and `/snapshot` (no-param legacy path) rider-list source fix. Both endpoints used `sorted([…snapshots…])[-1]` to find "the latest snapshot," which silently worked while `stage_2_holdet.json` was alphabetically last but broke when `stage_3_holdet.json` was created by a per-stage team-save path (carrying `team_composition` + `bank` + `captain` + `stage` only, no `riders` field). User-facing symptom: "Refresh pre-stage data" reported 0 riders, rider table emptied, optimizer became unrunnable. Fix: both endpoints now read `stage_1_holdet.json` directly (canonical rider master list per `fetch_riders.py`'s hardcoded `SNAPSHOT_FILE`). Wider audit pass surfaced a third site (`/riders`) using the same pattern; fixed in the same commit. Same architectural class as S17-24 — a latent assumption violated when a new input path landed. Future coupling note: when S17-3 (two-team support) generalizes `fetch_riders.py` to per-team master lists, all three endpoints will need matching generalization.
- ⏳ **S17-1 Sub-B1** — *(Sub-B1 and Sub-B2 verification depends on S17-21 landing first; otherwise "Silva at ~140k" testing is confounded by seed-driven local optima.)* Extend Haiku prompt + JSON schema with `stage_signals.{gc_volatility, sprint_likelihood, breakaway_likelihood}` ∈ [0.0, 1.0]. Calibration note in prompt: 0.0 = explicit "peloton control / no GC moves / sprint-controlled"; 1.0 = explicit "GC moves expected / decisive day / splits in the favourites group"; default 0.5 when sources don't speak to it. Verify field appears in re-scraped `stage_N_intel.json`. No optimizer change yet — Sub-B1 only delivers the input data.
- ⏳ **S17-1 Sub-B2** — Standings-aware GC/jersey bonus, gated by `gc_volatility`, consuming Sub-A's `stage_{N-1}_standings.json`. Replaces heuristic in both `add_stage_evs` (pre-search EV annotation) and `simulate_stage` (Monte Carlo). Blend formula: `P(post_stage_top_10) = (1-gc_volatility) × (current_rank ∈ top_10) + gc_volatility × P(stage_finish_top_10)`. Same shape for jersey retention. **Verification (option 2 — measurable gap)**: (a) retroactive Stage 3 should surface Silva at ~140k combined (rosa retention 25k + bianca retention 15k + GC #1 bonus ~100k); (b) at least one high-volatility historical stage (mountain stage with GC reshuffle, e.g. selected from prior Grand Tour) where blend formula is expected to break — measure how badly; documented gap feeds Sub-B3 trigger decision. Requires Sub-A2 to be landed for end-to-end test.
- ⏳ **S17-1 Sub-B3** *(deferred, conditional)* — Relative time-gap GC simulation. Triggers if Sub-B2 high-volatility verification shows blend formula breaks materially. Replaces stage-finish-position proxy with proper relative time-gap reasoning across current GC top-10 (a 40th-place finish that loses 30s with all rivals also losing 30s should preserve GC rank). Architecturally larger; possibly T-series rather than S17. If Sub-B2 verification shows blend is adequate, B3 stays in roadmap as a known refinement but isn't actively scheduled.
- ✅ **S17-2** — Closed. Tier A patch landed. All four verifications passed: V1 bit-identical re-run, V2 tickbox toggle still affects output, V3 three-basin resolution (all 4 strategies identical across sprint/neutral/gc-heavy n1 configs under OFF), V4 Phase 1 V2 reproducer collapses (1.17M vs 1.48M now both 1,372,018). Tier A was diagnostic-grade not hygiene — fully resolved low-transfer's three-basin pathology that even N=50 multi-start within a single config couldn't bridge. Confirmed: seed-state-leak was 100% of the mechanism. Commit 79449b8.
- ⏳ **S17-1 Sub-C** — Jersey acquisition probability for non-holders. Less critical than retention; matters in mountain weeks. Builds on Sub-B2's standings-aware infrastructure.
- ⏳ **S17-1 Sub-D** — Verification across multiple stages. Replay Stages 1-3 with full Sub-A + B1 + B2 (+ B3 if triggered) + C model + actual standings. Confirm Silva would have surfaced. Calibrate `gc_volatility`-blend behaviour against actual stage outcomes. ~1-2 days.
- 🟡 **S17-25** *(Phase 1 in flight)* — `finish` field empty in `stage_N_results.json` for all riders, Stages 2 + 3 (and likely earlier). Diagnostic surfaced during S17-24 investigation. Per Session 11 Fix 5, `fetch_stage_results` was supposed to populate stage results from the players API cross-referenced with the team snapshot. Currently `finish: "—"` for every rider on disk. Affects: A/B decision log (S17-5), retroactive post-mortems (S17-17), Tour backtesting (T-6) — anything wanting rider-by-rider finish-position attribution. Not blocking; cosmetic for in-race use. Read-only diagnostic first to understand whether `/fetch-stage-results` writes the field, ever wrote it, or the field name mismatches the renderer.
  - **2026-05-12 — Phase 1 in flight.** Session 15 D₂ established empirically that the round-history endpoint currently called by `fetch_stage_results` exposes only `priceChange` and `captainBonus` per rider; D₂ resolved team-level depth count via reverse-mapping but per-rider sprint/jersey/GC/team attribution has never been populated. User confirmed Holdet's UI exposes the full breakdown via the rider detail view (Pointtrøjen, Sprintpoint, Etapeplacering, Holdbonus per stage). Phase 1 finds the API endpoint that serves the detail panel — a different endpoint than the one currently wired. Phase 2 (separate handoff) wires the new endpoint into `fetch_stage_results`, extends `stage_N_results.json` schema, and verifies the renderer surfaces the new fields. Phase 1 read-only diagnostic, no code changes.
  - **2026-05-11 update:** User re-reported the breakdown showing totals only after S17-27 landed; bundled into S17-28's diagnostic round-trip (option A per user direction) to characterize whether disk state has changed since prior diagnostic, whether the writer or renderer is the failure source, and how it relates to Stage 2's current state.
  - **2026-05-11 update post-diagnostic:** Classified as Case C — both Stage 2 and Stage 3 have always shown only `stage_pts + captain_bonus + total`. Writer (`fetch_stage_results` in `fetch_riders.py:558-572`) hardcodes `finish: "—"`, `sprint_pts: 0`, `jersey_bonus: 0`, `gc_bonus: 0`, `team_bonus: 0` because the Holdet round-history API exposes only `priceChange` and `captainBonus` per rider. Not a regression. Three architectural options surfaced (TV2/Feltet finish-position scrape; alternative Holdet API endpoint; manual entry). Defer past Giro per project framing — calibration data, not model-execution. Re-queues.
- ✅ **S17-28** (2026-05-11) — Fetch-abort regression diagnostic. Closed (diagnostic complete; fix tracked as S17-29). Empirical findings: Stage 4 server-side runtime measured 132.79s (HTTP 200, valid JSON), exceeding dashboard's hardcoded 120s `AbortController` ([claude.html:1824](claude/dashboard/claude.html:1824)). S17-24's pre-flight correctly identified that win signal is present (20/42 rows non-zero on Stage 4); the abort is downstream of the pre-flight. Root cause two-layered: (a) wall-clock-exceeds-timeout, but (b) the wall-clock itself is inflated because `optimizer.py:306-309` treats cleared top10 (40/42 rows = 0) as zero probability instead of falling through to win-derived fallback, killing SA gradient on positions 4-15. User clarified the project invariant: odds are never zero by intent; zero ≡ missing. Audit confirmed `optimizer.py:306-309` is the only violation. Fix architecture: enforce invariant at the single violation site; declare it in CLAUDE_SESSION.md to prevent reintroduction. `AbortController` timeout question separately queued as S17-30 (defense-in-depth after re-measurement). 4th instance of "latent invariant exposed by new input path" pattern this session.
- ✅ **S17-29** (2026-05-11) — Odds invariant enforced. Project rule: odds are never zero by intent; zero ≡ missing. `optimizer.py:306-309` was the only violation, treating cleared top3/top10 as `0.0` probability instead of falling through to win-derived fallback. Fixed: changed `if o.get('top3_pct') is not None` and `if o.get('top10_pct') is not None` to `if (o.get('top3_pct') or 0) > 0` and `if (o.get('top10_pct') or 0) > 0`. Effect: missing top10 (Stage 4's regime, 40/42 rows = 0) now correctly inherits win-derived position-4-to-15 distribution. Expected to restore SA gradient on those positions and reduce runtime. Invariant documented in CLAUDE_SESSION.md.
- ✅ **S17-30** (2026-05-11) — Dashboard `AbortController` timeout robustness. Closed. Dashboard `AbortController` bumped from 120,000 ms to 240,000 ms in [claude.html:1824](claude/dashboard/claude.html:1824). Recognizes structural reality surfaced by S17-29 verification: SA runtime is dominated by per-chain `max_seconds=5` cap × 4 strategies × 10 chains ≈ 120s floor regardless of input. Any input that pushes a chain to its cap pushes total over the prior timeout. 240s gives ~2× margin against the structural floor; lookahead Pattern B (S17-22) chains hitting caps no longer surface as fetch aborts. Elapsed-time display on Run button ([claude.html:1815](claude/dashboard/claude.html:1815), pre-existing) addresses the "user clicked, nothing happening" UX concern.
- ✅ **S17-31** (2026-05-12) — Probability model extrapolation: missing top10 derived from top3, not win-imputed. S17-29 enforced "zero ≡ missing" at input guards but downstream `.get(name, default)` still imputed missing top10 from win (`pw * 8.0`), violating the invariant's second half. S17-31 replaces win-imputation with a fallback chain: top10 extrapolated from top3 when top3 is known (dominant case — `top10 ≈ top3 * C10_top3`); win-derived fallback only when top3 is also missing (rare edge). Calibration constants `C10_TOP3`, `C3_WIN`, `C10_WIN` hardcoded with sensible defaults; recalibration from empirical stage data tracked as a follow-up. Effect: riders with cleared top10 now get an honest extrapolated top10 contribution from top3 rather than a fabricated win-derived one. Captain choice unaffected on sprint stages (top stars have full odds); supporting rider rankings shift to reflect signal honesty.
- ⏳ **S17-32** — Calibrate `C10_TOP3`, `C3_WIN`, `C10_WIN` constants from empirical stage data. S17-31 ships with hardcoded defaults. Recalibrate by measuring observed ratios across stages where full odds are present (Stage 1, Stage 2; future stages as they accumulate). Document the calibration method and last-recalibrated date in `optimizer.py` near the constants. Defer until ≥4 stages of complete odds data accumulate; before then, hardcoded defaults are sufficient.
- ⏳ **S17-6** — Time trial bucket (5th `SCENARIO_TO_TERRAIN` category). **Hard deadline ~May 17** before Stage 8 prep when Stage 10 enters n+2 window. Cannot go to Tour without this.
- ⏳ **S17-3** — Two-team support. Team selector toggle in dashboard header. Snapshot files namespaced per team. Shared race-level data unified.
- 💭 **S17-12** — Ingemann observation window. Check if Stage 4 Feltet article appears post-rest-day. If not, manual paste is permanent. Observation only.

### Session 17 — week 2 (Stage 8 → Stage 14, ~May 17-23)

- ⏳ **S17-4** — Top-N teams scraper. Probe Holdet API for non-own team rosters (Freddy G's exposure confirms feasibility). Scrape top-50 per round into `shared/data/snapshots/top_teams/round_N.json`. Phase 3 (analysis) is post-Giro. Tour-prep unlock.
- ⏳ **S17-5** — A/B decision log. Captures roster delta, captain delta, slider settings, optimizer recommendation, human override + reasoning, post-stage outcome, would-have-scored deltas. Backfill Stages 1-3 from session notes.
- ⏳ **S17-15** — Axelgaard preview scraping for forward stages, Phase 1. Extend TV2 scraper for stage n+1, n+2. Store star ratings + stage classification ("Flad etape" / "Bjergetape") as forward intel signal. No optimizer changes yet.
- 💭 **S17-11** — Retire Low-transfer card decision. Updated criterion: empirical comparison of Lookahead and Low-transfer outputs across Stages 1-7 (backfill + live). If Lookahead recommends same team as Low-transfer in 80%+ of stages with EV gap defensibly explained, retire Low-transfer mid-Giro and reclaim ~30s/run (one strategy of the four at N=10). If outputs diverge meaningfully, keep both. Phase 1.5 N-curve showed Low-transfer is Pattern C (degenerate, 2-3 unique teams across N=50 vs Lookahead's varied N=50 spread); solving overlapping but not identical problems on Stage 3 (Lookahead 1,634k corroborated vs Low-transfer 1,612k). If retired, S18-3 (most-picked panel from Holdet API) becomes the natural fourth card.

### Session 17 — stretch into Session 18

- ⏳ **S17-7** — Dashboard depth-bonus footnote stale. Cosmetic or substantive — find out during S17-2 work.
- ⏳ **S17-8** — `DEPTH_BONUS` extraction to shared constants module. Both `optimizer.py` and `fetch_riders.py` import from one source (and possibly JS depending on S17-7).
- ⏳ **S17-9** — Race-type adjustment double-counting heuristic. Post-S17-2, address the deeper design issue: bookmaker odds already encode stage type, so multiplying Milan's win prob by 1.5× double-counts. Tooltip + dampener.
- ⏳ **S17-10** — Wall-clock determinism. Replace `time.time()` early termination at `optimizer.py:627, 773` with iteration count.
- ⏳ **S17-13** — Captain selection variance modeling. Add variance term or "captain confidence" parameter informed by S17-4 data.
- ⏳ **S17-14** — Transfer-rate calibration vs. top-N. Compare optimizer's recommended transfer counts vs. actual top-10 transfer counts. Calibration analysis, not code.
- ⏳ **S17-16** — Axelgaard preview integration, Phase 2. Use stage classification for forward slider auto-fill or hint. Use star ratings as forward EV priors in `build_forward_probabilities()`.
- ⏳ **S17-17** — Stage 2 retroactive A/B post-mortem. Re-run optimizer on Stage 2 with corrected curve + seeded RNG; compare to actual Project Win The Giro picks. Calibrates how much was optimizer wisdom vs. human bias.
- ⏳ **S17-18** *(new from S17 audit)* — Forward-probabilities intel consumption. `build_forward_probabilities` currently doesn't consume intel at all; n+1 and n+2 EV is purely slider-derived. Fold the same `key_signals`-multiplier logic (or its successor after Sub-B1) into forward EV calculation. Affects cost_n1 and cost_n2 reasoning across all four strategy cards.
- ⏳ **S17-19** *(new from S17 audit)* — Stage-level intel fields (`summary`, `stage_notes`, `weather`) are dead in optimizer — rendered in dashboard, never reach `build_probabilities`. Either (a) wire them into prompt context for the per-rider intel synthesis, (b) extract structured signals from them (Sub-B1 partially does this for `gc_volatility` etc.), or (c) explicitly mark display-only and stop scraping `weather` if unused. Decide direction first.

### Session 18 — calibration and refinement (mid-Giro, post-Stage 9-10)

- ⏳ **S18-1** — Mid-Giro re-baselining. Two distinct levers:
  - **Numerical**: `INTEL_MULT` table (6 cells at `optimizer.py:71-79`) — pre-Giro guesses, never validated. Calibrate against actual Stage 1-9 outcomes: do `up/strong` riders actually outperform their bookmaker baseline by ~20%?
  - **Prompt-tuning**: expert weights in `expert_sources.yaml` and dashboard sliders. These are LLM prompt-string nudges (per S17 Sub-B Design Diagnostic), not numerical multipliers. Tuning them is prompt engineering — adjust only with awareness that effects are opaque.
  - Also: depth-bonus distribution sanity check — how often do real teams hit 5/6/7/8 in top-15?
- ⏳ **S18-2** — Bank live in header (real-time Holdet API). Replaces D₁ removal from Session 15.
- ⏳ **S18-3** — Most-picked panel from Holdet API. Crowd consensus signal. Different from S17-4 (top-N expert teams). Useful as fourth card if S17-11 retires Low-transfer.
- ⏳ **S18-4** — Snapshot rename `stage_N_ingemann.json` → `stage_N_expert_team.json`. Cosmetic.
- ⏳ **S18-5** — Dead-code cleanup pass. Remove `/current-team`, `/save-current-team`, `.stat-pill`, `.mock-badge`, scraper Ingemann functions (gated on S17-12 confirming Feltet silence through Stage 6).
- 💭 **S18-6** — Crash-correlated risk modeling. Decision item, possibly no code. Document Stage 2 lesson (UAE-adjacent crash took out Strong/Morgado/Narvaez correlated). Make decision deliberate.
- ⏳ **S18-7** *(reworked from earlier draft)* — Multi-source intel framework with per-source UI control. Goals: (i) repair Inner Ring scraping (currently disabled due to stale-data failure showing 2024 Giro riders; root cause unknown — wrong page, outdated selectors, Inner Ring hadn't published 2026 content at scrape time, or upstream search returning archived content); (ii) add Cycling News as a configured source; (iii) extensible source registry for adding further sources without scraper rewrites.
  - **Phase 1 — Inner Ring repair diagnostic**: investigate why Inner Ring scraping returned 2024 Giro content. Identify whether it's a fixable selector/URL issue, a freshness check problem, or upstream content unavailability. ~half-day diagnostic.
  - **Phase 2 — Source registry + quality gate**: configured candidate source registry (TV2, Feltet, Inner Ring, Cycling News, etc.) with per-source scrape config (URL pattern, content selector). Quality gate at scrape-time: rider-name match against current `riders.json`; <30% match flags as stale. Returns warning, not error. ~1 day.
  - **Phase 3 — Dashboard UI + per-source controls**: per-source row in dashboard with (a) tickbox to include in this run (default ticked), (b) weight slider, (c) freshness indicator (✅ / ⚠️ stale / ❌ failed). Tickbox state persists in localStorage. Pipeline change: `scrape_all_intel(stage, included_sources)` returns only ticked sources passing freshness. Haiku prompt reflects which sources were used. ~1 day.
  - **Phase 4 — Architectural caveat documentation**: tooltip or note explaining that source weights are LLM prompt-string nudges, not numerical multipliers (per S17 Sub-B Design Diagnostic). The numerical lever is `INTEL_MULT` (S18-1 calibration target). Slider effects are opaque; tickbox effects are observable. ~30 min.
  - **Preliminary candidate sources** (surveyed in S17, to be evaluated in Phase 1):
    - Already in pipeline: TV2/Axelgaard (Danish, login), Feltet.dk (Danish, login)
    - To repair: Inner Ring (`inrng.com`) — English, free, scraping disabled S11 due to stale 2024 Giro content
    - User-flagged English candidates: `cyclinguptodate.com`, `idlprocycling.com`, `cyclingstage.com` — all free, confirmed publishing 2026 Giro stage previews with per-stage URL structure
    - Search-discovered English candidates: `cyclingnews.com` (major commercial site, dedicated per-stage preview URLs); `escapecollective.com` (high editorial quality, partial paywall — some content unlocked); `domestiquecycling.com` (free, structured stage-by-stage guide)
    - Out of initial intel scope: `procyclingstats.com` (primarily data/results, not preview commentary — useful as separate data source for S18-3 most-picked or T-2 stage profiles); Italian-language sites (`tuttobiciweb.it`, `cicloweb.it` — language barrier for current Haiku prompt structure, would need prompt rework before adding)
    - Phase 1 evaluation criteria per candidate: (a) freshness — does the source publish a 2026 Giro stage preview within ~24h of stage start? (b) structure — is content reliably scrapeable at predictable per-stage URL? (c) signal — does prose contain actionable rider-level commentary, not just stage-profile summary?
  - Total: ~2.5-3 days.
  - **Architectural property to preserve**: per-rider lift bounded by `INTEL_MULT` cells regardless of source count. Adding sources broadens coverage (more riders tagged) but each rider's individual lift cap stays the same. Watch for Haiku's `strength` assignment scaling with agreement (3/4 sources agreeing → `strong`; 1/4 → `moderate`); this is arguably desirable (agreement → confidence) but is the one place number-of-sources can affect lift via prompt synthesis.

### Pre-Tour (T-series, June 1 → early July, ~7 weeks)

- ⏳ **T-1** — Post-Giro analysis. Mine S17-4 top-N data + S17-5 A/B log: optimizer blind spots (where top-50 agreed but optimizer disagreed), contested-judgement areas (where top-50 disagreed among themselves), captain choice patterns by stage type, transfer-rate patterns.
- ⏳ **T-2** — Tour stage profile data ingestion. Standardize per-stage metadata (ProfileScore, finish gradient, etc.) so optimizer reasons from structured data, not user-set sliders alone.
- ⏳ **T-3** — TT modeling polish. Validate S17-6 on Giro Stage 10. Refine TT-rider `terrain_affinity` values. Improve TT win-probability calibration.
- ⏳ **T-4** — Team TT specifically. If Tour 2026 has team TT, scoring is fundamentally different (whole team scores together). Probably needs separate path in `simulate_stage`. Confirm Tour route first.
- ⏳ **T-5** — Tour GC dynamics. S17-1 retention probabilities need Tour-specific calibration. Maillot jaune changes more often than Giro pink in Week 1.
- ⏳ **T-6** — Backtest corrected optimizer against full Giro 2026. Replay every stage with full S17-1 model + actual standings + corrected curves + seeded RNG. Compare to (a) human team picks, (b) Freddy G picks, (c) optimal-in-hindsight team. Gap to optimal-in-hindsight = residual error budget.
- ⏳ **T-7** — Tour-prep dashboard polish. Top-N consensus panel, jerseys + GC panel, Axelgaard forward previews, four-strategy cards, A/B log accessible.

---

## Out of scope

- Live race tracking during stages (we're a pre-stage optimizer)
- Multi-race system beyond Giro + Tour (Vuelta etc.)
- Mobile app (localhost:5050 dashboard sufficient)
- Architectural cleanup for its own sake (refactor, modularize, type hints) — defer indefinitely

---

## Footnotes

[^s1]: No dedicated session log file at `claude/sessions/`. Reconstructed from git commits `2527374` (initial repo) and `afa1fe7` (roadmap + standing instructions).

[^s3]: File at `claude/sessions/2026-05-06_4.md` carries the title "Session 3" — naming is by chronological position, not filename suffix. The same file pattern repeats elsewhere (e.g. `2026-05-06_3.md` is Session 2c).

[^s5]: Two log files cover Session 5: `2026-05-08_5.md` (scraper + optimizer + Ingemann endpoints) and `2026-05-08_session5.md` (server rewrite, vision endpoint, intel structuring). Git history records 11 numbered "session 5 part X" commits across two days; the work was multi-part rather than two distinct sessions.

[^s8]: No dedicated session log file. Reconstructed from a cluster of "fix:" commits between Session 7 and Session 9 (`fix: server-msg visibility…`, `fix: catch SystemExit in /refresh…`, `fix: null-safe rider-count…`, `fix: restore working rider loading…`, `fix: null-guard h-stage-title…`). Appears to have been a stabilisation pass without a dedicated retrospective.

[^s10]: No dedicated session log file. Single commit `4393ccb session 10: stage 2 readiness — expert weights, optimizer, intel verified` on 2026-05-08. Stated as a verification pass before Stage 2; no functional changes captured beyond what the commit message implies.

[^s12]: No dedicated session log file. Single commit `75698a0 Session 12: ingemann body logging, rider name matching, placeholder card`.

[^s13]: Sessions 13 and 14 have no dedicated log files. Inferred from intermediate commits between Session 12 and Session 15: `db5e3e5` (transfer cost added to optimizer output), `6ddbf16` (API optimizer button removed; endpoint renamed), `1643e92` (button-ref fix), and the pre-Session-15 snapshot commit `bb71b7e` which records the Feltet weight change from 1.3 → 1.0. Whether these represent two distinct sessions or one bundled push is not recoverable from the logs.
