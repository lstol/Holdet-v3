"""
Sub-B2-followup unit tests (2026-05-15).

Verifies that `_retention_itt` strong-TT classifier under composed semantic-OR
shape (`rider_type in ('TTT Spec.', 'GC-Climber') or tt_affinity >= 0.7`)
produces the correct retention curve for five canonical substrate cases:

  Test 1 — Hybrid-TT (Ganna-shape):   Sprinter rider_type + tt=0.96 → strong-TT
  Test 2 — GC-Climber preservation:    GC-Climber + tt=0.48        → strong-TT (REGRESSION GUARD)
  Test 3 — Non-strong-TT pure climber: All-rounder + tt=0.45       → non-strong-TT
  Test 4 — TTT Spec. with low tt:      TTT Spec. + tt=0.30          → strong-TT
  Test 5 — Top-3 branching:            Hybrid-TT + current_rank=2  → top-3 strong-TT row

Persisted (not throwaway) — reusable when Stage 10 substrate becomes operational
or future ITT stages surface real hybrid-TT cases in GC top-10. Architectural
inertness of the patch on current Giro 2026 substrate (Stage 8 not ITT;
Ganna outside GC top-10 going into Stage 10) means runtime verification via
`/run-optimizer` cannot exercise the fix; these tests are the canonical proof.

Run with: python3 claude/diagnostics/sub_b2_followup_unit_test.py
Exit code 0 → all 5 pass. Non-zero → see failure detail.
"""
import os
import sys

# Make optimizer importable when running from repo root.
_THIS_DIR    = os.path.dirname(os.path.abspath(__file__))
_ENGINE_DIR  = os.path.normpath(os.path.join(_THIS_DIR, '..', 'engine'))
if _ENGINE_DIR not in sys.path:
    sys.path.insert(0, _ENGINE_DIR)

from optimizer import _retention_itt, compute_retention_probabilities


def _assert_curve(label, got, expected, tolerance=1e-9):
    """Compare two (p_top3, p_top10) tuples within tolerance. Returns (ok, msg)."""
    if got == expected or (
        abs(got[0] - expected[0]) <= tolerance and
        abs(got[1] - expected[1]) <= tolerance
    ):
        return True, f'[PASS] {label}: got={got}  expected={expected}'
    return False, f'[FAIL] {label}: got={got}  expected={expected}'


# Expected curves per _retention_itt source (verify against optimizer.py):
#   Strong-TT, rank ≤ 3:   (0.85, 0.90)
#   Strong-TT, rank 4–10:  (0.30, 0.90)   ← p_top3=0.30, p_top10=0.90
#   Non-strong, rank ≤ 3:  (0.40, max(0.20, 0.70 - 0.06*rank))
#   Non-strong, rank > 3:  (0.0,  max(0.20, 0.70 - 0.06*rank))
#
# IMPORTANT: re-read source if curves below diverge from current shape.

STRONG_TOP3   = (0.85, 0.90)
STRONG_TOP10  = (0.30, 0.90)   # rank 4-10 strong: p_top3=0.30, p_top10=0.90


def _non_strong_top3(rank):
    return (0.40, max(0.20, 0.70 - 0.06 * rank))


def _non_strong_top10(rank):
    return (0.0, max(0.20, 0.70 - 0.06 * rank))


