"""S17-25 Phase 2 one-shot — backfill stage_N_results.json for Stages 1, 2, 3
with per-rider breakdown fields (sprint_pts, stage_placement, race_placement,
team_bonus, jersey_bonus, gc_bonus, penalty).

Idempotent: re-runs overwrite the same files with the same data. Calls
fetch_stage_results, which now populates the breakdown via the modal-intercept
endpoint. Reports per-rider per-stage V8 sums for verification.

Usage:
    python3 claude/diagnostics/backfill_stage_results.py
"""
import json
import os
import pathlib
import sys
from collections import defaultdict

# Path relative to this script — works from main repo OR a worktree clone.
HERE   = pathlib.Path(__file__).resolve()
ROOT   = HERE.parents[2]                 # claude/diagnostics/X.py → repo root
ENGINE = ROOT / 'claude' / 'engine'

# .env always lives at the canonical repo root (~/Claude/Holdet-v3/.env)
ENV_FILE = pathlib.Path.home() / 'Claude' / 'Holdet-v3' / '.env'
if not ENV_FILE.exists():
    ENV_FILE = ROOT / '.env'   # worktree-local fallback if canonical missing
for line in ENV_FILE.read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1)
        os.environ[k.strip()] = v.strip().strip('"').strip("'")

sys.path.insert(0, str(ENGINE))
from fetch_riders import fetch_stage_results  # noqa: E402

STAGES = [1, 2, 3]


def main():
    aggregated = defaultdict(list)
    for stage in STAGES:
        print(f'\n=========================================')
        print(f'  Backfilling stage {stage}')
        print(f'=========================================')
        result = fetch_stage_results(stage)

        # Per-rider V8: sum of decomposed fields == stage_pts (which is breakdown growth)
        for r in result.get('rider_results', []):
            decomp = (
                r.get('sprint_pts',      0)
                + r.get('stage_placement', 0)
                + r.get('race_placement',  0)
                + r.get('team_bonus',      0)
                + r.get('jersey_bonus',    0)
                + r.get('gc_bonus',        0)
                + r.get('penalty',         0)
            )
            growth = r.get('stage_pts', 0)
            ok = (decomp == growth)
            aggregated[stage].append({
                'name':   r['name'],
                'growth': growth,
                'sum':    decomp,
                'ok':     ok,
            })
        for u in result.get('unmapped_actions', []):
            aggregated['unmapped'].append({**u, 'stage': stage})
        for d in result.get('growth_vs_pricechange_divergences', []):
            aggregated['divergences'].append({**d, 'stage': stage})

    # Final V8 report
    print(f'\n=========================================')
    print(f'  V8 invariant report')
    print(f'=========================================')
    all_ok = True
    for stage in STAGES:
        n = len(aggregated[stage])
        n_ok = sum(1 for r in aggregated[stage] if r['ok'])
        print(f'\nStage {stage}: {n_ok}/{n} riders pass V8 (sum_of_bonuses == growth)')
        for r in aggregated[stage]:
            mark = '✓' if r['ok'] else '✗'
            print(f'  {mark} {r["name"]:<28}  growth={r["growth"]:>+9,}  sum={r["sum"]:>+9,}')
            if not r['ok']:
                all_ok = False

    if aggregated['unmapped']:
        print(f'\n⚠  Unmapped action labels ({len(aggregated["unmapped"])}):')
        for u in aggregated['unmapped']:
            print(f'  {u}')
        all_ok = False
    else:
        print(f'\n✓ Zero unmapped action labels')

    if aggregated['divergences']:
        print(f'\n⚠  growth ≠ priceChange ({len(aggregated["divergences"])}):')
        for d in aggregated['divergences']:
            print(f'  {d["name"]:<28} stage {d["stage"]}  '
                  f'growth={d["growth"]:>+9,}  priceChange={d["priceChange"]:>+9,}  '
                  f'delta={d["delta"]:>+9,}')
    else:
        print(f'\n✓ Zero growth/priceChange divergences')

    print(f'\n{"="*42}')
    print(f'  V8 OVERALL: {"PASS" if all_ok else "FAIL"}')
    print(f'{"="*42}')
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
