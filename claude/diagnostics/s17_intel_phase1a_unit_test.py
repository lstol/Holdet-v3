"""
S17-INTEL Phase 1a unit tests (2026-05-16).

Verifies _derive_expert_stars correctly transforms source_ratings
(per-source-then-per-rider) into expert_stars (per-rider-then-per-source)
with null-for-unrated handling and name-matcher-hardened canonicalisation.

Persisted — re-runnable as schema regression check during Phase 1b/1c +
Phase 3 calibration work.

Run: python3 claude/diagnostics/s17_intel_phase1a_unit_test.py
Exit 0 → all pass.
"""
import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR = os.path.normpath(os.path.join(_THIS_DIR, '..', 'engine'))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from server import _derive_expert_stars


ALL_KNOWN_SOURCES = [
    'tv2_axelgaard', 'tv2_generic', 'feltet', 'inner_ring', 'touretappe',
    'wielerflits', 'indeleiderstrui', 'cyclingnews', 'cyclingstage',
    'total_velo', 'todaycycling', 'cicloweb', 'spaziociclismo',
]

# Synthetic roster — single entry sufficient for canonicalisation test;
# match_rider_name accepts list of dicts with 'name' key + (optional)
# nickname fields. For the bare unit test we use exact names so
# canonicalisation passes through bit-identically.
SYNTHETIC_RIDERS = [
    {'name': 'Jonas Vingegaard'},
    {'name': 'Filippo Ganna'},
    {'name': 'Paul Magnier'},
]


def _assert(label, actual, expected):
    if actual == expected:
        print(f'[PASS] {label}')
        return True
    print(f'[FAIL] {label}')
    print(f'       expected: {expected}')
    print(f'       actual:   {actual}')
    return False


