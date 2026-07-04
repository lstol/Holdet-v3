"""
TdF-MIGRATE Phase 1 — Tour substrate smoke test (2026-07-04).

Six-question read-only diagnostic against Tourspillet 2026 (cartridge 618).
Does NOT modify fetch_riders.py, optimizer.py, server.py, expert_sources.yaml,
riders.json, or any shared/data file. Outputs only under
claude/diagnostics/tdf_substrate_smoke_output/.

Q1: Does fetch_riders_api work against cartridge 618 with zero code changes?
Q2: Schema diff Giro vs Tour (rider JSON fields).
Q3: Rider count sanity vs 184 startlist.
Q4: Scoring/rules endpoint reachable + constants match?
Q5: Stage 1 TTT scoring shape per Holdet rules.
Q6: fetch_team_as_dict URL shape for Tour slug.

Stop conditions per handoff:
  - Auth error (401/403) → report and stop.
  - HTML instead of JSON → report headers and stop.
  - Cartridge 618 returns Giro data or empty riders → report and stop.
  - Any mutation to a shared file → stop and re-scope.
  - >45 min elapsed → return partial findings.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO = Path('/Users/lassestoltenberg/Claude/Holdet-v3')
OUT_DIR = REPO / 'claude' / 'diagnostics' / 'tdf_substrate_smoke_output'
OUT_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(REPO / '.env', override=True)

# Env inputs (all present per pre-flight check).
COOKIE           = os.getenv('HOLDET_COOKIE', '')
GAME_ID_GIRO     = os.getenv('HOLDET_GAME_ID_GIRO', '612')
GAME_ID_TDF      = '618'  # per handoff — do NOT read from env; verify against operator's assertion
CARTRIDGE_GIRO   = os.getenv('HOLDET_CARTRIDGE', 'giro-d-italia-2026')
CARTRIDGE_TDF    = os.getenv('HOLDET_CARTRIDGE_TDF', 'tour-de-france-2026')  # operator-set; verify
FANTASY_TEAM_ID  = os.getenv('HOLDET_FANTASY_TEAM_ID', '')

BASE_URL = 'https://nexus-app-fantasy-fargate.holdet.dk'
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36')

report = {
    'diagnostic': 'TdF-MIGRATE Phase 1 smoke test',
    'started_at': datetime.now(timezone.utc).isoformat(),
    'run_git_head': None,
    'env_shape': {
        'HOLDET_COOKIE_len': len(COOKIE),
        'HOLDET_GAME_ID_GIRO': GAME_ID_GIRO,
        'HOLDET_GAME_ID_TDF (asserted)': GAME_ID_TDF,
        'HOLDET_CARTRIDGE (Giro)': CARTRIDGE_GIRO,
        'HOLDET_CARTRIDGE_TDF': CARTRIDGE_TDF,
        'HOLDET_FANTASY_TEAM_ID_present': bool(FANTASY_TEAM_ID),
    },
    'q1_riders_api': {},
    'q2_schema_diff': {},
    'q3_rider_count': {},
    'q4_rules_endpoint': {},
    'q5_ttt_scoring': {},
    'q6_team_url_shape': {},
    'stop_condition_triggered': None,
    'notes': [],
}

# Capture git HEAD for substrate-time-skew SHA pair
try:
    import subprocess
    report['run_git_head'] = subprocess.check_output(
        ['git', '-C', str(REPO), 'rev-parse', 'HEAD'],
        text=True,
    ).strip()
except Exception as e:
    report['notes'].append(f'git HEAD capture failed: {e}')


# ── Auth pre-check ────────────────────────────────────────────────────────────
if not COOKIE:
    print('FATAL: HOLDET_COOKIE not present in env. Cannot proceed.')
    report['stop_condition_triggered'] = 'HOLDET_COOKIE missing'
    (OUT_DIR / 'tdf_substrate_smoke_report.json').write_text(json.dumps(report, indent=2, default=str))
    sys.exit(1)

if len(COOKIE) < 50:
    print(f'WARN: HOLDET_COOKIE only {len(COOKIE)} chars — typical values are 200+; may fail auth.')
    report['notes'].append(f'HOLDET_COOKIE unusually short ({len(COOKIE)} chars). Real Holdet cookies are typically 200+ chars.')

HEADERS = {
    'Cookie': COOKIE,
    'User-Agent': UA,
    'Accept': 'application/json, text/plain, */*',
}


def _try_get(url, timeout=15):
    """Return (status_code, content_type, body, headers) — never raises."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        return r.status_code, r.headers.get('content-type', ''), r.text, dict(r.headers)
    except requests.exceptions.RequestException as e:
        return 0, '', str(e), {}


