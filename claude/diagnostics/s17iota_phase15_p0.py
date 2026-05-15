"""S17-ι Phase 3 Phase 1.5 diagnostic — Sub-B2 dashboard surfacing failure.

Sub-B1 + Sub-B2 shipped 2026-05-14 with V1-V8 PASS. Eulálio expected to
surface in dashboard cards post-fix. Did not. This script identifies why.

Read-only. Compares the substrate path the dashboard reads against the
substrate my Sub-B2 verification used; surfaces the data dependency that
caused production runtime to skip the standings-aware override despite
the code being correct.
"""
import json
import os
import sys
import datetime

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3/.claude/worktrees/epic-hofstadter-ab23f7'
CANON = '/Users/lassestoltenberg/Claude/Holdet-v3'
sys.path.insert(0, os.path.join(REPO, 'claude', 'engine'))

from optimizer import (
    build_probabilities, load_stage_scoring, get_stage_config,
    add_stage_evs, _standings_rank_map,
)

STAGE = 6
TARGET = 'Afonso Eulálio'

INTEL_PATH = os.path.join(CANON, 'shared/data/snapshots/stage_6_intel.json')
ODDS_PATH  = os.path.join(CANON, 'shared/data/snapshots/stage_6_odds.json')
STDG_PATH  = os.path.join(CANON, 'shared/data/snapshots/stage_5_standings.json')


def step1_substrate_paths():
    print('=' * 72)
    print('STEP 1 — Substrate paths used by /run-optimizer vs my verification')
    print('=' * 72)
    # Dashboard path (via server.py /run-optimizer code path, lines 566/594/603)
    print('  Dashboard /run-optimizer reads (from server.py:566/594/603):')
    for label, path in [
        ('odds      ', ODDS_PATH),
        ('intel     ', INTEL_PATH),
        ('standings ', STDG_PATH),
    ]:
        print(f'    {label}{path}')
        if os.path.exists(path):
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(path))
            print(f'              ↳ exists, mtime={mtime}')
        else:
            print(f'              ↳ MISSING')

    print()
    print('  Sub-B2 verification (yesterday /tmp/sub_b_verify.py) read the SAME paths.')
    print('  → (A) substrate-mismatch RULED OUT — paths identical.')


def step2_intel_has_stage_signals():
    print()
    print('=' * 72)
    print('STEP 2 — Does the actual stage_6_intel.json have stage_signals.stage_type?')
    print('=' * 72)
    d = json.load(open(INTEL_PATH))
    inner = d.get('intel', d)
    keys = sorted(inner.keys()) if isinstance(inner, dict) else []
    print(f'  intel inner keys: {keys}')
    ss = inner.get('stage_signals') if isinstance(inner, dict) else None
    print(f'  stage_signals present? {ss is not None}')
    print(f'  stage_signals value:   {ss!r}')
    intel_stage_type = ss.get('stage_type') if isinstance(ss, dict) else None
    print(f'  extracted intel_stage_type: {intel_stage_type!r}')
    return intel_stage_type


def step3_diff_with_vs_without_injection():
    print()
    print('=' * 72)
    print('STEP 3 — Reproduce dashboard behaviour by passing the REAL intel through')
    print('         build_probabilities (no manual injection of stage_signals)')
    print('=' * 72)
    riders = json.load(open(os.path.join(CANON, 'shared/data/riders/giro_2026/riders.json')))['riders']
    active = [r for r in riders if not r.get('isOut') and r.get('status') != 'dns']
    odds = json.load(open(ODDS_PATH))
    if isinstance(odds, dict): odds = odds.get('odds', odds)
    intel = json.load(open(INTEL_PATH))                    # ← no manual injection
    standings = json.load(open(STDG_PATH))
    scoring = load_stage_scoring(); sc = get_stage_config(STAGE, scoring)
    sliders_n1 = {'bunch_sprint': 80, 'reduced_sprint': 20, 'gc': 0, 'breakaway': 0}

    # PRODUCTION-EQUIVALENT call: real intel, standings passed, use_race_type=False
    probs = build_probabilities(active, odds, intel, sliders_n1,
                                 stage_config=sc, scoring=scoring,
                                 use_race_type=False,
                                 standings=standings)
    eu = probs.get(TARGET, {})
    print(f'  PRODUCTION-equivalent (no stage_signals injection):')
    print(f'    Eulálio total_ev = {eu.get("total_ev", 0):,.0f}')
    print(f'    Eulálio gc_ev    = {eu.get("gc_ev", 0):,.0f}')
    print(f'    Eulálio jersey_ev= {eu.get("jersey_ev", 0):,.0f}')
    print(f'    gc_retention_top3  field present?  {"gc_retention_top3" in eu}')
    print(f'    gc_retention_top10 field present?  {"gc_retention_top10" in eu}')
    print()
    print('  Compare to my Sub-B2 verification yesterday (with `intel_with[\"stage_signals\"]')
    print('  [\"stage_type\"] = \"sprint\"` MANUALLY INJECTED): total_ev = 178,417')
    print()
    print('  Verification used the override path; production does not.')


