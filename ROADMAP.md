# Holdet v3 — Roadmap

Living document. Replaces the prior roadmap section in the v5 onboarding doc. Tracks completed work across sessions and future planned work.

**Project**: Holdet v3 (repo at `~/Claude/Holdet-v3/`)
**Race target**: Tour de France 2026 (early July). Giro d'Italia 2026 is calibration.
**Last updated**: May 10, 2026 (Session 17 close pending; Sub-B Design Diagnostic landed).

---

## Update protocol

- The first handoff of every new session is a ROADMAP.md update folding deltas from the prior session (closed items, new items, scope changes, corrections). Standing rule.
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

#### Sub-B carving evolution (decision history, for future reference)
Originally Sub-B (single ~2-3 day implementation). Mid-S17 evaluated B1/B2 split (jersey-only / GC re-ranking); **rejected** because the GC retention shortcut underlying the split proved invalid (breakaways routinely gap GC by 5+ minutes on "flat" stages). Merged back to single Sub-B. Architecture pivoted again when the user proposed reading GC volatility from intel rather than fitting rank-transition distributions — Sub-B Design Diagnostic added to characterize the intel pipeline. Final carving (post-diagnostic): Sub-B1 (input: extend Haiku schema with stage_signals) → Sub-B2 (consumer: standings-aware bonus blended via gc_volatility) → Sub-B3 (deferred refinement: relative time-gap simulation if Sub-B2 verification shows blend formula breaks materially on high-volatility stages). A briefly-proposed Sub-B0 (retire Inner Ring) was **withdrawn** when the user clarified Inner Ring's status: disabled under time pressure, not abandoned. Its repair is folded into S18-7.

---

## In flight

(none — Session 17 close pending; awaiting Stage 3 results and any additional handoffs)

---

## Future work

### Critical path (gates Sub-B work)

- ⏳ **S17-1 Sub-A2** — Dashboard wiring. Extend "Refresh riders" button to also call `/gather-standings` for stage `N-1`. Failure semantics: Holdet failure blocking, TV2 failure non-blocking warning. Stage 1 edge: skip standings call cleanly (no previous stage exists). Rename button (proposed: "Refresh pre-stage data" or similar). ~30 min. **Gate-critical**: without this, standings ingested by Sub-A never reach the optimizer in normal pre-stage workflow. Must land before Sub-B2 can be tested end-to-end.
- ⏳ **S17-1 Sub-B-plumbing** — Verify dashboard expert weight slider plumbing. ~5-min read-only follow-up to Sub-B Design Diagnostic. Read `claude.html` slider handler + `server.py` `/gather-intel` to confirm whether the dashboard slider rides the YAML→prompt-string pathway, plumbs to a different numerical pathway, or is partially wired. Result feeds S18-1 design and S18-7 architecture.

### Session 17 — week 1 remainder (rest day May 11 → Stage 7, May 15)