def _sha16(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8', errors='replace')).hexdigest()[:16]


# ── Q1 — Rider fetch against cartridge 618 ────────────────────────────────────
print('=' * 78)
print('Q1 — fetch /api/games/618/players (Tour cartridge)')
print('=' * 78)

url_q1 = f'{BASE_URL}/api/games/{GAME_ID_TDF}/players'
status, ctype, body, resp_headers = _try_get(url_q1)
report['q1_riders_api'] = {
    'url': url_q1,
    'status': status,
    'content_type': ctype,
    'body_len': len(body),
    'body_sha16': _sha16(body),
}
print(f'  URL: {url_q1}')
print(f'  HTTP {status}  content-type={ctype}  body_len={len(body)}')

if status in (401, 403):
    print(f'  STOP: auth error {status}')
    report['stop_condition_triggered'] = f'Q1 auth error {status}'
    report['q1_riders_api']['response_headers'] = {k: v for k, v in resp_headers.items() if k.lower() not in ('set-cookie', 'authorization')}
    (OUT_DIR / 'tdf_substrate_smoke_report.json').write_text(json.dumps(report, indent=2, default=str))
    sys.exit(0)

if status == 200 and 'html' in ctype.lower() and 'json' not in ctype.lower():
    print('  STOP: returned HTML instead of JSON')
    report['stop_condition_triggered'] = 'Q1 returned HTML (bot detection?)'
    report['q1_riders_api']['response_headers'] = {k: v for k, v in resp_headers.items() if k.lower() not in ('set-cookie',)}
    (OUT_DIR / 'tdf_substrate_smoke_report.json').write_text(json.dumps(report, indent=2, default=str))
    sys.exit(0)

tour_data = None
if status == 200:
    try:
        tour_data = json.loads(body)
    except json.JSONDecodeError as e:
        report['q1_riders_api']['parse_error'] = str(e)
        print(f'  JSON parse failed: {e}')
        report['stop_condition_triggered'] = 'Q1 JSON parse failed'
        (OUT_DIR / 'tdf_substrate_smoke_report.json').write_text(json.dumps(report, indent=2, default=str))
        sys.exit(0)

if not tour_data:
    print('  No data — stopping.')
    (OUT_DIR / 'tdf_substrate_smoke_report.json').write_text(json.dumps(report, indent=2, default=str))
    sys.exit(0)

# Parse using same logic as fetch_riders_api
persons = tour_data.get('_embedded', {}).get('persons', {})
teams = tour_data.get('_embedded', {}).get('teams', {})
items = tour_data.get('items', [])
report['q1_riders_api']['items_count'] = len(items)
report['q1_riders_api']['persons_count'] = len(persons)
report['q1_riders_api']['teams_count'] = len(teams)
report['q1_riders_api']['top_level_keys'] = sorted(tour_data.keys())
report['q1_riders_api']['embedded_keys'] = sorted(tour_data.get('_embedded', {}).keys())

# Assemble first 3 riders (fetch_riders_api-shape output)
tour_riders_parsed = []
for item in items[:3]:
    pid = str(item.get('personId', ''))
    tid = str(item.get('teamId', ''))
    person = persons.get(pid, {})
    team = teams.get(tid, {})
    tour_riders_parsed.append({
        'holdet_id': item.get('id'),
        'name': f"{person.get('firstName', '')} {person.get('lastName', '')}".strip(),
        'team': team.get('name', 'Unknown'),
        'team_abbr': team.get('abbreviation', '???'),
        'startPrice': item.get('startPrice', item.get('price', 0)),
        'price': item.get('price'),
        'points': item.get('points') or 0,
        'isOut': item.get('isOut', False),
        'isInjured': item.get('isInjured', False),
        'isEliminated': item.get('isEliminated', False),
        'captainPopularity': item.get('captainPopularity') or 0.0,
        'owners': item.get('owners') or 0,
    })
report['q1_riders_api']['first_3_riders_parsed'] = tour_riders_parsed
if items:
    report['q1_riders_api']['first_item_raw'] = items[0]

print(f'  items: {len(items)}  persons: {len(persons)}  teams: {len(teams)}')
if items:
    print(f'  First rider parsed: {tour_riders_parsed[0]["name"] if tour_riders_parsed else "?"}')

# Sanity: are any of the returned names actually Giro riders?
if items:
    giro_smell = any(
        'italia' in str(tour_data).lower()[:2000] or 'giro' in str(tour_data).lower()[:2000]
        for _ in [1]
    )
    report['q1_riders_api']['possibly_giro_data_flag'] = giro_smell


# ── Q2 — Schema diff Giro vs Tour ─────────────────────────────────────────────
print()
print('=' * 78)
print('Q2 — Schema diff: Giro rider shape vs Tour rider shape')
print('=' * 78)

url_giro = f'{BASE_URL}/api/games/{GAME_ID_GIRO}/players'
status_g, ctype_g, body_g, _ = _try_get(url_giro)
giro_data = None
if status_g == 200:
    try:
        giro_data = json.loads(body_g)
    except json.JSONDecodeError:
        pass

report['q2_schema_diff']['giro_url'] = url_giro
report['q2_schema_diff']['giro_status'] = status_g
report['q2_schema_diff']['giro_items_count'] = len(giro_data.get('items', [])) if giro_data else None
report['q2_schema_diff']['tour_items_count'] = len(items)

if giro_data and items:
    # Field-level diff on item, person, team
    def _keys(d): return set(d.keys()) if isinstance(d, dict) else set()

    giro_item_keys = _keys(giro_data['items'][0]) if giro_data['items'] else set()
    tour_item_keys = _keys(items[0]) if items else set()
    giro_persons = giro_data.get('_embedded', {}).get('persons', {})
    tour_persons = persons
    giro_pkeys = _keys(next(iter(giro_persons.values()))) if giro_persons else set()
    tour_pkeys = _keys(next(iter(tour_persons.values()))) if tour_persons else set()
    giro_teams = giro_data.get('_embedded', {}).get('teams', {})
    tour_teams = teams
    giro_tkeys = _keys(next(iter(giro_teams.values()))) if giro_teams else set()
    tour_tkeys = _keys(next(iter(tour_teams.values()))) if tour_teams else set()

    def _diff(a, b, label_a, label_b):
        return {
            f'only_in_{label_a}': sorted(a - b),
            f'only_in_{label_b}': sorted(b - a),
            'shared': sorted(a & b),
        }

    report['q2_schema_diff']['item_fields'] = _diff(giro_item_keys, tour_item_keys, 'giro', 'tour')
    report['q2_schema_diff']['person_fields'] = _diff(giro_pkeys, tour_pkeys, 'giro', 'tour')
    report['q2_schema_diff']['team_fields'] = _diff(giro_tkeys, tour_tkeys, 'giro', 'tour')

    # Type-diff: same field name, different Python type
    def _type_diff(a_dict, b_dict, common):
        out = {}
        for k in common:
            ta, tb = type(a_dict.get(k)).__name__, type(b_dict.get(k)).__name__
            if ta != tb:
                out[k] = {'giro_type': ta, 'tour_type': tb, 'giro_sample': a_dict.get(k), 'tour_sample': b_dict.get(k)}
        return out

    common_item = giro_item_keys & tour_item_keys
    report['q2_schema_diff']['item_type_drift'] = _type_diff(giro_data['items'][0], items[0], common_item)

    # Downstream consumer check: what fields does fetch_riders_api / build_probabilities need?
    fetch_needs = {'id', 'personId', 'teamId', 'startPrice', 'price', 'points', 'isOut', 'isInjured', 'isEliminated', 'captainPopularity', 'owners'}
    person_needs = {'firstName', 'lastName'}
    team_needs = {'name', 'abbreviation'}
    report['q2_schema_diff']['fetch_riders_needs'] = {
        'item_needs': sorted(fetch_needs),
        'missing_from_tour_item': sorted(fetch_needs - tour_item_keys),
        'person_needs': sorted(person_needs),
        'missing_from_tour_person': sorted(person_needs - tour_pkeys),
        'team_needs': sorted(team_needs),
        'missing_from_tour_team': sorted(team_needs - tour_tkeys),
    }
    print(f"  Giro item fields: {sorted(giro_item_keys)}")
    print(f"  Tour item fields: {sorted(tour_item_keys)}")
    print(f"  Item fields only in Giro: {sorted(giro_item_keys - tour_item_keys)}")
    print(f"  Item fields only in Tour: {sorted(tour_item_keys - giro_item_keys)}")
    print(f"  Missing from Tour item that fetch_riders_api needs: {sorted(fetch_needs - tour_item_keys)}")

# Also compare against local Giro riders.json
riders_json_path = REPO / 'shared' / 'data' / 'riders' / 'giro_2026' / 'riders.json'
if riders_json_path.exists():
    try:
        rjson = json.loads(riders_json_path.read_text())
        local_riders = rjson.get('riders', [])
        if local_riders:
            local_keys = set(local_riders[0].keys())
            report['q2_schema_diff']['local_riders_json_fields'] = sorted(local_keys)
            report['q2_schema_diff']['local_riders_count'] = len(local_riders)
            report['q2_schema_diff']['local_terrain_affinity_present'] = 'terrain_affinity' in local_keys
    except Exception as e:
        report['q2_schema_diff']['local_riders_json_error'] = str(e)


# ── Q3 — Rider count sanity ───────────────────────────────────────────────────
print()
print('=' * 78)
print('Q3 — Rider count sanity (expected ~184 for Tour startlist)')
print('=' * 78)

tour_count = len(items)
report['q3_rider_count'] = {
    'tour_items_count': tour_count,
    'expected_lower': 170,
    'expected_upper': 200,
    'expected_exact_startlist': 184,
    'flag': 'OUT_OF_RANGE' if (tour_count < 170 or tour_count > 200) else 'IN_RANGE',
    'giro_items_for_reference': len(giro_data.get('items', [])) if giro_data else None,
}
print(f'  Tour riders returned: {tour_count}')
print(f'  Expected: 184 (23 teams × 8); tolerance [170, 200]')
print(f'  Flag: {report["q3_rider_count"]["flag"]}')

# Team count sanity
tour_team_count = len(teams)
report['q3_rider_count']['tour_team_count'] = tour_team_count
report['q3_rider_count']['expected_team_count'] = 23
print(f'  Tour teams returned: {tour_team_count}  (expected 23)')


# ── Q4 — Scoring/rules endpoint + constants ───────────────────────────────────
print()
print('=' * 78)
print('Q4 — Scoring/rules endpoint + Giro constants comparison')
print('=' * 78)

# fetch_riders.py does NOT query rules metadata endpoint. Check API for game
# object which may embed scoring info.
url_game = f'{BASE_URL}/api/games/{GAME_ID_TDF}'
status_gm, ctype_gm, body_gm, _ = _try_get(url_game)
report['q4_rules_endpoint']['game_url'] = url_game
report['q4_rules_endpoint']['game_status'] = status_gm
report['q4_rules_endpoint']['game_content_type'] = ctype_gm
if status_gm == 200:
    try:
        game_obj = json.loads(body_gm)
        report['q4_rules_endpoint']['game_top_level_keys'] = sorted(game_obj.keys())
        # Look for anything scoring-related
        scoring_keys = [k for k in game_obj if any(hint in k.lower() for hint in ('rule', 'point', 'score', 'bonus', 'transfer', 'budget'))]
        report['q4_rules_endpoint']['scoring_hint_keys'] = scoring_keys
        for k in scoring_keys:
            report['q4_rules_endpoint'][f'game.{k}'] = game_obj.get(k)
        # Common fields: name, description, ruleId, ruleSet
        for k in ('name', 'description', 'ruleSetId', 'ruleId', 'gameType', 'ruleSet', 'rules'):
            if k in game_obj:
                val = game_obj[k]
                report['q4_rules_endpoint'][f'game.{k}'] = val if not isinstance(val, (dict, list)) or len(str(val)) < 500 else f'<{type(val).__name__} truncated>'
        print(f'  Game object keys: {sorted(game_obj.keys())}')
        if scoring_keys:
            print(f'  Scoring-related keys: {scoring_keys}')
    except json.JSONDecodeError as e:
        report['q4_rules_endpoint']['parse_error'] = str(e)

# Compare with Giro game object
url_game_g = f'{BASE_URL}/api/games/{GAME_ID_GIRO}'
status_gmg, ctype_gmg, body_gmg, _ = _try_get(url_game_g)
if status_gmg == 200:
    try:
        game_obj_g = json.loads(body_gmg)
        for k in ('name', 'ruleSetId', 'ruleId', 'gameType'):
            if k in game_obj_g:
                report['q4_rules_endpoint'][f'giro_game.{k}'] = game_obj_g[k]
    except json.JSONDecodeError:
        pass

# Optimizer's hardcoded Giro constants
report['q4_rules_endpoint']['optimizer_giro_constants'] = {
    'DEPTH_BONUS': {'0': 0, '1': 4000, '2': 8000, '3': 15000, '4': 35000, '5': 65000, '6': 120000, '7': 220000, '8': 400000},
    'POINT_VALUE': 3000,
    'TRANSFER_COST_RATE': 0.01,
    'source_file': 'claude/engine/optimizer.py:92, :117, :824',
}


# ── Q5 — Stage 1 TTT scoring — probe rules page ───────────────────────────────
print()
print('=' * 78)
print('Q5 — Stage 1 TTT scoring shape (Tour Stage 1 novel format)')
print('=' * 78)

# Probe public rules pages. No auth needed for these.
# Try both cartridge slugs for the game-rules page.
candidate_rules_urls = [
    f'https://holdet.dk/da/{CARTRIDGE_TDF}',
    f'https://holdet.dk/da/{CARTRIDGE_TDF}/regler',
    f'https://holdet.dk/da/{CARTRIDGE_TDF}/rules',
    f'https://holdet.dk/{CARTRIDGE_TDF}',
]
q5_probes = []
for u in candidate_rules_urls:
    s, c, b, _ = _try_get(u)
    entry = {'url': u, 'status': s, 'content_type': c, 'body_len': len(b), 'body_sha16': _sha16(b)}
    if s == 200 and 'html' in c.lower():
        # Look for TTT / holdtidskørsel / individual mentions
        b_lower = b.lower()
        entry['ttt_signal'] = {
            'contains_holdtidskoersel': 'holdtidskør' in b_lower,
            'contains_ttt': 'ttt' in b_lower,
            'contains_stage_1': ('etape 1' in b_lower or 'stage 1' in b_lower),
            'contains_individual_time': ('individuel tid' in b_lower or 'individual time' in b_lower),
            'contains_time_trial': ('tidskør' in b_lower or 'time trial' in b_lower),
        }
        # Try to find <title> and <h1>s
        title_m = re.search(r'<title[^>]*>(.*?)</title>', b, re.DOTALL | re.IGNORECASE)
        h1s = re.findall(r'<h1[^>]*>(.*?)</h1>', b, re.DOTALL | re.IGNORECASE)
        entry['title'] = title_m.group(1).strip()[:200] if title_m else None
        entry['h1s'] = [re.sub(r'<[^>]+>', '', h).strip()[:200] for h in h1s[:3]]
    q5_probes.append(entry)
    print(f"  {u}  HTTP {s}  {c[:40]}  {len(b)}b")
    if s == 200 and 'html' in c.lower() and entry.get('ttt_signal', {}).get('contains_holdtidskoersel'):
        print('    → contains "holdtidskør" (TTT) mentions')

report['q5_ttt_scoring']['rules_page_probes'] = q5_probes
report['q5_ttt_scoring']['note'] = (
    'Optimizer currently has no TTT-specific scoring path. simulate_stage/'
    'add_stage_evs treat stage as ITT-shape if sprint_type is unusual; '
    'sprint_type=A (regular sprint) uses SPRINT_POINTS_FINAL. Stage 1 Tour '
    'is TTT (novel format) — Holdet may score individually per rider even '
    'in TTT context. No optimizer path for this today.'
)


# ── Q6 — fetch_team_as_dict URL shape ─────────────────────────────────────────
print()
print('=' * 78)
print('Q6 — Own-team fetch URL shape for Tour cartridge')
print('=' * 78)

# Probe just STRUCTURAL — do not fetch anyone's team; use fantasy_team_id if
# present. Only structural verification of URL response shape, not team data.
if FANTASY_TEAM_ID:
    slug_candidates = [
        CARTRIDGE_TDF,
        'tourspillet-2026',
        'tour-de-france-2026',
        'tour-2026',
        'tourspillet',
        GAME_ID_TDF,  # numeric ID as fallback
    ]
    q6_probes = []
    seen_slugs = set()
    for slug in slug_candidates:
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        url = f'{BASE_URL}/da/{slug}/me/fantasyteams/{FANTASY_TEAM_ID}'
        s, c, b, _ = _try_get(url, timeout=20)
        entry = {
            'slug': slug, 'url': url, 'status': s, 'content_type': c,
            'body_len': len(b), 'body_sha16': _sha16(b),
            'has_initialLineup_marker': 'initialLineup' in b,
            'has_fantasyTeamId_marker': 'fantasyTeamId' in b,
            'has_login_redirect_marker': ('login' in b.lower()[:2000] and 'holdet' in b.lower()[:2000]),
        }
        # Redirect chain?
        # A 404 or explicit "not found" HTML would be the signal
        q6_probes.append(entry)
        print(f"  slug={slug!r}  HTTP {s}  initialLineup={entry['has_initialLineup_marker']}  fantasyTeamId={entry['has_fantasyTeamId_marker']}")
    report['q6_team_url_shape']['probes'] = q6_probes
    report['q6_team_url_shape']['fantasy_team_id_present'] = True
else:
    report['q6_team_url_shape']['fantasy_team_id_present'] = False
    report['q6_team_url_shape']['note'] = 'HOLDET_FANTASY_TEAM_ID env not set — cannot probe URL shape with real team ID. Structural probe possible only with an ID.'


# ── Finalize ──────────────────────────────────────────────────────────────────
report['completed_at'] = datetime.now(timezone.utc).isoformat()
report_path = OUT_DIR / 'tdf_substrate_smoke_report.json'
report_path.write_text(json.dumps(report, indent=2, default=str, ensure_ascii=False))
print()
print('=' * 78)
print(f'Report persisted at {report_path.relative_to(REPO)}')
print('=' * 78)
