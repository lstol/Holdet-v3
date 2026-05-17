"""
EV-function asymmetry verification (2026-05-17).

Follow-up to per-rider EV diagnostic (commit 5a6434f). Verifies at code
level + numerically that `compute_team_ev` (SA objective) and
`simulate_stage` (reported Net EV) are genuinely different EV
formulations and rank rosters oppositely on Stage 9 substrate.

Three sections:
  A. Source-citation of both functions' methods + call sites + hypothesis
     assessment at code level.
  B. Numerical comparison of 6 candidate rosters under both functions:
       1. Optimal best-corroborated (Gall captain)
       2. Lookahead best-corroborated (Vingegaard captain)
       3. Depth dominant (Gall captain)
       4. Synthetic — Optimal roster with Vingegaard swapped in
       5. Synthetic — Lookahead roster with Gall swapped in
       6. Current team (no transfers) baseline
  C. Synthetic stress-test: stylized Roster A (one big-favorite + 7
     medium) vs Roster B (8 medium with no big favorite).

Outputs:
  /tmp/s17_intel_ev_function_audit.json  (machine-readable)
  Committed snapshot at claude/diagnostics/s17_intel_stage_9_output/
    s17_intel_ev_function_audit.log + .json after the run.

Usage:
  python3 claude/diagnostics/s17_intel_ev_function_audit.py [--stage 9]
"""
from __future__ import annotations
import argparse
import copy
import inspect
import json
import os
import sys

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3'
sys.path.insert(0, os.path.join(REPO, 'claude', 'engine'))

from optimizer import (
    INTEL_MULT,
    FINISH_POINTS,
    build_probabilities,
    build_forward_probabilities,
    compute_seed,
    compute_team_ev,
    compute_team_bonus_ev,
    compute_transfer_cost,
    get_stage_config,
    load_stage_scoring,
    select_captain,
    simulate_stage,
    DEPTH_BONUS,
)