- ⏳ **S17-1 Sub-B1** — Extend Haiku prompt + JSON schema with `stage_signals.{gc_volatility, sprint_likelihood, breakaway_likelihood}` ∈ [0.0, 1.0]. Calibration note in prompt: 0.0 = explicit "peloton control / no GC moves / sprint-controlled"; 1.0 = explicit "GC moves expected / decisive day / splits in the favourites group"; default 0.5 when sources don't speak to it. Verify field appears in re-scraped `stage_N_intel.json`. No optimizer change yet — Sub-B1 only delivers the input data.
- ⏳ **S17-1 Sub-B2** — Standings-aware GC/jersey bonus, gated by `gc_volatility`, consuming Sub-A's `stage_{N-1}_standings.json`. Replaces heuristic in both `add_stage_evs` (pre-search EV annotation) and `simulate_stage` (Monte Carlo). Blend formula: `P(post_stage_top_10) = (1-gc_volatility) × (current_rank ∈ top_10) + gc_volatility × P(stage_finish_top_10)`. Same shape for jersey retention. **Verification (option 2 — measurable gap)**: (a) retroactive Stage 3 should surface Silva at ~140k combined (rosa retention 25k + bianca retention 15k + GC #1 bonus ~100k); (b) at least one high-volatility historical stage (mountain stage with GC reshuffle, e.g. selected from prior Grand Tour) where blend formula is expected to break — measure how badly; documented gap feeds Sub-B3 trigger decision. Requires Sub-A2 to be landed for end-to-end test.
- ⏳ **S17-1 Sub-B3** *(deferred, conditional)* — Relative time-gap GC simulation. Triggers if Sub-B2 high-volatility verification shows blend formula breaks materially. Replaces stage-finish-position proxy with proper relative time-gap reasoning across current GC top-10 (a 40th-place finish that loses 30s with all rivals also losing 30s should preserve GC rank). Architecturally larger; possibly T-series rather than S17. If Sub-B2 verification shows blend is adequate, B3 stays in roadmap as a known refinement but isn't actively scheduled.
- ⏳ **S17-2** — Slider/race-type tickbox bug. Diagnose first. EV variance 1450k-1785k for same stage; recommendations partially trustworthy until fixed. Should land before Stage 4 prep (May 12) for confident EV reads.
- ⏳ **S17-1 Sub-C** — Jersey acquisition probability for non-holders. Less critical than retention; matters in mountain weeks. Builds on Sub-B2's standings-aware infrastructure.
- ⏳ **S17-1 Sub-D** — Verification across multiple stages. Replay Stages 1-3 with full Sub-A + B1 + B2 (+ B3 if triggered) + C model + actual standings. Confirm Silva would have surfaced. Calibrate `gc_volatility`-blend behaviour against actual stage outcomes. ~1-2 days.
- ⏳ **S17-6** — Time trial bucket (5th `SCENARIO_TO_TERRAIN` category). **Hard deadline ~May 17** before Stage 8 prep when Stage 10 enters n+2 window. Cannot go to Tour without this.
- ⏳ **S17-3** — Two-team support. Team selector toggle in dashboard header. Snapshot files namespaced per team. Shared race-level data unified.
- 💭 **S17-12** — Ingemann observation window. Check if Stage 4 Feltet article appears post-rest-day. If not, manual paste is permanent. Observation only.

### Session 17 — week 2 (Stage 8 → Stage 14, ~May 17-23)

- ⏳ **S17-4** — Top-N teams scraper. Probe Holdet API for non-own team rosters (Freddy G's exposure confirms feasibility). Scrape top-50 per round into `shared/data/snapshots/top_teams/round_N.json`. Phase 3 (analysis) is post-Giro. Tour-prep unlock.
- ⏳ **S17-5** — A/B decision log. Captures roster delta, captain delta, slider settings, optimizer recommendation, human override + reasoning, post-stage outcome, would-have-scored deltas. Backfill Stages 1-3 from session notes.
- ⏳ **S17-15** — Axelgaard preview scraping for forward stages, Phase 1. Extend TV2 scraper for stage n+1, n+2. Store star ratings + stage classification ("Flad etape" / "Bjergetape") as forward intel signal. No optimizer changes yet.

### Session 17 — stretch into Session 18

- ⏳ **S17-7** — Dashboard depth-bonus footnote stale. Cosmetic or substantive — find out during S17-2 work.
- ⏳ **S17-8** — `DEPTH_BONUS` extraction to shared constants module. Both `optimizer.py` and `fetch_riders.py` import from one source (and possibly JS depending on S17-7).
- ⏳ **S17-9** — Race-type adjustment double-counting heuristic. Post-S17-2, address the deeper design issue: bookmaker odds already encode stage type, so multiplying Milan's win prob by 1.5× double-counts. Tooltip + dampener.
- ⏳ **S17-10** — Wall-clock determinism. Replace `time.time()` early termination at `optimizer.py:627, 773` with iteration count.
- 💭 **S17-11** — Retire Low-transfer card decision. Pending S17-4 data. Likely keep — Freddy G's conservative trading suggests yes.
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