def main():
    results = []

    # ── Test 1 — single source, single rider ──────────────────────────────
    src = [{'source': 'tv2_axelgaard', 'weight': 1.5,
            'ratings': [{'rider': 'Jonas Vingegaard', 'stars': 5}]}]
    out = _derive_expert_stars(src, ALL_KNOWN_SOURCES, SYNTHETIC_RIDERS)
    expected_vingegaard = {s: None for s in ALL_KNOWN_SOURCES}
    expected_vingegaard['tv2_axelgaard'] = 5
    results.append(_assert('Test 1: single source, single rider',
                           out, {'Jonas Vingegaard': expected_vingegaard}))

    # ── Test 2 — multi-source, multi-rider, null-for-unrated ─────────────
    src = [
        {'source': 'tv2_axelgaard', 'weight': 1.5,
         'ratings': [{'rider': 'Jonas Vingegaard', 'stars': 5},
                     {'rider': 'Filippo Ganna', 'stars': 4}]},
        {'source': 'feltet', 'weight': 1.2,
         'ratings': [{'rider': 'Jonas Vingegaard', 'stars': 4}]},
        # cyclingnews has empty ratings — source attempted but no riders rated
        {'source': 'cyclingnews', 'weight': 1.0, 'ratings': []},
    ]
    out = _derive_expert_stars(src, ALL_KNOWN_SOURCES, SYNTHETIC_RIDERS)
    expected_v = {s: None for s in ALL_KNOWN_SOURCES}
    expected_v['tv2_axelgaard'] = 5
    expected_v['feltet'] = 4
    expected_g = {s: None for s in ALL_KNOWN_SOURCES}
    expected_g['tv2_axelgaard'] = 4
    results.append(_assert('Test 2: multi-source / multi-rider / null-for-unrated',
                           out, {'Jonas Vingegaard': expected_v, 'Filippo Ganna': expected_g}))

    # ── Test 3 — stars out of range silently ignored ─────────────────────
    src = [{'source': 'tv2_axelgaard', 'weight': 1.5,
            'ratings': [
                {'rider': 'Jonas Vingegaard', 'stars': 5},
                {'rider': 'Filippo Ganna',   'stars': 7},   # out of [1,5]
                {'rider': 'Paul Magnier',    'stars': 0},   # out of [1,5]
            ]}]
    out = _derive_expert_stars(src, ALL_KNOWN_SOURCES, SYNTHETIC_RIDERS)
    # All three riders surface (mentioned in pass 1) but only Vingegaard's
    # rating is in valid range; others stay None.
    expected_v = {s: None for s in ALL_KNOWN_SOURCES}; expected_v['tv2_axelgaard'] = 5
    expected_g = {s: None for s in ALL_KNOWN_SOURCES}
    expected_m = {s: None for s in ALL_KNOWN_SOURCES}
    results.append(_assert('Test 3: out-of-range stars silently null',
                           out, {'Jonas Vingegaard': expected_v,
                                 'Filippo Ganna':    expected_g,
                                 'Paul Magnier':     expected_m}))

    # ── Test 4 — empty input → empty output ───────────────────────────────
    out = _derive_expert_stars([], ALL_KNOWN_SOURCES, SYNTHETIC_RIDERS)
    results.append(_assert('Test 4: empty input → empty output', out, {}))

    # ── Test 5 — None input tolerated ────────────────────────────────────
    out = _derive_expert_stars(None, ALL_KNOWN_SOURCES, SYNTHETIC_RIDERS)
    results.append(_assert('Test 5: None input → empty output', out, {}))

    # ── Test 6 — unknown source (not in all_known_sources) skipped ───────
    src = [{'source': 'made_up_source', 'weight': 1.0,
            'ratings': [{'rider': 'Jonas Vingegaard', 'stars': 5}]},
           {'source': 'tv2_axelgaard', 'weight': 1.5,
            'ratings': [{'rider': 'Jonas Vingegaard', 'stars': 4}]}]
    out = _derive_expert_stars(src, ALL_KNOWN_SOURCES, SYNTHETIC_RIDERS)
    expected_v = {s: None for s in ALL_KNOWN_SOURCES}
    expected_v['tv2_axelgaard'] = 4
    # made_up_source not in keys → not present in expert_stars[rider]
    results.append(_assert('Test 6: unknown source skipped',
                           out, {'Jonas Vingegaard': expected_v}))

    # ── Test 7 — float stars round to int when integer-valued ────────────
    src = [{'source': 'feltet', 'weight': 1.2,
            'ratings': [{'rider': 'Filippo Ganna', 'stars': 4.0}]}]
    out = _derive_expert_stars(src, ALL_KNOWN_SOURCES, SYNTHETIC_RIDERS)
    # 4.0 → 4 (int)
    assert out['Filippo Ganna']['feltet'] == 4
    assert isinstance(out['Filippo Ganna']['feltet'], int)
    print('[PASS] Test 7: float 4.0 → int 4')
    results.append(True)

    # ── Test 8 — non-integer float preserved as float ────────────────────
    src = [{'source': 'feltet', 'weight': 1.2,
            'ratings': [{'rider': 'Filippo Ganna', 'stars': 4.5}]}]
    out = _derive_expert_stars(src, ALL_KNOWN_SOURCES, SYNTHETIC_RIDERS)
    assert out['Filippo Ganna']['feltet'] == 4.5
    print('[PASS] Test 8: float 4.5 preserved')
    results.append(True)

    # ── Test 9 — empty roster falls back to raw name ─────────────────────
    src = [{'source': 'tv2_axelgaard', 'weight': 1.5,
            'ratings': [{'rider': 'Unknown Rider Name', 'stars': 5}]}]
    out = _derive_expert_stars(src, ALL_KNOWN_SOURCES, [])
    assert 'Unknown Rider Name' in out
    assert out['Unknown Rider Name']['tv2_axelgaard'] == 5
    print('[PASS] Test 9: empty roster → raw name fallback')
    results.append(True)

    passed = sum(1 for r in results if r)
    total = len(results)
    print(f'\n{passed}/{total} passed.')
    sys.exit(0 if passed == total else 1)


if __name__ == '__main__':
    main()
