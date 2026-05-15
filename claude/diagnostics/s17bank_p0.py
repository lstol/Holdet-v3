"""S17-BANK Phase 0 diagnostic — Bug A + Bug B classification.

Origin: Stage 6 prep 2026-05-14, three optimizer cards anchored at
49.62-49.74M of 50.00M cap while dashboard "How it unfolded" shows
Bank: 53.001M kr. Read-only diagnostic locates the discrepancy.

Findings (2026-05-15):
  Bug A: shape (c) snapshot-read variant. server.py:609 reads
         bank_balance from `stage_{N}_holdet.json` which does NOT exist
         for upcoming stages (Stage 6 not raced yet → no snapshot).
         Falls back to 50_000_000 default. Live bank lives in
         `stage_{N-1}_results.json` (the same source the dashboard
         "How it unfolded" panel uses via /stage-results endpoint).
         Fix shape: change server.py:607 to read from
         `stage_{N-1}_results.json`.

  Bug B: confirmed. optimizer.py:712-724 `is_valid(team, budget)`
         checks only `sum(team_prices) > budget` — no transfer-fee
         subtraction. is_valid doesn't receive current_team so it
         cannot compute fees. compute_transfer_cost (optimizer.py:782)
         exists and feeds the EV objective, but isn't called from
         is_valid. 8-transfer teams can pass validation while
         carrying ~400-500k of fees that aren't deducted from budget
         cap. Bug B compounds Bug A.
"""
import json
import os
import sys

REPO = '/Users/lassestoltenberg/Claude/Holdet-v3/.claude/worktrees/epic-hofstadter-ab23f7'
CANON = '/Users/lassestoltenberg/Claude/Holdet-v3'

SNAPSHOT_DIR = os.path.join(CANON, 'shared/data/snapshots')


def step1_bug_a_codepath():
    print('=' * 72)
    print('STEP 1 — Bug A code path (server.py /run-optimizer → optimizer.py is_valid)')
    print('=' * 72)
    server_py = open(os.path.join(REPO, 'claude/engine/server.py')).read()
    opt_py    = open(os.path.join(REPO, 'claude/engine/optimizer.py')).read()
    # Bug A line
    for i, line in enumerate(server_py.splitlines(), 1):
        if 'snapshot.get(' in line and 'bank_balance' in line:
            print(f'  server.py:{i}  {line.strip()}')
    print()
    print(f'  optimizer.py BUDGET constant (line 82): {next(l for l in opt_py.splitlines() if l.startswith("BUDGET = "))!r}')
    print(f'  optimizer.py is_valid (line 712): {next(l for l in opt_py.splitlines() if l.startswith("def is_valid"))!r}')


def step2_bug_a_snapshot_state():
    print()
    print('=' * 72)
    print('STEP 2 — Bug A snapshot state (live bank source)')
    print('=' * 72)
    s6_holdet = os.path.join(SNAPSHOT_DIR, 'stage_6_holdet.json')
    s5_holdet = os.path.join(SNAPSHOT_DIR, 'stage_5_holdet.json')
    s5_results = os.path.join(SNAPSHOT_DIR, 'stage_5_results.json')

    print(f'  stage_6_holdet.json (target-stage snapshot, what server reads): '
          f'{"EXISTS" if os.path.exists(s6_holdet) else "DOES NOT EXIST"}')
    if not os.path.exists(s6_holdet):
        print(f'    → server.py:609 falls back to int(snapshot.get("bank_balance", 50_000_000)) = 50_000_000')
    if os.path.exists(s5_holdet):
        d = json.load(open(s5_holdet))
        print(f'  stage_5_holdet.json (previous-stage post-race snapshot): exists')
        print(f'    bank_balance: {d.get("bank_balance")}')
    if os.path.exists(s5_results):
        d = json.load(open(s5_results))
        print(f'  stage_5_results.json (where dashboard "How it unfolded" reads from): exists')
        print(f'    bank_balance: {d.get("bank_balance")}')
        print(f'    → This is the live bank the optimizer SHOULD be reading.')