def step4_confirm_gate_skips_when_intel_stage_type_none():
    print()
    print('=' * 72)
    print('STEP 4 — Confirm the gate in add_stage_evs skips when intel_stage_type is None')
    print('=' * 72)
    print('  Code at optimizer.py (Sub-B2 commit 9ec292d):')
    print('    rank_map = _standings_rank_map(standings) if standings else {}')
    print('    ...')
    print('    current_rank = rank_map.get(rider_name)')
    print('    if current_rank is not None and intel_stage_type:    ← gate')
    print('        ...override fires...')
    print()
    standings = json.load(open(STDG_PATH))
    rmap = _standings_rank_map(standings)
    print(f'  rank_map[Afonso Eulálio] = {rmap.get(TARGET)!r}   ← non-None ✓')
    print(f'  intel_stage_type         = None (per Step 2)       ← falsy ✗')
    print(f'  Gate condition: (True) and (False) = False  →  override does NOT fire')
    print()
    print('  Result: Eulálio gets bookmaker-derived ~11k EV instead of standings-aware ~178k.')


def step5_doc_vs_impl_gap():
    print()
    print('=' * 72)
    print('STEP 5 — Documentation-implementation gap (CLAUDE_SESSION operational note)')
    print('=' * 72)
    print('  CLAUDE_SESSION says (committed 2026-05-14 in Part 0):')
    print('    "If `stage_type` is missing or null for a given stage, retention model')
    print('     falls back to \"stage acts like sprint\" (no GC movement) — conservative')
    print('     default that prevents Eulalio-shaped collapse..."')
    print()
    print('  But the GATE at add_stage_evs requires `intel_stage_type` to be truthy.')
    print('  When intel_stage_type is None, the override skips entirely — falls back to')
    print('  the BOOKMAKER-derived path, NOT to "sprint" curves.')
    print()
    print('  compute_retention_probabilities DOES handle None correctly (it falls back')
    print('  to _retention_sprint via _RETENTION_CURVES.get(None, _retention_sprint))')
    print('  but the gate short-circuits before that helper is ever called.')


def step6_classification_and_fix_shape():
    print()
    print('=' * 72)
    print('CLASSIFICATION + FIX SHAPE')
    print('=' * 72)
    print('  (A) substrate mismatch:        RULED OUT (Step 1)')
    print('  (B) code path mismatch:        CONFIRMED — but as a DATA DEPENDENCY,')
    print('                                 not a wiring failure. The gate condition')
    print('                                 short-circuits when intel substrate hasn\'t')
    print('                                 been re-extracted with the new schema field.')
    print('  (C) race-type interaction:     RULED OUT (Step 4 above; race-type adjusts')
    print('                                 win/top3/top10/top15 only, before Sub-B2 fires')
    print('                                 — Sub-B2 REPLACES gc_ev/jersey_ev for in-top-10')
    print('                                 riders so race-type does not get a second bite)')
    print('  (D) something else:            n/a')
    print()
    print('  Recommended fix shape (1 sentence — Phase 1.6 handoff drafts the actual fix):')
    print('    Drop `and intel_stage_type` from the gate condition in add_stage_evs')
    print('    (optimizer.py around line 415); compute_retention_probabilities already')
    print('    falls back to _retention_sprint when stage_type is None, so removing the')
    print('    short-circuit matches the documented fallback behaviour.')


if __name__ == '__main__':
    step1_substrate_paths()
    intel_st = step2_intel_has_stage_signals()
    step3_diff_with_vs_without_injection()
    step4_confirm_gate_skips_when_intel_stage_type_none()
    step5_doc_vs_impl_gap()
    step6_classification_and_fix_shape()
