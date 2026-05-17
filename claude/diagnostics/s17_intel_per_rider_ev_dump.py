"""
Per-rider EV diagnostic + strategy-basin investigation (2026-05-17).

Read-only diagnostic answering operator-surfaced questions on Stage N:
  Q1: Why does optimal report ~430k Net EV behind lookahead?
  Q2: Why does optimal/depth select Felix Gall captain while lookahead
      selects Vingegaard?
  Q3: Is intel adjustment proportional across riders, or asymmetric?
  Q4: Vingegaard stage_EV value vs domain expectation?
  Q5: Captain Δ EV — did intel choose captain or roster composition?

Deliverables:
  Section A: per-rider stage_EV decomposition (top-30 universe + per-card
             mini-tables) with pre/post-INTEL_MULT columns
  Section B: per-strategy basin reachability across 10 SA chains
  Section C: cross-strategy roster diff

Persisted JSON:
  /tmp/s17_intel_stage_{N}_per_rider_ev.json
  /tmp/s17_intel_stage_{N}_strategy_basins.json

Usage:
  python3 claude/diagnostics/s17_intel_per_rider_ev_dump.py [--stage N]
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
import sys
from collections import Counter

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3'
sys.path.insert(0, os.path.join(REPO, 'claude', 'engine'))

from optimizer import (
    INTEL_MULT,
    FINISH_POINTS,
    build_probabilities,
    build_forward_probabilities,
    compute_seed,
    compute_team_ev,
    compute_transfer_cost,
    estimate_forward_costs,
    fast_optimize,
    get_stage_config,
    load_stage_scoring,
    select_captain,
    simulated_annealing,
    simulate_stage,
    topup_team,
    build_tier_union_pool,
)

SNAPSHOT_DIR = os.path.join(REPO, 'shared', 'data', 'snapshots')
RIDERS_FILE = os.path.join(REPO, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')
TERRAIN_OVERRIDES = os.path.join(
    REPO, 'shared', 'data', 'riders', 'giro_2026', 'terrain_affinity_overrides.json'
)

# Dashboard default sliders (matches claude.html S.sliders defaults; the
# realistic production input shape).
DEFAULT_SLIDERS = {
    'n1': {'bunch_sprint': 70, 'reduced_sprint': 20, 'gc': 5,  'breakaway': 5,  'time_trial': 0},
    'n2': {'bunch_sprint': 50, 'reduced_sprint': 30, 'gc': 10, 'breakaway': 10, 'time_trial': 0},
    'n3': {'bunch_sprint': 30, 'reduced_sprint': 30, 'gc': 30, 'breakaway': 10, 'time_trial': 0},
}


def _load_riders():
    data = json.load(open(RIDERS_FILE))
    riders = data['riders']
    # Apply terrain_affinity overrides if present
    if os.path.exists(TERRAIN_OVERRIDES):
        try:
            overrides = json.load(open(TERRAIN_OVERRIDES))
            if isinstance(overrides, dict):
                out = []
                for r in riders:
                    entry = overrides.get(r.get('name'))
                    if entry and isinstance(entry.get('overrides'), dict):
                        r = dict(r)
                        r['terrain_affinity'] = dict(entry['overrides'])
                    out.append(r)
                riders = out
        except Exception:
            pass
    return [r for r in riders if not r.get('isOut') and r.get('status') != 'dns']


def _load_snapshot(stage):
    paths = {
        'odds':       os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json'),
        'intel':      os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json'),
        'standings':  os.path.join(SNAPSHOT_DIR, f'stage_{stage - 1}_standings.json'),
        'prev_results': os.path.join(SNAPSHOT_DIR, f'stage_{stage - 1}_results.json'),
    }
    out = {}
    for k, p in paths.items():
        if os.path.exists(p):
            try:
                with open(p, 'rb') as f:
                    raw = f.read()
                out[f'{k}_sha'] = hashlib.sha256(raw).hexdigest()[:16]
                out[k] = json.loads(raw.decode('utf-8'))
            except Exception as e:
                out[k] = None
                out[f'{k}_sha'] = f'ERR:{e}'
        else:
            out[k] = None
            out[f'{k}_sha'] = 'MISSING'
    return out


def _odds_list_from_snapshot(odds_raw):
    if isinstance(odds_raw, dict):
        return odds_raw.get('odds', odds_raw)
    return odds_raw or []


def _intel_signal_for(intel_block, rider_name):
    """Return (direction, strength, multiplier) for the rider, or None."""
    if not isinstance(intel_block, dict):
        return None
    src = intel_block.get('intel', intel_block)
    if not isinstance(src, dict):
        return None
    rname = (rider_name or '').lower()
    for sig in src.get('key_signals', []) or []:
        sr = (sig.get('rider') or '').lower()
        # Tolerant match — last-name suffix sufficient for diagnostic
        if sr == rname or rname.endswith(sr) or sr.endswith(rname.split()[-1]):
            d = sig.get('direction', 'neutral')
            s = sig.get('strength', 'weak')
            mult = INTEL_MULT.get((d, s), 1.0)
            return (d, s, mult)
    return None


def _expert_stars_compact(expert_stars, rider_name, sources_order):
    """Compact per-source star summary like '5/4/5/4/null/3/...'."""
    rec = expert_stars.get(rider_name, {}) if isinstance(expert_stars, dict) else {}
    return '/'.join(str(rec.get(s, '·') if rec.get(s) is not None else 'n') for s in sources_order)


def _expert_stars_avg(expert_stars, rider_name, sources_order):
    rec = expert_stars.get(rider_name, {}) if isinstance(expert_stars, dict) else {}
    vals = [v for v in (rec.get(s) for s in sources_order) if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else None


def _roster_sha(team):
    names = sorted(r.get('name', '') for r in team)
    return hashlib.sha256('|'.join(names).encode()).hexdigest()[:12]


def section_a_per_rider_ev(stage: int, top_n: int = 30):
    print(f"\n{'='*88}")
    print(f"  SECTION A — Per-rider stage_EV decomposition (Stage {stage}, top-{top_n})")
    print(f"{'='*88}\n")

    snap = _load_snapshot(stage)
    print(f"  Substrate SHAs:")
    print(f"    odds:        {snap.get('odds_sha')}")
    print(f"    intel:       {snap.get('intel_sha')}")
    print(f"    standings:   {snap.get('standings_sha')}")
    print(f"    prev_result: {snap.get('prev_results_sha')}")
    print()

    active = _load_riders()
    odds_list = _odds_list_from_snapshot(snap.get('odds'))
    intel_real = snap.get('intel') or {}
    standings = snap.get('standings') or {}
    scoring = load_stage_scoring()
    stage_cfg = get_stage_config(stage, scoring)

    # Compute pre-INTEL_MULT probabilities by passing empty intel
    # (key_signals=[] → adj dict empty → all multipliers stay at 1.0).
    intel_empty: dict = {'intel': {'key_signals': []}}

    probs_pre = build_probabilities(
        active, odds_list, intel_empty,
        sliders=DEFAULT_SLIDERS.get('n1'),
        stage_config=stage_cfg, scoring=scoring,
        use_race_type=False, standings=standings,
    )
    probs_post = build_probabilities(
        active, odds_list, intel_real,
        sliders=DEFAULT_SLIDERS.get('n1'),
        stage_config=stage_cfg, scoring=scoring,
        use_race_type=False, standings=standings,
    )

    # Source list for expert_stars compact display
    intel_inner = intel_real.get('intel', intel_real) if isinstance(intel_real, dict) else {}
    expert_stars = intel_inner.get('expert_stars', {}) if isinstance(intel_inner, dict) else {}
    sources_consulted = intel_inner.get('sources_consulted', []) if isinstance(intel_inner, dict) else []
    sources_order = list(sources_consulted) or sorted({s for v in expert_stars.values() for s in (v or {}).keys()})

    # Build per-rider row dataset
    rows = []
    for r in active:
        name = r['name']
        pre = probs_pre.get(name, {})
        post = probs_post.get(name, {})
        if not pre or not post:
            continue
        sev_pre  = pre.get('total_ev', 0.0)
        sev_post = post.get('total_ev', 0.0)
        sig = _intel_signal_for(intel_real, name)
        intel_mult_decl = sig[2] if sig else 1.0
        observed_mult = (sev_post / sev_pre) if sev_pre > 1e-6 else None
        delta_abs = sev_post - sev_pre
        # expert_stars compact summary
        es_avg = _expert_stars_avg(expert_stars, name, sources_order)
        rows.append({
            'rider':       name,
            'price':       r.get('price', 0) / 1e6,
            'raw_win':     pre.get('win', 0),
            'raw_top3':    pre.get('top3', 0),
            'raw_top10':   pre.get('top10', 0),
            'raw_top15':   pre.get('top15', 0),
            'finish_ev_pre':  pre.get('finish_ev', 0),
            'finish_ev_post': post.get('finish_ev', 0),
            'sprint_ev_post': post.get('sprint_ev', 0),
            'gc_ev_post':     post.get('gc_ev', 0),
            'jersey_ev_post': post.get('jersey_ev', 0),
            'kom_ev_post':    post.get('kom_ev', 0),
            'stage_EV_pre':  int(sev_pre),
            'stage_EV_post': int(sev_post),
            'delta_abs':     int(delta_abs),
            'intel_mult_declared': intel_mult_decl,
            'observed_mult':       observed_mult,
            'key_signal_dir':  sig[0] if sig else None,
            'key_signal_str':  sig[1] if sig else None,
            'expert_stars_avg': es_avg,
            'expert_stars_compact': _expert_stars_compact(expert_stars, name, sources_order),
        })

    rows.sort(key=lambda x: -x['stage_EV_post'])
    universe = rows[:top_n]

    # Print universe table
    hdr = f"  {'#':>2}  {'Rider':24s}  {'Price':>5s}  {'rawWin':>6s} {'rawT3':>5s} {'rawT10':>6s} {'rawT15':>6s}  {'EVpre':>7s}  {'×':>5s}  {'EVpost':>7s}  {'ΔEV':>6s}  {'dir':>4s} {'str':>5s}  {'ESavg':>5s}  {'sources(*=consulted)':30s}"
    print(hdr)
    print(f"  {'-'*2}  {'-'*24}  {'-'*5}  {'-'*6} {'-'*5} {'-'*6} {'-'*6}  {'-'*7}  {'-'*5}  {'-'*7}  {'-'*6}  {'-'*4} {'-'*5}  {'-'*5}  {'-'*30}")
    for i, x in enumerate(universe, 1):
        om = x['observed_mult'] if x['observed_mult'] is not None else float('nan')
        es = f"{x['expert_stars_avg']:.2f}" if x['expert_stars_avg'] is not None else '  · '
        dir_s = x['key_signal_dir'] or '·'
        str_s = x['key_signal_str'] or '·'
        # Truncate name to 24 chars
        rname = x['rider'][:24]
        print(f"  {i:>2}  {rname:24s}  {x['price']:>5.2f}  "
              f"{x['raw_win']*100:>5.1f}% {x['raw_top3']*100:>4.0f}% {x['raw_top10']*100:>5.0f}% {x['raw_top15']*100:>5.0f}%  "
              f"{x['stage_EV_pre']:>7,d}  ×{om:>4.2f}  {x['stage_EV_post']:>7,d}  "
              f"{x['delta_abs']:>+6,d}  "
              f"{dir_s[:4]:>4s} {str_s[:5]:>5s}  {es:>5s}")

    return {
        'rows': rows,
        'universe': universe,
        'sources_order': sources_order,
        'probs_pre': probs_pre,
        'probs_post': probs_post,
        'snap': snap,
        'active': active,
        'scoring': scoring,
        'stage_cfg': stage_cfg,
    }


def section_a_card_minitables(ctx, optimizer_output_path):
    print(f"\n{'='*88}")
    print(f"  SECTION A — Per-card roster mini-tables")
    print(f"{'='*88}\n")
    if not os.path.exists(optimizer_output_path):
        print(f"  [optimizer output not available at {optimizer_output_path}; skipping mini-tables]")
        return {}

    out = json.load(open(optimizer_output_path))
    rows_by_name = {x['rider']: x for x in ctx['rows']}

    minis = {}
    for team in out.get('teams', []):
        strategy = team.get('strategy', 'unknown')
        captain_name = team.get('captain', {}).get('name')
        roster_rows = []
        for r in team.get('riders', []):
            rname = r.get('name')
            row = rows_by_name.get(rname)
            if not row:
                continue
            row = dict(row)
            row['is_captain'] = (rname == captain_name)
            roster_rows.append(row)
        # Sort: captain first, then by stage_EV_post desc
        roster_rows.sort(key=lambda x: (-int(bool(x.get('is_captain'))), -x['stage_EV_post']))
        minis[strategy] = {
            'captain': captain_name,
            'rows': roster_rows,
            'ev_net': team.get('ev_net'),
            'ev_estimate': team.get('ev_estimate'),
            'transfer_cost': team.get('transfer_cost'),
            'corroboration': team.get('convergence', {}),
        }

        print(f"\n### {strategy.upper()} — captain: {captain_name}  ev_net: {team.get('ev_net'):,}  transfer_cost: {team.get('transfer_cost'):,}")
        print(f"  {'role':>4s}  {'Rider':24s}  {'Price':>5s}  {'EVpre':>7s}  {'×':>5s}  {'EVpost':>7s}  {'ΔEV':>6s}  {'dir':>4s} {'str':>5s}  {'ESavg':>5s}")
        for x in roster_rows:
            om = x['observed_mult'] if x['observed_mult'] is not None else float('nan')
            es = f"{x['expert_stars_avg']:.2f}" if x['expert_stars_avg'] is not None else '  · '
            dir_s = x['key_signal_dir'] or '·'
            str_s = x['key_signal_str'] or '·'
            role = '🅒' if x.get('is_captain') else ' '
            rname = x['rider'][:24]
            print(f"  {role:>4s}  {rname:24s}  {x['price']:>5.2f}  "
                  f"{x['stage_EV_pre']:>7,d}  ×{om:>4.2f}  {x['stage_EV_post']:>7,d}  "
                  f"{x['delta_abs']:>+6,d}  "
                  f"{dir_s[:4]:>4s} {str_s[:5]:>5s}  {es:>5s}")
    return minis


def section_b_chain_enumeration(ctx, stage: int):
    print(f"\n{'='*88}")
    print(f"  SECTION B — Per-strategy basin reachability (10 SA chains/strategy)")
    print(f"{'='*88}\n")

    active = ctx['active']
    snap = ctx['snap']
    probs_post = ctx['probs_post']
    scoring = ctx['scoring']
    stage_cfg = ctx['stage_cfg']
    odds_list = _odds_list_from_snapshot(snap.get('odds'))
    intel_real = snap.get('intel') or {}
    standings = snap.get('standings') or {}

    # Replicate production seed derivation per server.py
    base_seed = compute_seed(stage, DEFAULT_SLIDERS, [], [], False)
    print(f"  base_seed: {base_seed}")

    # current_team from prev stage results
    prev_results = snap.get('prev_results') or {}
    current_team = None
    if prev_results:
        prev_names = [r.get('name') for r in prev_results.get('rider_results', []) if r.get('name')]
        by_lower = {r['name'].lower(): r for r in active}
        current_team = []
        for n in prev_names:
            if n.lower() in by_lower:
                current_team.append(by_lower[n.lower()])
        if not current_team:
            current_team = None

    # Build forward probabilities for cost_n1/cost_n2 estimation
    probs_n1 = build_forward_probabilities(active, DEFAULT_SLIDERS['n2'])
    probs_n2 = build_forward_probabilities(active, DEFAULT_SLIDERS['n3'])

    # Forward cost estimation — replicates generate_candidate_teams
    proxy_seed = base_seed ^ 0xF
    proxy = current_team or fast_optimize(
        active, probs_post, active, [], [], 50_000_000, seed=proxy_seed,
    )
    cost_n1, cost_n2, _, _, team_n1, team_n2 = estimate_forward_costs(
        proxy or [], active, active,
        probs_n1, probs_n2, [], [], 50_000_000, seed=base_seed,
    )

    # Tier-union pool for biased-swap
    biased_pool = build_tier_union_pool(
        active, odds_list, intel_real, standings, current_team,
        DEFAULT_SLIDERS, [], [],
    )

    LOOKAHEAD_DISCOUNT = 0.7
    N_CHAINS = 10
    _CHAIN_XOR_MASKS = tuple(0xC0 + i for i in range(N_CHAINS))
    eval_seed_shared = base_seed ^ 0xF

    strategies = [
        ('optimal',   0x1, 'ev',        {},                          5),
        ('depth',     0x2, 'depth',     {},                          5),
        ('lookahead', 0x4, 'lookahead', {'cooling_rate': 0.99999},    5),
    ]

    # budget from prev_results bank_balance
    budget = int((prev_results.get('bank_balance') if prev_results else None) or 50_000_000)
    print(f"  budget: {budget:,}")
    print(f"  current_team: {len(current_team) if current_team else 0} riders")
    print(f"  biased_pool: {len(biased_pool) if biased_pool else 'None'} riders")

    all_chains = {}
    for sname, sxor, sobj, soverrides, smaxs in strategies:
        print(f"\n  Running 10 chains for strategy={sname} ...")
        chains = []
        chain_seeds = [base_seed ^ (sxor << 8) ^ m for m in _CHAIN_XOR_MASKS]
        for ci, ch_seed in enumerate(chain_seeds):
            seed_team = current_team if (ci == 0 and current_team) else None
            team_ci, _ev_ci, _diags = simulated_annealing(
                active, probs_post, [], [],
                budget=budget,
                n_iter=200_000,
                max_seconds=smaxs,
                seed=ch_seed,
                objective=sobj,
                verbose=False,
                cost_n1=cost_n1, cost_n2=cost_n2,
                team_n1=team_n1, team_n2=team_n2,
                current_team=current_team,
                seed_team=seed_team,
                biased_pool=biased_pool,
                **soverrides,
            )
            if team_ci is None:
                continue
            team_ci = topup_team(team_ci, active, probs_post, active, budget)
            captain_ci = select_captain(team_ci, probs_post)
            sim_ci = simulate_stage(
                team_ci, probs_post, captain_ci['name'],
                all_riders=active, stage_config=stage_cfg, scoring=scoring,
                seed=eval_seed_shared,
            )
            stage_ev = int(sim_ci['mean'])
            tc = int(compute_transfer_cost(current_team or [], team_ci)) if current_team else 0
            tc_n1 = int(compute_transfer_cost(team_ci, team_n1 or [])) if team_n1 else 0
            tc_n2 = int(compute_transfer_cost(team_n1 or [], team_n2 or [])) if team_n1 and team_n2 else 0
            net_ev = int(stage_ev - tc)
            look_obj = int(stage_ev - tc - tc_n1 - LOOKAHEAD_DISCOUNT * tc_n2)
            chains.append({
                'chain':         ci,
                'stage_ev':      int(stage_ev),
                'transfer_cost': tc,
                'net_ev':        net_ev,
                'look_obj':      look_obj,
                'captain':       captain_ci['name'],
                'roster_sha':    _roster_sha(team_ci),
                'team_names':    sorted(r.get('name') for r in team_ci),
            })

        # Summary
        sha_counts = Counter(c['roster_sha'] for c in chains)
        n_distinct = len(sha_counts)
        sorted_by_ev = sorted(chains, key=lambda c: -c['stage_ev'])
        best_seen = sorted_by_ev[0] if sorted_by_ev else None
        # Best corroborated (stage_ev for non-lookahead, look_obj for lookahead)
        corroborated_shas = [sha for sha, cnt in sha_counts.items() if cnt >= 2]
        if sname == 'lookahead':
            sort_key = lambda c: c['look_obj']
        else:
            sort_key = lambda c: c['stage_ev']
        best_corr = None
        if corroborated_shas:
            best_corr = max(
                (c for c in chains if c['roster_sha'] in corroborated_shas),
                key=sort_key,
            )
        dominant_sha, dominant_count = sha_counts.most_common(1)[0] if sha_counts else (None, 0)

        print(f"\n  === {sname} ===")
        print(f"  {'#':>2}  {'stage_EV':>9s}  {'tc':>7s}  {'net_EV':>9s}  {'look_obj':>9s}  {'roster_SHA':>10s}  {'count':>5s}  {'captain':24s}")
        for c in chains:
            cnt = sha_counts.get(c['roster_sha'], 0)
            print(f"  {c['chain']:>2}  {c['stage_ev']:>9,d}  {c['transfer_cost']:>7,d}  {c['net_ev']:>+9,d}  {c['look_obj']:>+9,d}  {c['roster_sha']:>10s}  {cnt:>5d}  {c['captain'][:24]}")
        print(f"\n  Summary:")
        print(f"    n_chains: {len(chains)}/10")
        print(f"    distinct_basins: {n_distinct}")
        print(f"    dominant_basin: SHA={dominant_sha} count={dominant_count}/{len(chains)}")
        if best_seen:
            print(f"    best_seen:    stage_ev={best_seen['stage_ev']:,} net_ev={best_seen['net_ev']:,} captain={best_seen['captain']} SHA={best_seen['roster_sha']} count={sha_counts.get(best_seen['roster_sha'], 0)}")
        if best_corr:
            print(f"    best_corr:    stage_ev={best_corr['stage_ev']:,} net_ev={best_corr['net_ev']:,} look_obj={best_corr['look_obj']:,} captain={best_corr['captain']} SHA={best_corr['roster_sha']} count={sha_counts[best_corr['roster_sha']]}")
        else:
            print(f"    best_corr:    NONE (all singletons)")
        if best_seen and best_corr:
            gap = best_seen['stage_ev'] - best_corr['stage_ev']
            print(f"    best_seen − best_corroborated stage_ev gap: {gap:+,d}")

        all_chains[sname] = {
            'chains': chains,
            'distinct_basins': n_distinct,
            'dominant_sha': dominant_sha,
            'dominant_count': dominant_count,
            'best_seen': best_seen,
            'best_corr': best_corr,
        }
    return all_chains


def section_c_cross_strategy_diff(minis):
    print(f"\n{'='*88}")
    print(f"  SECTION C — Cross-strategy roster diff")
    print(f"{'='*88}\n")
    if not minis:
        print("  [no minis available; skipping]")
        return {}

    # Union of all riders across strategies
    all_riders = set()
    by_strategy = {}
    for sname, m in minis.items():
        names = [r['rider'] for r in m['rows']]
        all_riders.update(names)
        by_strategy[sname] = {r['rider']: r for r in m['rows']}

    print(f"  Union of riders across optimal/depth/lookahead: {len(all_riders)}")
    print()

    rows = []
    for rider in all_riders:
        row = {'rider': rider}
        for s in ('optimal', 'depth', 'lookahead'):
            r = by_strategy.get(s, {}).get(rider)
            row[s] = r['stage_EV_post'] if r else None
            row[f'{s}_captain'] = bool(r and r.get('is_captain'))
        rows.append(row)
    # Sort by lookahead EV desc (or any other), with riders present in lookahead first
    rows.sort(key=lambda x: (-(x.get('lookahead') or 0), -(x.get('optimal') or 0)))

    print(f"  {'Rider':24s}  {'optimal':>10s}  {'depth':>10s}  {'lookahead':>10s}  {'in':>6s}")
    print(f"  {'-'*24}  {'-'*10}  {'-'*10}  {'-'*10}  {'-'*6}")
    for x in rows:
        in_o = '🅒' if x['optimal_captain'] else ('✓' if x['optimal'] is not None else '·')
        in_d = '🅒' if x['depth_captain']   else ('✓' if x['depth']   is not None else '·')
        in_l = '🅒' if x['lookahead_captain'] else ('✓' if x['lookahead'] is not None else '·')
        o = f"{x['optimal']:>9,d}"   if x['optimal']   is not None else '         ·'
        d = f"{x['depth']:>9,d}"     if x['depth']     is not None else '         ·'
        l = f"{x['lookahead']:>9,d}" if x['lookahead'] is not None else '         ·'
        rname = x['rider'][:24]
        marker = f"{in_o}{in_d}{in_l}"
        print(f"  {rname:24s}  {o}  {d}  {l}  {marker:>6s}")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=int, default=9)
    ap.add_argument('--optimizer-output', default='/tmp/s17_innerring_v4f_post_optimizer.json',
                    help='Path to a /run-optimizer JSON output for this stage (for Section A mini-tables + Section C diff)')
    args = ap.parse_args()

    print(f"\n{'#'*88}")
    print(f"# Per-rider EV diagnostic + strategy-basin investigation — Stage {args.stage}")
    print(f"{'#'*88}")

    ctx = section_a_per_rider_ev(args.stage)
    minis = section_a_card_minitables(ctx, args.optimizer_output)
    chains = section_b_chain_enumeration(ctx, args.stage)
    cross = section_c_cross_strategy_diff(minis)

    # Persist
    persist_a = {
        'stage': args.stage,
        'substrate_shas': {k: v for k, v in ctx['snap'].items() if k.endswith('_sha')},
        'universe': ctx['universe'],
        'rows': ctx['rows'],
        'sources_order': ctx['sources_order'],
        'minis': {
            sname: {
                'captain': m['captain'],
                'ev_net': m['ev_net'],
                'ev_estimate': m['ev_estimate'],
                'transfer_cost': m['transfer_cost'],
                'corroboration': m['corroboration'],
                'rows': m['rows'],
            }
            for sname, m in minis.items()
        },
        'cross_strategy_rows': cross,
    }
    with open(f'/tmp/s17_intel_stage_{args.stage}_per_rider_ev.json', 'w') as f:
        json.dump(persist_a, f, default=str, indent=2)

    persist_b = {
        'stage': args.stage,
        'substrate_shas': {k: v for k, v in ctx['snap'].items() if k.endswith('_sha')},
        'chains_by_strategy': chains,
    }
    with open(f'/tmp/s17_intel_stage_{args.stage}_strategy_basins.json', 'w') as f:
        json.dump(persist_b, f, default=str, indent=2)

    print(f"\nPersisted:")
    print(f"  /tmp/s17_intel_stage_{args.stage}_per_rider_ev.json")
    print(f"  /tmp/s17_intel_stage_{args.stage}_strategy_basins.json")


if __name__ == '__main__':
    main()