def step3_bug_b_codepath():
    print()
    print('=' * 72)
    print('STEP 3 — Bug B code path (is_valid budget check)')
    print('=' * 72)
    opt_py = open(os.path.join(REPO, 'claude/engine/optimizer.py')).read().splitlines()
    # Extract is_valid body
    for i, line in enumerate(opt_py, 1):
        if line.startswith('def is_valid('):
            print(f'  optimizer.py:{i}-{i+12}')
            for j in range(i, min(i+13, len(opt_py)+1)):
                print(f'    {opt_py[j-1]}')
            break
    print()
    print('  Observation: line 716 `if sum(r.get("price", 0) for r in team) > budget:`')
    print('               compares team_prices to budget. NO transfer fee subtraction.')
    print('               is_valid does NOT receive current_team — cannot compute fees.')
    print()
    # compute_transfer_cost
    for i, line in enumerate(opt_py, 1):
        if line.startswith('def compute_transfer_cost('):
            print(f'  optimizer.py:{i} compute_transfer_cost(current_team, target_team, ...)')
            print(f'    Exists separately. Feeds EV objective (look_obj = ev − tc_current − cost_n1 − 0.7×cost_n2).')
            print(f'    Not called from is_valid.')
            break


def step4_curl_evidence():
    print()
    print('=' * 72)
    print('STEP 4 — curl evidence: what budget does /run-optimizer actually use?')
    print('=' * 72)
    import subprocess
    payload = '{"stage":6,"sliders":{"n1":{"bunch_sprint":80,"reduced_sprint":20,"gc":0,"breakaway":0},"n2":{"bunch_sprint":0,"reduced_sprint":20,"gc":80,"breakaway":0},"n3":{"bunch_sprint":0,"reduced_sprint":0,"gc":0,"breakaway":100}},"force_in":[],"force_out":[],"use_race_type_adjustment":false}'
    try:
        out = subprocess.check_output(
            ['curl', '-s', '-X', 'POST', 'http://localhost:5050/run-optimizer',
             '-H', 'Content-Type: application/json', '-d', payload],
            text=True, timeout=120,
        )
        d = json.loads(out)
        print(f'  /run-optimizer response.budget = {d.get("budget"):,}')
        print(f'  matches BUDGET fallback default (50,000,000)? {d.get("budget") == 50_000_000}')
        print(f'  matches stage_5_results bank (53,001,243)?    {d.get("budget") == 53_001_243}')
        print()
        for t in d.get('teams', []):
            print(f'  {t["strategy"]:<12} total_price={t.get("total_price",0):>12,}  '
                  f'budget_left={d.get("budget",0) - t.get("total_price",0):>10,}')
    except Exception as e:
        print(f'  curl failed: {e}')


def step5_summary():
    print()
    print('=' * 72)
    print('CLASSIFICATION + FIX SHAPE')
    print('=' * 72)
    print('  Bug A: shape (c) snapshot-read variant. server.py:609 reads bank_balance')
    print('         from `stage_{N}_holdet.json` which doesn\'t exist pre-stage. Falls')
    print('         back to 50M default. Live bank is in `stage_{N-1}_results.json`.')
    print('         Fix shape (1 sentence): change server.py:607-609 to read from')
    print('         `stage_{N-1}_results.json` — same source dashboard\'s /stage-results')
    print('         endpoint already uses for "How it unfolded".')
    print()
    print('  Bug B: confirmed. is_valid (optimizer.py:712-724) checks only team prices')
    print('         vs budget, no transfer-fee subtraction.')
    print('         Fix shape (1 sentence): either pass current_team to is_valid so it')
    print('         can compute fees, OR pre-subtract estimated fees from budget')
    print('         before passing to is_valid; ~5 callsites of is_valid to consider.')


if __name__ == '__main__':
    step1_bug_a_codepath()
    step2_bug_a_snapshot_state()
    step3_bug_b_codepath()
    step4_curl_evidence()
    step5_summary()