def main():
    results = []

    # ── Test 1 — Hybrid-TT Ganna-shape ────────────────────────────────────
    # Ganna's actual values from riders.json: sp=0.72, cl=0.42, tt=0.96, mx=0.52.
    # _python_rider_type returns 'Sprinter' (sp >= 0.72 priority fires first).
    # Pre-fix this would fail strong-TT check (Sprinter not in {'TTT Spec.','GC-Climber'}).
    # Post-fix: tt=0.96 >= 0.7 fires second route → strong-TT.
    ganna_rider = {
        'name': 'Filippo Ganna',
        'terrain_affinity': {'sprint': 0.72, 'climbing': 0.42, 'time_trial': 0.96, 'mixed': 0.52},
    }
    got = _retention_itt(current_rank=5, rider_type='Sprinter', rider=ganna_rider)
    results.append(_assert_curve('Test 1 (Ganna hybrid-TT)', got, STRONG_TOP10))

    # ── Test 2 — GC-Climber preservation (Ciccone-shape, REGRESSION GUARD) ─
    # Ciccone's actual values: sp=0.30, cl=0.76, tt=0.48, mx=0.58.
    # _python_rider_type returns 'GC-Climber' (cl >= 0.72 fires after sp < 0.72).
    # tt=0.48 < 0.7, so new route does NOT fire. But original 'GC-Climber'
    # route DOES fire → strong-TT preserved.
    # This is the canonical guard against the literal-replacement shape that
    # would have regressed Ciccone/Bernal.
    ciccone_rider = {
        'name': 'Giulio Ciccone',
        'terrain_affinity': {'sprint': 0.30, 'climbing': 0.76, 'time_trial': 0.48, 'mixed': 0.58},
    }
    got = _retention_itt(current_rank=6, rider_type='GC-Climber', rider=ciccone_rider)
    results.append(_assert_curve('Test 2 (GC-Climber preservation, regression guard)', got, STRONG_TOP10))

    # ── Test 3 — Pure climber, low tt, non-strong-TT path ─────────────────
    # Substrate-realistic shape: high climbing, low everything else.
    # Not GC-Climber (we use 'All-rounder' rider_type), tt < 0.7. Both routes miss.
    pure_climber = {
        'name': 'synthetic-pure-climber',
        'terrain_affinity': {'sprint': 0.20, 'climbing': 0.86, 'time_trial': 0.45, 'mixed': 0.55},
    }
    got = _retention_itt(current_rank=8, rider_type='All-rounder', rider=pure_climber)
    results.append(_assert_curve('Test 3 (pure climber non-strong)', got, _non_strong_top10(8)))

    # ── Test 4 — TTT Spec. preservation with synthetic low tt ─────────────
    # Synthetic case: rider_type='TTT Spec.' with tt=0.30 (improbable in
    # practice — TTT Spec. classification requires tt >= 0.65 — but isolates
    # the rider_type route). Original 'TTT Spec.' route should still fire.
    ttt_spec_low_tt = {
        'name': 'synthetic-ttt-spec',
        'terrain_affinity': {'sprint': 0.10, 'climbing': 0.20, 'time_trial': 0.30, 'mixed': 0.20},
    }
    got = _retention_itt(current_rank=4, rider_type='TTT Spec.', rider=ttt_spec_low_tt)
    results.append(_assert_curve('Test 4 (TTT Spec. preservation, low tt)', got, STRONG_TOP10))

    # ── Test 5 — Top-3 branching (hybrid-TT at rank 2) ────────────────────
    # Confirms the top-3 vs top-10 strong-TT branching is preserved.
    got = _retention_itt(current_rank=2, rider_type='Sprinter', rider=ganna_rider)
    results.append(_assert_curve('Test 5 (hybrid-TT top-3 branch)', got, STRONG_TOP3))

    # ── Bonus end-to-end via compute_retention_probabilities ──────────────
    # Verify the dispatcher threads `rider` through correctly.
    got = compute_retention_probabilities(
        current_rank=5, rider_type='Sprinter', stage_type='itt', rider=ganna_rider,
    )
    results.append(_assert_curve('Bonus (dispatcher threads rider through)', got, STRONG_TOP10))

    # ── Bonus regression check via dispatcher: rider=None still works ─────
    # When rider is None (e.g., legacy caller), _retention_itt falls back to
    # the original rider_type-based check exactly. TT Spec. → strong-TT.
    got = compute_retention_probabilities(
        current_rank=5, rider_type='TTT Spec.', stage_type='itt', rider=None,
    )
    results.append(_assert_curve('Bonus (rider=None backward-compat for TTT Spec.)', got, STRONG_TOP10))

    print('\n'.join(msg for _, msg in results))
    failures = [m for ok, m in results if not ok]
    print()
    print(f'{len(results) - len(failures)}/{len(results)} passed.')
    if failures:
        print('\nFAILURES:')
        for f in failures: print(f'  {f}')
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