SNAPSHOT_DIR = os.path.join(REPO, 'shared', 'data', 'snapshots')
RIDERS_FILE = os.path.join(REPO, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')
BASIN_FILE = os.path.join(REPO, 'claude', 'diagnostics', 's17_intel_stage_9_output',
                          's17_intel_stage_9_strategy_basins.json')


def _load_riders():
    data = json.load(open(RIDERS_FILE))
    return [r for r in data['riders'] if not r.get('isOut') and r.get('status') != 'dns']


def _load_snapshot(stage):
    paths = {
        'odds':       os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json'),
        'intel':      os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json'),
        'standings':  os.path.join(SNAPSHOT_DIR, f'stage_{stage - 1}_standings.json'),
        'prev_results': os.path.join(SNAPSHOT_DIR, f'stage_{stage - 1}_results.json'),
    }
    out = {}
    for k, p in paths.items():
        out[k] = json.load(open(p)) if os.path.exists(p) else None
    return out


def _odds_list_from_snapshot(odds_raw):
    if isinstance(odds_raw, dict):
        return odds_raw.get('odds', odds_raw)
    return odds_raw or []


def _roster_from_basin(basin_file, strategy, target_sha):
    """Look up the team_names list for a given strategy/SHA in the persisted basin JSON."""
    data = json.load(open(basin_file))
    chains = data['chains_by_strategy'][strategy]['chains']
    for c in chains:
        if c['roster_sha'] == target_sha:
            return c['team_names']
    return None


def _make_roster(rider_names, active_riders):
    """Build a roster list of rider dicts from name list. Tolerates exact matches only."""
    by_name = {r['name']: r for r in active_riders}
    roster = []
    for n in rider_names:
        if n in by_name:
            roster.append(by_name[n])
    return roster


def section_a_function_inspection():
    print("=" * 88)
    print("  SECTION A — Function implementation inspection")
    print("=" * 88)

    # compute_team_ev
    ctev_src = inspect.getsource(compute_team_ev)
    ctev_lineno = inspect.getsourcelines(compute_team_ev)[1]
    print(f"\n### compute_team_ev — optimizer.py:{ctev_lineno}\n")
    print("```python")
    print(ctev_src.rstrip())
    print("```")

    # simulate_stage (just the signature + docstring + key MC block, full body too large)
    sim_src = inspect.getsource(simulate_stage)
    sim_lineno = inspect.getsourcelines(simulate_stage)[1]
    # Truncate body — print signature + docstring + key Plackett-Luce block only
    print(f"\n### simulate_stage — optimizer.py:{sim_lineno}\n")
    lines = sim_src.split('\n')
    # Show first ~14 lines (signature + docstring) plus the Plackett-Luce sampling block
    print("```python")
    for ln in lines[:15]:
        print(ln)
    print("    ...")
    # Print the Plackett-Luce block
    for i, ln in enumerate(lines):
        if 'Plackett-Luce' in ln or 'rng.uniform' in ln or 'np.argsort(scores' in ln:
            for j in range(max(0, i), min(len(lines), i + 6)):
                print(lines[j])
            break
    print("    ...")
    print("```")

    print("\n### Method classification\n")
    print("| Function           | Method                                              | Mutual-exclusivity |")
    print("|--------------------|-----------------------------------------------------|--------------------|")
    print("| compute_team_ev    | Naive marginal sum (Σ per-rider total_ev + max + ε) | NOT modeled        |")
    print("| simulate_stage     | Plackett-Luce Monte Carlo (n_sims=10,000 joint draws) | YES (one rider per finish position) |")

    print("\n### Call site enumeration\n")
    print("compute_team_ev:")
    print("  - optimizer.py:819   _compute_objective('ev' branch)   — SA objective fallback")
    print("  - optimizer.py:943   fast_optimize SA loop (initial)   — forward-stage proxy")
    print("  - optimizer.py:972   fast_optimize SA inner            — forward-stage proxy iter")
    print("  - optimizer.py:1031  compute_objective(team, ...)      — multi-strategy SA objective")
    print("  - optimizer.py:1449  post-SA reporting                 — 'true analytical EV' for diags")
    print("simulate_stage:")
    print("  - optimizer.py:1687  generate_candidate_teams chain eval — produces displayed Net EV")
    print("  (No SA call site uses simulate_stage; SA uses compute_team_ev exclusively.)")

    print("\n### Hypothesis assessment at code level\n")
    print("  Q: Does compute_team_ev use bookmaker marginal probabilities directly")
    print("     (independence-assuming)?")
    print("  A: YES. Line 730-731 reads pre-computed `total_ev` per rider (= sum of")
    print("     finish_ev/sprint_ev/gc_ev/jersey_ev/kom_ev marginals from build_probabilities).")
    print("     Line 733 adds `max(total_evs)` as captain bonus. Line 734 adds team_bonus_ev.")
    print("     Line 735-736 adds depth_bonus from `round(sum(top15))` — sums marginal top-15 probs")
    print("     into a single expected-top-15-count integer and looks up DEPTH_BONUS table.")
    print("     NO modelling of which rider actually finishes 1st vs 2nd vs ... in joint dist.")

    print("\n  Q: Does simulate_stage sample stage outcomes with mutual-exclusivity preserved?")
    print("  A: YES. Plackett-Luce scoring at line 1920-1923:")
    print("       u      = rng.uniform(1e-12, 1.0, (n_sims, n_field))")
    print("       scores = -log(u) / field_probs   # one score per (sim, rider)")
    print("       order  = argsort(scores, axis=1) # argsort → finish order per sim")
    print("     Exactly ONE rider gets each finish position per simulation. Per-position points")
    print("     (FINISH_POINTS table) are accumulated only for the rider at that position.")
    print("     n_sims=10,000 joint realizations across the full ~170-rider field.")

    print("\n  → Hypothesis CONFIRMED at code level:")
    print("    - compute_team_ev independence-assuming marginal sum")
    print("    - simulate_stage joint-distribution Plackett-Luce MC")
    print("    - SA loops invoke compute_team_ev (line 1031); displayed Net EV uses simulate_stage")
    print("    - These are genuinely different EV formulations.")

    return {
        'compute_team_ev': {
            'method': 'naive_marginal_sum',
            'mutual_exclusivity': False,
            'call_sites': [
                'optimizer.py:819 (_compute_objective ev branch)',
                'optimizer.py:943 (fast_optimize initial)',
                'optimizer.py:972 (fast_optimize inner)',
                'optimizer.py:1031 (compute_objective)',
                'optimizer.py:1449 (post-SA reporting)',
            ],
        },
        'simulate_stage': {
            'method': 'plackett_luce_monte_carlo',
            'n_sims_default': 10_000,
            'mutual_exclusivity': True,
            'call_sites': [
                'optimizer.py:1687 (generate_candidate_teams chain eval — displayed Net EV)',
            ],
        },
        'hypothesis_verdict': 'CONFIRMED_AT_CODE_LEVEL',
    }


def section_b_numerical_comparison(stage: int):
    print("\n" + "=" * 88)
    print("  SECTION B — Direct numerical comparison")
    print("=" * 88)

    snap = _load_snapshot(stage)
    active = _load_riders()
    odds_list = _odds_list_from_snapshot(snap.get('odds'))
    intel_real = snap.get('intel') or {}
    standings = snap.get('standings') or {}
    scoring = load_stage_scoring()
    stage_cfg = get_stage_config(stage, scoring)

    # Build probabilities with real intel (post-INTEL_MULT) — same path SA uses
    probs = build_probabilities(
        active, odds_list, intel_real,
        sliders={'bunch_sprint': 70, 'reduced_sprint': 20, 'gc': 5, 'breakaway': 5, 'time_trial': 0},
        stage_config=stage_cfg, scoring=scoring,
        use_race_type=False, standings=standings,
    )

    # Load Stage 9 basin enumeration from earlier diagnostic
    basin_data = json.load(open(BASIN_FILE))

    # Roster definitions
    # Pre-resolved SHAs from prior diagnostic output:
    OPT_GALL_SHA   = 'b2bed0e50232'  # Optimal best-corroborated 3/10 (Gall captain)
    DEP_GALL_SHA   = '49283f3b8263'  # Depth dominant 8/10 (Gall captain)
    LOO_VING_SHA   = 'a33da892cd1c'  # Lookahead dominant 5/10 (Vingegaard captain)

    opt_names  = _roster_from_basin(BASIN_FILE, 'optimal',   OPT_GALL_SHA)
    dep_names  = _roster_from_basin(BASIN_FILE, 'depth',     DEP_GALL_SHA)
    loo_names  = _roster_from_basin(BASIN_FILE, 'lookahead', LOO_VING_SHA)

    print(f"\n  Optimal best-corr roster (SHA {OPT_GALL_SHA}): {opt_names}")
    print(f"  Depth dominant   roster (SHA {DEP_GALL_SHA}): {dep_names}")
    print(f"  Lookahead dominant roster (SHA {LOO_VING_SHA}): {loo_names}")

    # Build Roster #4 — Optimal with Vingegaard swapped in for a low-EV rider
    # Use Optimal's roster (Gall captain) but replace Garofoli (lowest EVpost = 65k) with Vingegaard
    opt_with_ving = [n for n in opt_names if n != 'Gianmarco Garofoli'] + ['Jonas Vingegaard']

    # Build Roster #5 — Lookahead with Gall in place of Vingegaard
    # Use Lookahead's roster but replace Vingegaard with Felix Gall + adjust for budget
    # (Vingegaard 18.24M, Gall 9.45M → frees 8.79M; remaining roster still valid)
    loo_with_gall = [n for n in loo_names if n != 'Jonas Vingegaard'] + ['Felix Gall']

    # Roster #6 — current team
    prev_results = snap.get('prev_results') or {}
    current_team_names = [r.get('name') for r in prev_results.get('rider_results', []) if r.get('name')]
    # Truncate to 8 if more (shouldn't be)
    current_team_names = current_team_names[:8]

    rosters = [
        ('1_optimal_bestcorr',    opt_names,        'Felix Gall'),
        ('2_lookahead_bestcorr',  loo_names,        'Jonas Vingegaard'),
        ('3_depth_dominant',      dep_names,        'Felix Gall'),
        ('4_opt_swap_in_ving',    opt_with_ving,    'Jonas Vingegaard'),
        ('5_loo_swap_in_gall',    loo_with_gall,    'Felix Gall'),
        ('6_current_team',        current_team_names, None),
    ]

    print("\n  Evaluation under both functions (compute_team_ev marginal-sum vs simulate_stage MC):")
    print()
    print(f"  {'Roster':28s}  {'Cap':24s}  {'compute_team_ev':>16s}  {'simulate_stage':>16s}  {'Δ_abs':>10s}  {'Δ_pct':>7s}  {'which_higher':>14s}")
    print(f"  {'-'*28}  {'-'*24}  {'-'*16}  {'-'*16}  {'-'*10}  {'-'*7}  {'-'*14}")

    results = []
    for label, names, captain in rosters:
        team = _make_roster(names, active)
        if len(team) != 8:
            print(f"  {label:28s}  [SKIP: only {len(team)} riders matched out of {len(names)} — {set(names) - {r['name'] for r in team}}]")
            results.append({'label': label, 'skip_reason': f'matched {len(team)}/8'})
            continue
        if captain is None:
            captain_obj = select_captain(team, probs)
            captain = captain_obj['name']
        cte = compute_team_ev(team, probs)
        # Use a fixed seed for simulate_stage reproducibility
        sim = simulate_stage(
            team, probs, captain,
            all_riders=active, stage_config=stage_cfg, scoring=scoring,
            seed=42, n_sims=10_000,
        )
        sim_mean = sim['mean']
        d_abs = sim_mean - cte
        d_pct = (d_abs / cte * 100) if cte else 0.0
        which = 'simulate_stage' if sim_mean > cte else 'compute_team_ev'
        print(f"  {label:28s}  {captain[:24]:24s}  {cte:>16,.0f}  {sim_mean:>16,.0f}  {d_abs:>+10,.0f}  {d_pct:>+6.1f}%  {which:>14s}")
        results.append({
            'label': label,
            'roster': names,
            'captain': captain,
            'compute_team_ev': float(cte),
            'simulate_stage_mean': float(sim_mean),
            'delta_abs': float(d_abs),
            'delta_pct': float(d_pct),
            'which_higher': which,
        })

    # Critical test: optimal vs lookahead
    print("\n### Critical test: Optimal vs Lookahead\n")
    opt = next((r for r in results if r['label'] == '1_optimal_bestcorr' and 'compute_team_ev' in r), None)
    loo = next((r for r in results if r['label'] == '2_lookahead_bestcorr' and 'compute_team_ev' in r), None)
    if opt and loo:
        cte_winner = 'optimal' if opt['compute_team_ev'] > loo['compute_team_ev'] else 'lookahead'
        sim_winner = 'optimal' if opt['simulate_stage_mean'] > loo['simulate_stage_mean'] else 'lookahead'
        cte_diff = opt['compute_team_ev'] - loo['compute_team_ev']
        sim_diff = opt['simulate_stage_mean'] - loo['simulate_stage_mean']
        print(f"  compute_team_ev:  optimal {opt['compute_team_ev']:,.0f}  vs  lookahead {loo['compute_team_ev']:,.0f}  (Δ_opt_vs_loo = {cte_diff:+,.0f}; {cte_winner} higher)")
        print(f"  simulate_stage:   optimal {opt['simulate_stage_mean']:,.0f}  vs  lookahead {loo['simulate_stage_mean']:,.0f}  (Δ_opt_vs_loo = {sim_diff:+,.0f}; {sim_winner} higher)")
        if cte_winner != sim_winner:
            print(f"\n  → Functions RANK OPPOSITELY: compute_team_ev prefers {cte_winner}; simulate_stage prefers {sim_winner}.")
            print(f"  → Hypothesis CONFIRMED numerically.")
            critical_result = 'CONFIRMED_RANK_OPPOSITELY'
        else:
            print(f"\n  → Functions AGREE on ranking ({sim_winner} preferred by both).")
            print(f"  → Hypothesis FALSIFIED at numerical level.")
            critical_result = 'FALSIFIED_AGREE'
    else:
        critical_result = 'UNDETERMINED_SKIPPED'

    return {
        'rosters': results,
        'critical_test': critical_result,
    }


def section_c_stress_test(stage: int):
    print("\n" + "=" * 88)
    print("  SECTION C — Synthetic stress-test")
    print("=" * 88)

    snap = _load_snapshot(stage)
    active = _load_riders()
    odds_list = _odds_list_from_snapshot(snap.get('odds'))
    intel_real = snap.get('intel') or {}
    standings = snap.get('standings') or {}
    scoring = load_stage_scoring()
    stage_cfg = get_stage_config(stage, scoring)

    probs_real = build_probabilities(
        active, odds_list, intel_real,
        sliders={'bunch_sprint': 70, 'reduced_sprint': 20, 'gc': 5, 'breakaway': 5, 'time_trial': 0},
        stage_config=stage_cfg, scoring=scoring,
        use_race_type=False, standings=standings,
    )

    # For stress test we synthesize stylized win/top3/top10/top15 probs for two
    # hypothetical 8-rider rosters and inject them into a probs dict copy.
    # Roster A: one big favorite (~30% win) + 7 medium (~3% win each)
    # Roster B: zero big favorites + 8 medium (~3% win each)

    # Use real rider names from active roster to satisfy team-bonus / team-cap
    # constraints, but override their probabilities for the synthetic test.
    by_name = {r['name']: r for r in active}

    # Pick 16 riders from active roster — first 16 by some order so this is reproducible
    sample_pool = sorted(active, key=lambda r: r['name'])[:16]
    big_fav_name = sample_pool[0]['name']
    roster_A_names = [r['name'] for r in sample_pool[:8]]
    roster_B_names = [r['name'] for r in sample_pool[8:16]]

    # Build synthetic probs override
    probs_synth = copy.deepcopy(probs_real)

    def _make_rider_probs(p_win, p_top3, p_top10, p_top15):
        """Compute finish_ev from per-position probs the way build_probabilities does."""
        _FP_W1    = FINISH_POINTS[0]
        _FP_W23   = (FINISH_POINTS[1] + FINISH_POINTS[2]) / 2
        _FP_W4_10 = sum(FINISH_POINTS[3:10]) / 7
        _FP_W11_15= sum(FINISH_POINTS[10:15]) / 5
        d23  = max(0.0, p_top3 - p_win) / 2
        d410 = max(0.0, p_top10 - p_top3) / 7
        d1115= max(0.0, p_top15 - p_top10) / 5
        finish_ev = (p_win * _FP_W1 + d23 * 2 * _FP_W23
                     + d410 * 7 * _FP_W4_10 + d1115 * 5 * _FP_W11_15)
        return {
            'win': p_win, 'top3': p_top3, 'top10': p_top10, 'top15': p_top15,
            'finish_ev': finish_ev,
            'sprint_ev': 0.0, 'jersey_ev': 0.0, 'gc_ev': 0.0, 'kom_ev': 0.0,
            'total_ev': finish_ev,
            'p2': d23, 'p3': d23, 'p_top15': p_top15,
            'finish_probs': [p_win] + [d23] * 2 + [d410] * 7 + [d1115] * 5,
        }

    # Roster A — big favorite + 7 medium
    big_fav_probs = _make_rider_probs(0.30, 0.75, 0.95, 0.95)
    medium_A = _make_rider_probs(0.03, 0.25, 0.80, 0.85)
    probs_synth[roster_A_names[0]] = {
        **probs_synth.get(roster_A_names[0], {}),
        **big_fav_probs,
        'name': roster_A_names[0],
        'team': by_name[roster_A_names[0]].get('team', ''),
    }
    for n in roster_A_names[1:]:
        probs_synth[n] = {**probs_synth.get(n, {}), **medium_A, 'name': n, 'team': by_name[n].get('team', '')}

    # Roster B — 8 medium with slightly higher top-3 and top-10 than A's mediums
    medium_B = _make_rider_probs(0.03, 0.30, 0.85, 0.88)
    for n in roster_B_names:
        probs_synth[n] = {**probs_synth.get(n, {}), **medium_B, 'name': n, 'team': by_name[n].get('team', '')}

    team_A = _make_roster(roster_A_names, active)
    team_B = _make_roster(roster_B_names, active)

    # Marginal-sum naive evaluations + MC evaluations
    print(f"\n  Roster A — '1 big favorite (Vingegaard-like, p_win=30%) + 7 medium':")
    print(f"    Riders: {roster_A_names}")
    print(f"  Roster B — '8 medium with no big favorite':")
    print(f"    Riders: {roster_B_names}")

    cte_A = compute_team_ev(team_A, probs_synth)
    cte_B = compute_team_ev(team_B, probs_synth)
    capt_A = select_captain(team_A, probs_synth)['name']
    capt_B = select_captain(team_B, probs_synth)['name']
    sim_A = simulate_stage(team_A, probs_synth, capt_A, all_riders=active,
                            stage_config=stage_cfg, scoring=scoring, seed=42, n_sims=10_000)['mean']
    sim_B = simulate_stage(team_B, probs_synth, capt_B, all_riders=active,
                            stage_config=stage_cfg, scoring=scoring, seed=42, n_sims=10_000)['mean']

    print()
    print(f"  {'Roster':12s}  {'Captain':24s}  {'compute_team_ev':>16s}  {'simulate_stage':>16s}  {'Δ_abs':>10s}  {'which_higher':>14s}")
    print(f"  {'-'*12}  {'-'*24}  {'-'*16}  {'-'*16}  {'-'*10}  {'-'*14}")
    for label, capt, cte, sim in [('A', capt_A, cte_A, sim_A), ('B', capt_B, cte_B, sim_B)]:
        d = sim - cte
        print(f"  {label:12s}  {capt[:24]:24s}  {cte:>16,.0f}  {sim:>16,.0f}  {d:>+10,.0f}  {'simulate_stage' if sim > cte else 'compute_team_ev':>14s}")

    cte_winner = 'A' if cte_A > cte_B else 'B'
    sim_winner = 'A' if sim_A > sim_B else 'B'
    print(f"\n  Cross-roster ranking:")
    print(f"    compute_team_ev: {'A > B' if cte_A > cte_B else 'B > A'}  (Δ = {abs(cte_A - cte_B):,.0f})")
    print(f"    simulate_stage:  {'A > B' if sim_A > sim_B else 'B > A'}  (Δ = {abs(sim_A - sim_B):,.0f})")

    if cte_winner != sim_winner:
        print(f"\n  → Functions RANK OPPOSITELY (compute_team_ev prefers {cte_winner}; simulate_stage prefers {sim_winner}).")
        print(f"  → Textbook example of mutual-exclusivity asymmetry.")
        result = 'OPPOSITE_RANKING'
    else:
        print(f"\n  → Functions AGREE ({sim_winner} preferred by both).")
        print(f"  → Difference is magnitude not direction.")
        result = 'AGREEMENT'

    return {
        'roster_A_names': roster_A_names,
        'roster_B_names': roster_B_names,
        'roster_A_compute_team_ev': float(cte_A),
        'roster_A_simulate_stage': float(sim_A),
        'roster_B_compute_team_ev': float(cte_B),
        'roster_B_simulate_stage': float(sim_B),
        'cte_winner': cte_winner,
        'sim_winner': sim_winner,
        'verdict': result,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=int, default=9)
    args = ap.parse_args()

    print(f"\n{'#'*88}")
    print(f"# EV-function asymmetry verification — Stage {args.stage}")
    print(f"# Verifies compute_team_ev (SA objective) ↔ simulate_stage (reported Net EV)")
    print(f"# rank rosters oppositely.")
    print(f"{'#'*88}")

    a = section_a_function_inspection()
    b = section_b_numerical_comparison(args.stage)
    c = section_c_stress_test(args.stage)

    print("\n" + "=" * 88)
    print("  FINAL VERDICT")
    print("=" * 88)
    code_level = a.get('hypothesis_verdict', '?')
    crit_b = b.get('critical_test', '?')
    crit_c = c.get('verdict', '?')
    print(f"  Section A (code level):    {code_level}")
    print(f"  Section B (real rosters):  {crit_b}")
    print(f"  Section C (stress test):   {crit_c}")
    confirmed = (code_level == 'CONFIRMED_AT_CODE_LEVEL'
                 and crit_b == 'CONFIRMED_RANK_OPPOSITELY'
                 and crit_c == 'OPPOSITE_RANKING')
    if confirmed:
        verdict = 'CONFIRMED — compute_team_ev and simulate_stage rank rosters oppositely on Stage 9 substrate; the asymmetry is the load-bearing mechanism behind the optimal/lookahead Net EV gap'
    elif code_level == 'CONFIRMED_AT_CODE_LEVEL' and (crit_b == 'CONFIRMED_RANK_OPPOSITELY' or crit_c == 'OPPOSITE_RANKING'):
        verdict = 'PARTIAL — functions differ structurally + at least one numerical test ranks oppositely; details below'
    else:
        verdict = 'FALSIFIED at numerical level — functions agree on ranking despite different shapes; alternative theory required'
    print(f"\n  Final: {verdict}")

    payload = {'section_a': a, 'section_b': b, 'section_c': c, 'final_verdict': verdict}
    with open('/tmp/s17_intel_ev_function_audit.json', 'w') as f:
        json.dump(payload, f, default=str, indent=2)
    print(f"\nPersisted: /tmp/s17_intel_ev_function_audit.json\n")


if __name__ == '__main__':
    main()
