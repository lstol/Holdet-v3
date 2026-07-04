# claude/engine/server.py
# Full local web app server for the Holdet v3 dashboard.
# Requires: pip install flask anthropic pyyaml python-dotenv
#
# Run from repo root: python3 claude/engine/server.py
# Dashboard: http://localhost:5050

import json
import os
import re
import sys
import datetime
from datetime import datetime as _dt
import subprocess
import time
import unicodedata
import concurrent.futures

# ── Load .env FIRST — before any anthropic instantiation ─────────────────────
from dotenv import load_dotenv

_HERE    = os.path.dirname(os.path.abspath(__file__))          # …/claude/engine
_ENV     = os.path.join(_HERE, '..', '..', '.env')             # repo root .env
load_dotenv(os.path.abspath(_ENV), override=True)              # explicit abs path; override=True so shell env blanks don't win

_API_KEY = os.getenv('ANTHROPIC_API_KEY')
if not _API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY not set — check .env at repo root")

# Race dispatch (HOLDET_ACTIVE_RACE → data_dir + stages filename). Import
# after .env load so env vars resolve.
sys.path.insert(0, _HERE)
from race_config import race_config as _race_config  # noqa: E402
_CFG = _race_config()

from flask import Flask, jsonify, request, send_from_directory

# Python optimizer (imported lazily so server starts even if numpy missing)
try:
    from optimizer import build_probabilities, simulate_stage, generate_candidate_teams, select_captain
    HAS_OPTIMIZER = True
except ImportError:
    HAS_OPTIMIZER = False

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False

try:
    import anthropic
    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

app = Flask(__name__)

BASE_DIR          = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAPSHOT_DIR      = os.path.join(BASE_DIR, 'shared', 'data', 'snapshots')
_DATA_DIR         = _CFG['data_dir']
RIDERS_FILE       = os.path.join(BASE_DIR, 'shared', 'data', 'riders', _DATA_DIR, 'riders.json')
AFFINITY_OVERRIDES_FILE = os.path.join(BASE_DIR, 'shared', 'data', 'riders', _DATA_DIR, 'terrain_affinity_overrides.json')
STAGE_SCORING_FILE= os.path.join(BASE_DIR, 'shared', 'data', 'stages', _DATA_DIR, 'stage_scoring.json')
EXPERT_SOURCES    = os.path.join(BASE_DIR, 'claude', 'engine', 'expert_sources.yaml')
FETCH_RIDERS      = os.path.join(BASE_DIR, 'claude', 'engine', 'fetch_riders.py')
LOG_FILE          = os.path.join(BASE_DIR, 'claude', 'logs', 'server.log')

def _load_stage_scoring():
    if os.path.exists(STAGE_SCORING_FILE):
        with open(STAGE_SCORING_FILE) as f:
            return json.load(f)
    return {}


# ── S17-AFFINITY: terrain_affinity override merge ────────────────────────────

def _load_affinity_overrides() -> dict:
    """Return dict mapping canonical rider name → override entry, or {} if file
    missing/empty/malformed. Tolerant on read; bad file logs and falls through
    rather than failing the whole riders load."""
    if not os.path.exists(AFFINITY_OVERRIDES_FILE):
        return {}
    try:
        with open(AFFINITY_OVERRIDES_FILE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        _log(f"affinity_overrides_load_error: {e}")
        return {}


def _save_affinity_overrides(data: dict) -> None:
    """Write override dict back to disk. Caller is responsible for canonicalising
    rider-name keys and validating dimension values before invoking."""
    os.makedirs(os.path.dirname(AFFINITY_OVERRIDES_FILE), exist_ok=True)
    with open(AFFINITY_OVERRIDES_FILE, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write('\n')


def _apply_affinity_overrides(riders: list) -> list:
    """Return a new list of rider dicts with `terrain_affinity` replaced by
    override values for any rider with an override entry. Riders without
    entries are passed through unchanged. Does NOT mutate the input list."""
    overrides = _load_affinity_overrides()
    if not overrides:
        return riders
    out = []
    for r in riders:
        entry = overrides.get(r.get('name'))
        if entry and isinstance(entry.get('overrides'), dict):
            r2 = dict(r)
            r2['terrain_affinity'] = dict(entry['overrides'])
            out.append(r2)
        else:
            out.append(r)
    return out


def _load_riders_merged(prefer_snapshot: bool = False) -> dict:
    """Load riders from RIDERS_FILE (or stage_1_holdet.json snapshot if
    `prefer_snapshot=True` and snapshot exists), apply terrain_affinity
    overrides, return the same `{riders, ...}` envelope as the source file.

    Single boundary for terrain_affinity override merge — every read site that
    previously did `json.load(open(RIDERS_FILE))` should call this helper.
    """
    if prefer_snapshot:
        snap = os.path.join(SNAPSHOT_DIR, 'stage_1_holdet.json')
        if os.path.exists(snap):
            data = json.load(open(snap))
            data = dict(data)
            data['riders'] = _apply_affinity_overrides(data.get('riders', []))
            return data
    with open(RIDERS_FILE) as f:
        data = json.load(f)
    data = dict(data)
    data['riders'] = _apply_affinity_overrides(data.get('riders', []))
    return data


def _derive_expert_stars(source_ratings, all_known_sources, all_riders):
    """S17-INTEL Phase 1a (2026-05-16): transform Haiku's source_ratings
    (per-source-then-per-rider) into expert_stars (per-rider-then-per-source).

    source_ratings: [{source, weight, ratings: [{rider, stars}]}] from Haiku.
    all_known_sources: list of canonical source identifiers from
                      expert_sources.yaml `canonical` field.
    all_riders: active rider roster for match_rider_name canonicalisation
               (may be empty list — falls back to raw Haiku-emitted name).

    Returns: {canonical_rider_name: {source_canonical: stars_or_null}}.
    Null-for-unrated: if a source did not rate a rider, the entry is
    None (zero-means-missing invariant; 0 would be a downvote).
    Phase 3 consumer math interprets null as "no signal → no lift".
    """
    expert_stars = {}

    def _canonicalise_name(raw):
        if not raw:
            return None
        if all_riders:
            matched = match_rider_name(raw, all_riders)
            if matched:
                return matched['name']
        return raw  # fallback to raw name; surfaces in expert_stars as-is

    # Pass 1: collect every rider mentioned across any source; init null row.
    for entry in source_ratings or []:
        if not isinstance(entry, dict):
            continue
        for rating in (entry.get('ratings') or []):
            if not isinstance(rating, dict):
                continue
            canonical_name = _canonicalise_name(rating.get('rider'))
            if canonical_name and canonical_name not in expert_stars:
                expert_stars[canonical_name] = {s: None for s in all_known_sources}

    # Pass 2: fill in actual ratings. Bound stars to [1, 5]; tolerate float.
    for entry in source_ratings or []:
        if not isinstance(entry, dict):
            continue
        source_canonical = entry.get('source')
        if source_canonical not in all_known_sources:
            continue  # unknown source (shouldn't happen if Haiku follows prompt)
        for rating in (entry.get('ratings') or []):
            if not isinstance(rating, dict):
                continue
            canonical_name = _canonicalise_name(rating.get('rider'))
            if not canonical_name or canonical_name not in expert_stars:
                continue
            stars_raw = rating.get('stars')
            try:
                stars_val = float(stars_raw)
            except (TypeError, ValueError):
                continue  # unparseable; leave as None
            if not (1 <= stars_val <= 5):
                continue  # out of range; leave as None
            # Prefer int when round-tripping cleanly (matches Haiku output shape).
            expert_stars[canonical_name][source_canonical] = (
                int(stars_val) if stars_val == int(stars_val) else stars_val
            )

    return expert_stars


def _log(msg: str) -> None:
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, 'a') as f:
        f.write(f"[{datetime.datetime.utcnow().isoformat()}] {msg}\n")


def call_with_retry(fn, max_retries=3):
    """Call fn(), retrying on RateLimitError with exponential backoff (60s, 120s, 180s)."""
    for attempt in range(max_retries):
        try:
            return fn()
        except anthropic.RateLimitError:
            if attempt == max_retries - 1:
                raise
            wait = 60 * (attempt + 1)
            app.logger.warning(f"Rate limit hit, waiting {wait}s (attempt {attempt + 1}/{max_retries})")
            _log(f"call_with_retry: rate limit, sleeping {wait}s")
            time.sleep(wait)


# name-matcher-hardening (2026-05-14): match_rider_name + _ascii_fold +
# _NICKNAME_ALIASES extracted to claude/engine/name_match.py for cross-module
# reuse (server.py + optimizer.py both need it; optimizer can't import server
# without a circular dependency). Behaviour preserved bit-identically.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from name_match import _ascii_fold, _NICKNAME_ALIASES, match_rider_name  # noqa: E402, F401


@app.after_request
def cors(r):
    r.headers['Access-Control-Allow-Origin'] = '*'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    r.headers['Access-Control-Allow-Methods'] = 'GET, POST, DELETE, OPTIONS'
    return r


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/')
@app.route('/dashboard')
def dashboard():
    return send_from_directory(os.path.join(BASE_DIR, 'claude', 'dashboard'), 'claude.html')


# ── Static files ─────────────────────────────────────────────────────────────

@app.route('/files/<path:filename>')
def static_files(filename):
    return send_from_directory(BASE_DIR, filename)


@app.route('/stage-images/<path:filename>')
def stage_images(filename):
    return send_from_directory(os.path.join(BASE_DIR, 'shared', 'data', 'stage_images'), filename)


# ── Stage scoring ────────────────────────────────────────────────────────────

@app.route('/stage-scoring/<int:stage_num>', methods=['GET'])
def stage_scoring(stage_num):
    scoring      = _load_stage_scoring()
    stage_config = scoring.get('stages', {}).get(str(stage_num), {})
    return jsonify({'stage': stage_num, 'config': stage_config, 'scoring': scoring})


# ── Riders ───────────────────────────────────────────────────────────────────

@app.route('/riders', methods=['GET'])
def riders():
    """Return riders from latest snapshot (live pricing) or riders.json (static).

    S17-AFFINITY: applies terrain_affinity overrides via `_apply_affinity_overrides`
    at the load boundary; clients (dashboard, optimizer) see merged values.
    """
    try:
        # S17-27: read stage_1 directly (canonical rider master list per
        # fetch_riders.py). The prior sorted([…])[-1] pattern silently fell
        # on later-stage stubs once they existed.
        path = os.path.join(SNAPSHOT_DIR, 'stage_1_holdet.json')
        if os.path.exists(path):
            data = json.load(open(path))
            return jsonify({
                'riders': _apply_affinity_overrides(data.get('riders', [])),
                'timestamp': data.get('timestamp'),
                'source': 'snapshot',
                '_filename': 'stage_1_holdet.json',
            })
    except Exception:
        pass
    try:
        with open(RIDERS_FILE) as f:
            data = json.load(f)
        return jsonify({
            'riders': _apply_affinity_overrides(data.get('riders', [])),
            'source': 'riders.json',
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── S17-AFFINITY: terrain_affinity override endpoints ───────────────────────

@app.route('/terrain-affinity-overrides', methods=['GET'])
def terrain_affinity_overrides_get():
    """Return raw contents of terrain_affinity_overrides.json (empty dict if file
    missing). No transformation."""
    return jsonify(_load_affinity_overrides())


@app.route('/terrain-affinity-overrides', methods=['POST', 'OPTIONS'])
def terrain_affinity_overrides_post():
    if request.method == 'OPTIONS':
        return ('', 204)
    """Upsert a rider's terrain_affinity override.

    Body: {"rider_name": "<name>", "overrides": {"sprint": 0.88, ...}}

    Server-side: (a) canonicalise rider_name via match_rider_name against active
    roster (error 400 if no match); (b) if no prior entry, snapshot the current
    riders.json terrain_affinity into `original`; (c) write `overrides` (full
    dimension set expected; missing keys default to whatever was there);
    (d) write `updated_at` ISO timestamp; (e) persist.

    All values must be numbers in [0.0, 1.0]. Returns 400 otherwise.
    """
    try:
        body = request.get_json(force=True) or {}
    except Exception:
        return jsonify({'status': 'error', 'message': 'invalid json body'}), 400

    raw_name  = (body.get('rider_name') or '').strip()
    new_over  = body.get('overrides')
    if not raw_name:
        return jsonify({'status': 'error', 'message': 'rider_name required'}), 400
    if not isinstance(new_over, dict) or not new_over:
        return jsonify({'status': 'error', 'message': 'overrides dict required'}), 400

    # Validate values in range
    for k, v in new_over.items():
        if not isinstance(v, (int, float)) or v < 0.0 or v > 1.0:
            return jsonify({
                'status': 'error',
                'message': f'value out of [0.0, 1.0] for dimension {k!r}: {v}',
            }), 400

    # Canonicalise name against active roster (read riders.json directly so
    # canonical-name resolution is not influenced by prior overrides).
    with open(RIDERS_FILE) as f:
        riders_data = json.load(f)
    active = [r for r in riders_data.get('riders', [])
              if not r.get('isOut') and r.get('status') != 'dns']
    match = match_rider_name(raw_name, active)
    if not match:
        return jsonify({
            'status': 'error',
            'message': f'rider_name {raw_name!r} did not match any active rider',
        }), 400
    canonical = match['name']

    overrides = _load_affinity_overrides()
    entry = overrides.get(canonical, {})
    # Snapshot original on first override creation (not overwritten on re-edit).
    if 'original' not in entry:
        original_ta = next(
            (r.get('terrain_affinity', {}) for r in riders_data.get('riders', [])
             if r['name'] == canonical),
            {},
        )
        entry['original'] = dict(original_ta)
    entry['overrides']  = {k: float(v) for k, v in new_over.items()}
    entry['updated_at'] = _dt.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')

    overrides[canonical] = entry
    _save_affinity_overrides(overrides)
    _log(f"terrain_affinity_override_saved rider={canonical!r} overrides={entry['overrides']}")
    return jsonify({'status': 'ok', 'rider_name': canonical, 'entry': entry})


@app.route('/terrain-affinity-overrides/<path:rider_name>', methods=['DELETE', 'OPTIONS'])
def terrain_affinity_overrides_delete(rider_name):
    """Remove a rider's override entry. Returns 200 even if no entry existed
    (idempotent)."""
    if request.method == 'OPTIONS':
        return ('', 204)
    overrides = _load_affinity_overrides()
    # Try direct match, then canonicalised match.
    if rider_name in overrides:
        canonical = rider_name
    else:
        with open(RIDERS_FILE) as f:
            active = [r for r in json.load(f).get('riders', [])
                      if not r.get('isOut') and r.get('status') != 'dns']
        match = match_rider_name(rider_name, active)
        canonical = match['name'] if match else rider_name
    removed = overrides.pop(canonical, None)
    _save_affinity_overrides(overrides)
    if removed is not None:
        _log(f"terrain_affinity_override_removed rider={canonical!r}")
    return jsonify({'status': 'ok', 'rider_name': canonical, 'removed': removed is not None})


# ── Refresh ───────────────────────────────────────────────────────────────────

def _latest_stage():
    """Return the most recently active stage number based on today's date."""
    stages_path = os.path.join(BASE_DIR, 'shared', 'data', 'stages', _DATA_DIR, _CFG['stages_file'])
    if not os.path.exists(stages_path):
        return 1
    stages = json.load(open(stages_path)).get('stages', [])
    import datetime as _dt
    today = _dt.date.today().isoformat()
    upcoming = [s for s in stages if s['date'] >= today]
    if upcoming:
        return upcoming[0]['stage_number']
    return stages[-1]['stage_number'] if stages else 1


@app.route('/refresh', methods=['POST', 'OPTIONS'])
def refresh():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        result = subprocess.run(
            [sys.executable, FETCH_RIDERS],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            return jsonify({'status': 'error', 'message': result.stderr}), 500

        # S17-27: fetch_riders.py writes the canonical rider master list to
        # stage_1_holdet.json only; later-stage snapshots carry per-stage
        # team_composition + bank without a riders field. Hardcoding stage_1
        # avoids the alphabetic sort-falls-on-later-stage failure mode that
        # emerged once stage_3_holdet.json appeared and dominated `[-1]`.
        stage1_path = os.path.join(SNAPSHOT_DIR, 'stage_1_holdet.json')
        rider_count = 0
        if os.path.exists(stage1_path):
            rider_count = len(json.load(open(stage1_path)).get('riders', []))

        return jsonify({
            'status': 'ok',
            'timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'rider_count': rider_count
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Run optimizer (Claude API / legacy — kept for reference, not exposed) ─────

def _run_optimizer_claude_api_legacy():
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_ANTHROPIC:
        return jsonify({'status': 'error', 'message': 'anthropic package not installed'}), 500
    data = request.json
    stage = data.get('stage', 1)
    sliders = data.get('sliders', {})
    force_in = data.get('force_in', [])
    force_out = data.get('force_out', [])

    odds_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
    if os.path.exists(odds_path):
        raw_odds = json.load(open(odds_path))
        odds = raw_odds.get('odds', raw_odds) if isinstance(raw_odds, dict) else raw_odds
    else:
        odds = []

    rider_data = _load_riders_merged()
    active_riders = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

    intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    intel_data = json.load(open(intel_path)).get('intel', {}) if os.path.exists(intel_path) else {}

    def sl(key):
        # S17-6 (2026-05-15): 5-term display string (added time_trial). Legacy
        # path not route-exposed but kept in sync for consistency.
        s = sliders.get(key, {})
        return (f"Bunch sprint {s.get('bunch_sprint',0)}%  "
                f"Reduced sprint {s.get('reduced_sprint',0)}%  "
                f"Breakaway {s.get('breakaway',0)}%  GC {s.get('gc',0)}%  "
                f"Time trial {s.get('time_trial',0)}%")

    # Only send Tier A riders (win_pct >= 1%) to the prompt — reduces tokens significantly
    tier_a = [r for r in active_riders
              if any(o['name'] == r['name'] and o.get('win_pct', 0) >= 1.0 for o in odds)]
    # Fall back to all active riders if odds not loaded yet
    prompt_riders = tier_a if tier_a else active_riders
    tier_b_count = len(active_riders) - len(prompt_riders)
    tier_b_prices = sorted([r.get('price', 0) for r in active_riders if r not in prompt_riders])
    tier_b_min = tier_b_prices[0] if tier_b_prices else 2_500_000
    tier_b_max = tier_b_prices[-1] if tier_b_prices else 6_000_000
    tier_b_summary = (f"{tier_b_count} additional budget riders available, "
                      f"prices {tier_b_min//1_000_000:.1f}M–{tier_b_max//1_000_000:.1f}M")

    riders_json = json.dumps(
        [{'name': r['name'], 'price': r.get('price', 0), 'team': r.get('team', '')}
         for r in prompt_riders],
        indent=2
    )
    odds_json = json.dumps(odds, indent=2)
    force_in_str  = str(force_in)  if force_in  else 'none'
    force_out_str = str(force_out) if force_out else 'none'
    if intel_data and isinstance(intel_data, dict) and intel_data.get('key_signals'):
        signals = intel_data.get('key_signals', [])
        intel_str = (
            f"Summary: {intel_data.get('summary', '')}\n"
            f"Weather: {intel_data.get('weather', '')}\n"
            f"Stage notes: {intel_data.get('stage_notes', '')}\n\n"
            "Key signals (adjust win probability accordingly):\n" +
            '\n'.join(
                f"  {s['rider']}: {s['direction'].upper()} ({s['strength']}) — {s['signal']}"
                for s in signals
            )
        )
    else:
        intel_str = 'Not yet gathered — use odds only.'

    prompt = f"""You are a Giro d'Italia fantasy optimizer. Rules and scoring are fixed — optimize for them exactly.

SCORING (fantasy points per stage):
Stage finish: 1st=200k 2nd=150k 3rd=130k 4th=120k 5th=110k 6th=100k 7th=95k 8th=90k 9th=85k 10th=80k 11th=70k 12th=55k 13th=40k 14th=30k 15th=15k
GC bonus: top-10 GC pays 100k/90k/80k/70k/60k/50k/40k/30k/20k/10k per stage
Team bonus: if teammate finishes 1st/2nd/3rd, all your riders from that team get +60k/+30k/+20k
Depth bonus: non-linear bonus for 0-8 riders in stage top-15: 0/4k/8k/15k/35k/65k/120k/220k/400k
Captain: positive value growth doubled, losses NOT amplified
DNF: -50k. DNS: -100k per remaining stage.
Budget: 50,000,000 kr. Team: exactly 8 riders. Max 2 per real-world team. Transfer cost: 1% buy cost.

STAGE {stage} TYPE MIX:
n+1 (this stage): {sl('n1')}
n+2: {sl('n2')}
n+3: {sl('n3')}

BOOKMAKER ODDS (implied win probability):
{odds_json}

AVAILABLE RIDERS (name, price, team) — Tier A only (win probability ≥ 1%):
{riders_json}

BUDGET FILLERS: {tier_b_summary}
(Use budget filler slots for team-bonus plays — pick riders whose real-world teammates are in your Tier A squad.)

CONSTRAINTS:
Force include: {force_in_str}
Force exclude: {force_out_str}

EXPERT INTEL:
{intel_str}

For each team, break down the EV estimate into components:
- stage_finish: expected points from stage finish positions weighted by probability
- captain_bonus: additional EV from doubling captain's positive outcomes
- team_bonus: expected +60k/+30k/+20k from teammates finishing top 3
- depth_bonus: expected non-linear bonus from riders in top 15
- gc_bonus: expected GC position bonus (100k-10k) for GC riders in team
All values in fantasy points (kr). Components must sum to ev_estimate.

OUTPUT — Return ONLY a JSON object, no preamble, no markdown, no code fences:
{{
  "teams": [
    {{
      "label": "Sprint-maximal",
      "riders": ["Name 1", "Name 2", "Name 3", "Name 4", "Name 5", "Name 6", "Name 7", "Name 8"],
      "total_price": 49500000,
      "ev_estimate": 850000,
      "ev_breakdown": {{
        "stage_finish": 580000,
        "captain_bonus": 160000,
        "team_bonus": 50000,
        "depth_bonus": 40000,
        "gc_bonus": 20000
      }},
      "cdf": {{"p25": 400000, "p50": 750000, "p75": 1100000, "p90": 1600000}},
      "forward_pressure": {{"n2": "low", "n3": "medium"}},
      "rationale": "One sentence."
    }}
  ],
  "captain": {{
    "name": "Rider Name",
    "rationale": "One sentence on right-tail EV logic."
  }},
  "tier_a": ["Name 1", "Name 2"]
}}

Generate 3-5 structurally distinct teams. Each exactly 8 riders, budget ≤50,000,000 kr, max 2 per real-world team."""

    try:
        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        message = call_with_retry(lambda: client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=4000,
            messages=[{'role': 'user', 'content': prompt}],
        ))
        raw = message.content[0].text.strip()
        _log(f"run-optimizer stage={stage} raw={raw[:200]}")
        if raw.startswith('```'):
            raw = re.sub(r'^```[a-z]*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
            raw = raw.strip()
        result = json.loads(raw)
        out_path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_claude.json')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        meta_path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_last_optimizer.json')
        with open(meta_path, 'w') as f:
            json.dump({'last': 'api'}, f)
        return jsonify(result)
    except json.JSONDecodeError as e:
        _log(f"run-optimizer JSON error: {e}")
        return jsonify({'status': 'error', 'message': str(e), 'raw': raw}), 500
    except Exception as e:
        _log(f"run-optimizer error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Run optimizer ────────────────────────────────────────────────────────────

@app.route('/run-optimizer', methods=['POST', 'OPTIONS'])
def run_optimizer_py():
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_OPTIMIZER:
        return jsonify({'status': 'error', 'message': 'optimizer.py not importable (numpy missing?)'}), 500

    data      = request.json or {}
    stage     = data.get('stage', 1)
    sliders   = data.get('sliders', {})
    force_in  = data.get('force_in', [])
    force_out = data.get('force_out', [])
    use_race_type = bool(data.get('use_race_type_adjustment', False))

    odds_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
    if os.path.exists(odds_path):
        raw_odds = json.load(open(odds_path))
        odds = raw_odds.get('odds', raw_odds) if isinstance(raw_odds, dict) else raw_odds
    else:
        odds = []

    # S17-24: detect the "present but all-zero" odds state introduced by
    # S17-20's clear buttons. With uniform probabilities SA has no gradient
    # and every chain runs to its max_seconds cap (~200s total), exceeding
    # the dashboard's 120s AbortController. Empty list (`odds = []`) is the
    # legitimate fresh-stage / Stage-1 flow and stays on the slider-only
    # fallback path inside build_probabilities — only the present-but-zero
    # case is short-circuited here.
    has_win_signal = any((o.get('win_pct') or 0) > 0 for o in odds)
    if odds and not has_win_signal:
        return jsonify({
            'status': 'error',
            'message': (
                f'Stage {stage} odds are all zero — likely cleared via the ✕ button. '
                'Paste win odds before running the optimizer, or click the win-odds '
                'paste zone to gather them.'
            ),
        }), 400

    rider_data    = _load_riders_merged()
    active_riders = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

    intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    intel_data = json.load(open(intel_path)) if os.path.exists(intel_path) else {}

    # S17-ι Phase 1: load previous-stage standings for Tier 2 (GC top-10) and
    # Tier 4 (Points + KOM top-10) of the tier-union biased-swap pool. Falls
    # back to empty when standings haven't been gathered yet for stage N-1
    # (e.g., Stage 1 prep before any standings exist) — optimizer.py's
    # build_tier_union_pool then returns None and SA falls back to legacy
    # top-50-by-EV path.
    standings_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage - 1}_standings.json')
    standings_data = json.load(open(standings_path)) if os.path.exists(standings_path) else {}

    # S17-BANK Bug A fix (2026-05-15): bank balance comes from the PREVIOUS
    # stage's results.json (the post-race bank, which is the available budget
    # to deploy for the upcoming stage). Same source the dashboard
    # `/stage-results` endpoint reads for the "How it unfolded" panel — single
    # source of truth for optimizer + display surfaces.
    # Pre-fix: read stage_{stage}_holdet.json (target-stage snapshot, which
    # doesn't exist pre-race) and fell through to hardcoded 50_000_000.
    snapshot_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage - 1}_results.json')
    snapshot = json.load(open(snapshot_path)) if os.path.exists(snapshot_path) else {}
    budget = int(snapshot.get('bank_balance', 50_000_000))

    # Current team is the team that just raced — pull from previous stage's results.json.
    # Holdet API spells names exactly as riders.json should, but historically a few rows
    # diverge in case (e.g. "Dries van Gestel" vs "Dries Van Gestel"), so we fall back
    # case-insensitively and surface anything that still doesn't match.
    current_team = None
    name_match_warnings = []
    prev_stage = stage - 1
    if prev_stage >= 1:
        results_path = os.path.join(SNAPSHOT_DIR, f'stage_{prev_stage}_results.json')
        if os.path.exists(results_path):
            results_doc = json.load(open(results_path))
            prev_names = [r.get('name', '') for r in results_doc.get('rider_results', []) if r.get('name')]

            by_exact = {r['name']: r for r in active_riders}
            by_lower = {r['name'].lower(): r for r in active_riders}

            matched = []
            for n in prev_names:
                if n in by_exact:
                    matched.append(by_exact[n])
                elif n.lower() in by_lower:
                    real = by_lower[n.lower()]
                    matched.append(real)
                    _log(f"run-optimizer stage={stage} case-insensitive match '{n}' → '{real['name']}'")
                else:
                    name_match_warnings.append(n)
                    app.logger.warning(f"run-optimizer stage={stage}: '{n}' from stage_{prev_stage}_results.json not in active riders")
                    _log(f"run-optimizer stage={stage} WARNING: '{n}' from stage_{prev_stage}_results.json not in active riders")

            current_team = matched or None
            _log(f"run-optimizer stage={stage} current_team from stage_{prev_stage}_results.json: {len(matched)}/{len(prev_names)} matched")
        else:
            _log(f"run-optimizer stage={stage}: stage_{prev_stage}_results.json missing — empty current_team (zero transfer cost)")

    app.logger.info(f"run-optimizer-py stage={stage} budget={budget:,}")
    _log(f"run-optimizer-py stage={stage} budget={budget:,}")

    try:
        from optimizer import (build_probabilities, build_forward_probabilities,
                               compute_seed,
                               generate_candidate_teams, load_stage_scoring, get_stage_config,
                               select_captain)

        scoring      = load_stage_scoring()
        stage_config = get_stage_config(stage, scoring)

        # S16-3: derive a deterministic seed from the request payload so
        # identical inputs produce bit-identical outputs across runs. The
        # seed is propagated to every RNG site in the optimizer pipeline
        # (initial-team shuffle, SA exploration, Plackett-Luce sampling).
        base_seed = compute_seed(stage, sliders, force_in, force_out, use_race_type)

        # Current stage: real odds + intel (+ optional race-type adjustment from n1 slider)
        # Sub-B2 (2026-05-14): pass standings_data through so build_probabilities
        # can use standings-aware retention path for in-GC-top-10 riders.
        probs_current = build_probabilities(
            active_riders, odds, intel_data, sliders.get('n1', {}),
            stage_config=stage_config, scoring=scoring,
            use_race_type=use_race_type,
            standings=standings_data,
        )

        # Forward stages: slider-based inference. S17-16 forward-intel
        # multipliers reverted in S17-γ — INTEL_MULT is a re-ranking op on a
        # bookmaker distribution; forward stages have no such distribution.
        # forward_nN_intel keys still populated on disk by /gather-intel and
        # surfaced in dashboard rectangles (S17-15 + S17-α), just unconsumed here.
        probs_n1 = build_forward_probabilities(active_riders, sliders.get('n2', {}))
        probs_n2 = build_forward_probabilities(active_riders, sliders.get('n3', {}))

        teams = generate_candidate_teams(
            active_riders, probs_current,
            probs_n1, probs_n2,
            force_in, force_out, budget,
            stage_config, scoring, active_riders,
            current_team=current_team if current_team else None,
            seed=base_seed,
            # S17-ι Phase 1: pass substrate so the biased-swap pool can be
            # built as Tier 1 ∪ Tier 2 ∪ Tier 3 ∪ Tier 4 ∪ Tier 5 ∪ current_team
            # instead of top-50-by-EV. Missing substrate → falls back to legacy.
            odds=odds,
            intel=intel_data,
            standings=standings_data,
            sliders=sliders,
        )

        if not teams:
            return jsonify({'status': 'error', 'message': 'No valid teams found — check budget/constraints'}), 500

        output = {
            'teams': [{
                **t,
                'riders': [{'name': r['name'], 'team': r.get('team', ''),
                             'price': r['price'], 'type': r.get('type', '')}
                           for r in t['riders']],
            } for t in teams],
            'captain': teams[0]['captain'] if teams else {},
            'budget':  budget,
            'stage':   stage,
            'current_team': [
                {'name': r['name'], 'team': r.get('team', ''),
                 'price': r.get('price', 0), 'type': r.get('type', '')}
                for r in (current_team or [])
            ],
            'name_match_warnings': name_match_warnings,
        }

        out_path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_claude_py.json')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        meta_path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_last_optimizer.json')
        with open(meta_path, 'w') as f:
            json.dump({'last': 'py'}, f)

        _log(f"run-optimizer-py stage={stage} teams={len(teams)}")
        return jsonify(output)

    except Exception as e:
        _log(f"run-optimizer-py error: {e}")
        import traceback
        app.logger.error(traceback.format_exc())
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Save / load intel ─────────────────────────────────────────────────────────

@app.route('/save-intel', methods=['POST', 'OPTIONS'])
def save_intel():
    if request.method == 'OPTIONS':
        return '', 204
    stage = request.json.get('stage')
    intel = request.json.get('intel', {})
    path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    with open(path, 'w') as f:
        json.dump({'stage': stage, 'intel': intel,
                   'gathered_at': _dt.now().isoformat()}, f, indent=2, ensure_ascii=False)
    return jsonify({'status': 'ok'})


@app.route('/load-intel', methods=['GET'])
def load_intel():
    stage = request.args.get('stage')
    path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        intel = data.get('intel', {})
        intel['_gathered_at'] = data.get('gathered_at')
        return jsonify(intel)
    return jsonify({})


# ── Load optimizer output ────────────────────────────────────────────────────

@app.route('/load-output', methods=['GET'])
def load_output():
    stage = request.args.get('stage')
    path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_claude.json')
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify({})


@app.route('/load-output-py', methods=['GET'])
def load_output_py():
    stage = request.args.get('stage')
    path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_claude_py.json')
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify({})


@app.route('/load-last-optimizer', methods=['GET'])
def load_last_optimizer():
    stage = request.args.get('stage')
    path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_last_optimizer.json')
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify({'last': 'api'})


# ── Save / load odds ─────────────────────────────────────────────────────────

@app.route('/save-odds', methods=['POST', 'OPTIONS'])
def save_odds():
    if request.method == 'OPTIONS':
        return '', 204
    stage = request.json.get('stage')
    odds  = request.json.get('odds')
    path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
    with open(path, 'w') as f:
        json.dump({'odds': odds, 'stage': stage,
                   'gathered_at': _dt.now().isoformat()}, f, indent=2)
    return jsonify({'status': 'ok'})


@app.route('/load-odds', methods=['GET'])
def load_odds():
    stage = request.args.get('stage')
    path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        # Support both old format (bare array) and new envelope {odds, gathered_at}
        if isinstance(data, list):
            return jsonify({'odds': data, 'gathered_at': None})
        return jsonify(data)
    return jsonify({'odds': [], 'gathered_at': None})


# ── Parse odds image ─────────────────────────────────────────────────────────

@app.route('/parse-odds-image', methods=['POST', 'OPTIONS'])
def parse_odds_image():
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_ANTHROPIC:
        return jsonify({'status': 'error', 'message': 'anthropic package not installed'}), 500
    body       = request.json
    stage      = body.get('stage', '?')
    image_data = body.get('image')
    media_type = body.get('media_type', 'image/png')
    odds_type  = body.get('type', 'win')   # 'win' | 'top3' | 'top10'

    type_map  = {'win': 'win probability', 'top3': 'top-3 finish probability', 'top10': 'top-10 finish probability'}
    field_map = {'win': 'win_pct',         'top3': 'top3_pct',                 'top10': 'top10_pct'}
    prob_label = type_map.get(odds_type, 'win probability')
    field_name = field_map.get(odds_type, 'win_pct')

    raw = ''
    try:
        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        prompt = (
            f"This is an Oddschecker odds table for Stage {stage} Giro d'Italia 2026.\n\n"
            "TABLE STRUCTURE:\n"
            "- Each ROW is one rider (rider name in the leftmost column)\n"
            "- Each subsequent COLUMN is a different bookmaker showing decimal odds\n"
            "- The LAST column on the right is often the best odds (highlighted)\n"
            "- Ignore any highlighted/bold values — use ALL columns equally\n\n"
            "TASK:\n"
            "For each rider row:\n"
            "1. Read ALL decimal odds values across ALL bookmaker columns for that rider\n"
            "2. Calculate the AVERAGE of all those decimal values\n"
            "3. Convert average to implied probability: pct = round(100 / average, 1)\n"
            "4. Include only riders where pct >= 1.0\n\n"
            f"This is {prob_label} data — not win odds.\n\n"
            "IMPORTANT: Every rider must have a DIFFERENT probability. If you find yourself\n"
            "assigning the same value to multiple riders, you are reading the table incorrectly.\n"
            "Re-examine the image carefully — each row has different odds.\n\n"
            "Return ONLY a JSON array, no markdown, no other text:\n"
            '[{"name": "Rider Name", "pct": 5.2}]\n'
            "Sorted by pct descending."
        )
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2000,
            messages=[{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': image_data}},
                {'type': 'text',  'text': prompt},
            ]}],
        )
        raw = message.content[0].text.strip()
        _log(f"parse-odds-image stage={stage} type={odds_type} raw={raw[:400]}")
        # Strip markdown fences (handle leading spaces/newlines too)
        raw = re.sub(r'^[\s]*```[a-z]*\s*', '', raw)
        raw = re.sub(r'\s*```[\s]*$', '', raw)
        raw = raw.strip()
        # Extract the JSON array — find outermost [ ... ]
        start = raw.find('[')
        end   = raw.rfind(']')
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end+1]
        _log(f"parse-odds-image after-strip raw={repr(raw[:200])}")
        parsed = json.loads(raw)  # [{name, pct}, ...]

        # Validate: suspicious uniformity means the model misread the table
        pcts = [item.get('pct') or item.get(field_name) or item.get('win_pct') or 0 for item in parsed]
        if len(pcts) > 3:
            unique_pcts = len(set(pcts))
            if unique_pcts <= 2:
                _log(f"parse-odds-image suspicious uniformity: {unique_pcts} unique values for {len(pcts)} riders")
                return jsonify({
                    'status': 'error',
                    'message': f'Parsing error: {unique_pcts} unique value(s) for {len(pcts)} riders — model misread the table. Try a cleaner screenshot.',
                    'raw': raw,
                }), 500

        # Load existing odds to merge into (guard against empty/corrupt file)
        odds_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
        existing = []
        if os.path.exists(odds_path) and os.path.getsize(odds_path) > 0:
            try:
                existing_file = json.load(open(odds_path))
                existing = existing_file.get('odds', existing_file) if isinstance(existing_file, dict) else existing_file
            except (json.JSONDecodeError, ValueError):
                existing = []

        # Build name→row index map for merge
        existing_map = {r['name']: r for r in existing}

        # name-matcher-hardening (2026-05-14): canonicalise Haiku-read rider
        # names against the active roster before storing. Previously
        # /parse-odds-image stored Haiku's raw output verbatim, so name
        # mismatches (e.g. "Antonio Morgado" vs canonical "António Morgado",
        # "Jonas Vingegaard Hansen" vs "Jonas Vingegaard") propagated into
        # stage_N_odds.json. Downstream `build_probabilities` does
        # `odds_map.get(r['name'], 0.0)` and silently misses, dropping the
        # rider's bookmaker signal to EPS. Canonicalise here so the JSON is
        # clean going forward; `build_probabilities` also canonicalises
        # defensively at read time for historical data.
        try:
            _rd = _load_riders_merged()
            active_riders = [r for r in _rd.get('riders', [])
                             if not r.get('isOut') and r.get('status') != 'dns']
        except Exception:
            active_riders = []
        unmatched = []

        for item in parsed:
            raw_name = item.get('name', '')
            # Model sometimes returns field-specific keys (win_pct, top3_pct, top10_pct)
            # instead of the requested 'pct' key — accept both
            pct  = item.get('pct') or item.get(field_name) or item.get('win_pct') or 0
            if not raw_name:
                continue
            matched = match_rider_name(raw_name, active_riders) if active_riders else None
            name = matched['name'] if matched else raw_name
            if matched is None:
                unmatched.append(raw_name)
            if name in existing_map:
                existing_map[name][field_name] = pct
            else:
                # New rider — create row with only the pasted field populated
                existing_map[name] = {'name': name, field_name: pct}

        if unmatched:
            _log(f"parse-odds-image stage={stage} unmatched names ({len(unmatched)}): {unmatched[:10]}")

        merged = sorted(existing_map.values(), key=lambda r: r.get('win_pct', 0), reverse=True)

        # Save merged result with timestamp
        with open(odds_path, 'w') as f:
            json.dump({'odds': merged, 'stage': stage,
                       'gathered_at': _dt.now().isoformat()}, f, indent=2)

        return jsonify(merged)
    except json.JSONDecodeError as e:
        _log(f"parse-odds-image JSON error: {e}")
        return jsonify({'status': 'error', 'message': str(e), 'raw': raw}), 500
    except Exception as e:
        _log(f"parse-odds-image error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Parse single-bookmaker two-column odds image ──────────────────────────────

@app.route('/parse-odds-image-single', methods=['POST', 'OPTIONS'])
def parse_odds_image_single():
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_ANTHROPIC:
        return jsonify({'status': 'error', 'message': 'anthropic package not installed'}), 500
    body       = request.json
    stage      = body.get('stage', '?')
    image_data = body.get('image')
    media_type = body.get('media_type', 'image/png')
    odds_type  = body.get('type', 'top3')   # 'top3' | 'top10'

    field_map = {'top3': 'top3_pct', 'top10': 'top10_pct'}
    col_map   = {'top3': '(1-3)',    'top10': '(1-10)'}
    field_name = field_map.get(odds_type, 'top3_pct')
    col_label  = col_map.get(odds_type, '(1-3)')

    raw = ''
    try:
        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2000,
            messages=[{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': image_data}},
                {'type': 'text',  'text': (
                    f"This table has two columns: 'Vinder' (win odds) and '{col_label}' ({odds_type} odds).\n"
                    f"Read ONLY the '{col_label}' column — the RIGHTMOST column.\n"
                    "For each rider, read their decimal odds value from that column only.\n"
                    "Convert to implied probability: pct = round(100 / odds, 1)\n"
                    "Include all riders visible.\n"
                    "Return ONLY a JSON array, no markdown:\n"
                    '[{"name": "Rider Name", "pct": 74.1}] sorted by pct descending.'
                )},
            ]}],
        )
        raw = message.content[0].text.strip()
        _log(f"parse-odds-image-single stage={stage} type={odds_type} raw={raw[:400]}")
        # Strip markdown fences
        raw = re.sub(r'^[\s]*```[a-z]*\s*', '', raw)
        raw = re.sub(r'\s*```[\s]*$', '', raw)
        raw = raw.strip()
        start = raw.find('[')
        end   = raw.rfind(']')
        if start != -1 and end != -1 and end > start:
            raw = raw[start:end+1]
        parsed = json.loads(raw)

        # Load existing odds to merge into (guard against empty/corrupt file)
        odds_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
        existing = []
        if os.path.exists(odds_path) and os.path.getsize(odds_path) > 0:
            try:
                existing_file = json.load(open(odds_path))
                existing = existing_file.get('odds', existing_file) if isinstance(existing_file, dict) else existing_file
            except (json.JSONDecodeError, ValueError):
                existing = []

        existing_map = {r['name']: r for r in existing}
        for item in parsed:
            name = item.get('name', '')
            pct  = item.get('pct') or 0
            if not name:
                continue
            if name in existing_map:
                existing_map[name][field_name] = pct
            else:
                existing_map[name] = {'name': name, field_name: pct}

        merged = sorted(existing_map.values(), key=lambda r: r.get('win_pct', 0), reverse=True)

        with open(odds_path, 'w') as f:
            json.dump({'odds': merged, 'stage': stage,
                       'gathered_at': _dt.now().isoformat()}, f, indent=2)

        return jsonify(merged)
    except json.JSONDecodeError as e:
        _log(f"parse-odds-image-single JSON error: {e}")
        return jsonify({'status': 'error', 'message': str(e), 'raw': raw}), 500
    except Exception as e:
        _log(f"parse-odds-image-single error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Clear odds bucket (S17-20) ─────────────────────────────────────────────────

@app.route('/clear-odds', methods=['POST', 'OPTIONS'])
def clear_odds():
    """Zero a single bucket (win / top3 / top10) for one stage on disk.
    Mirrors /parse-odds-image's bucket-isolation property: only the named
    field is touched; other buckets are preserved.
    """
    if request.method == 'OPTIONS':
        return '', 204
    body   = request.json or {}
    stage  = body.get('stage')
    bucket = body.get('bucket')
    field_map = {'win': 'win_pct', 'top3': 'top3_pct', 'top10': 'top10_pct'}

    if not isinstance(stage, int) or not (1 <= stage <= 21):
        return jsonify({'ok': False, 'error': f'stage must be int in [1,21], got {stage!r}'}), 400
    if bucket not in field_map:
        return jsonify({'ok': False, 'error': f'bucket must be one of {list(field_map)}, got {bucket!r}'}), 400
    field_name = field_map[bucket]

    odds_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
    # Stage-N edge: no on-disk file ⇒ in-memory clear is still valid.
    if not os.path.exists(odds_path):
        return jsonify({'ok': True, 'stage': stage, 'bucket': bucket, 'cleared_count': 0})

    try:
        with open(odds_path) as f:
            existing_file = json.load(f)
        is_envelope = isinstance(existing_file, dict)
        rows = existing_file.get('odds', existing_file) if is_envelope else existing_file
        if not isinstance(rows, list):
            return jsonify({'ok': False, 'error': f'unexpected odds schema in {odds_path}'}), 500

        cleared = 0
        for r in rows:
            if not isinstance(r, dict):
                continue
            r[field_name] = 0
            cleared += 1

        # Preserve envelope (stage + gathered_at) when present. Don't refresh
        # gathered_at — this isn't new gathered data.
        if is_envelope:
            existing_file['odds'] = rows
            payload = existing_file
        else:
            payload = rows

        with open(odds_path, 'w') as f:
            json.dump(payload, f, indent=2)
        _log(f"clear-odds stage={stage} bucket={bucket} cleared={cleared}")
        return jsonify({'ok': True, 'stage': stage, 'bucket': bucket, 'cleared_count': cleared})
    except Exception as e:
        _log(f"clear-odds error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ── Gather intel ──────────────────────────────────────────────────────────────

def _haiku_extract_forward(stage_num: int, tv2_prose: str, client) -> dict | None:
    """S17-15: extract key_signals + stage_classification for a forward stage
    from TV2/Axelgaard prose only (Feltet/Inner Ring rarely cover n+1/n+2 ahead
    of race day). Returns None when prose is the not-found sentinel, a scrape
    error placeholder, empty, or when the Haiku call / JSON parse fails.
    Callers treat None as 'omit this forward_nN_intel key' — the consumer
    (`build_forward_probabilities`) then falls back to slider-only forward EV.
    """
    if not tv2_prose or len(tv2_prose) < 200:
        return None
    if tv2_prose.startswith('[TV2/Axelgaard:') or tv2_prose.startswith('[TV2 '):
        return None
    try:
        msg = call_with_retry(lambda: client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2000,
            messages=[{'role': 'user', 'content': f"""Structure this Axelgaard forward-stage preview for Stage {stage_num} Giro d'Italia 2026 into JSON.

TV2/AXELGAARD (Danish — summarise key rider signals in English):
{tv2_prose[:3000]}

Focus: which riders will perform well on this stage, which are downgraded relative to bookmaker odds.

Return ONLY the JSON object below. No text before or after. No markdown fences.
{{
  "stage_classification": "stage type label — e.g. 'Flad etape', 'Bjergetape', 'Bakketop', 'Enkeltstart' — copy from article or infer from terrain description",
  "key_signals": [
    {{"rider": "Name", "signal": "what was said (English)", "direction": "up/down/neutral", "strength": "strong/moderate/weak"}}
  ]
}}

Rules:
- direction: up = favoured beyond raw odds, down = risk not in odds, neutral = in line with odds
- strength: strong / moderate / weak
- Only include riders for whom the article makes a substantive forward-looking signal
- Translate Danish rider mentions to English; keep signal sentence concise"""}]
        ))
        raw = msg.content[0].text
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            _log(f"gather-intel forward stage={stage_num}: no JSON in Haiku response")
            return None
        result = json.loads(m.group())
        if not isinstance(result, dict) or 'key_signals' not in result:
            _log(f"gather-intel forward stage={stage_num}: malformed Haiku JSON (missing key_signals)")
            return None
        return result
    except Exception as e:
        _log(f"gather-intel forward stage={stage_num}: extraction failed: {e}")
        return None


@app.route('/gather-intel', methods=['POST', 'OPTIONS'])
def gather_intel():
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_ANTHROPIC:
        return jsonify({'status': 'error', 'message': 'anthropic package not installed'}), 500
    stage = request.json.get('stage', '?')
    raw = ''
    try:
        # Step 1: scrape current-stage triple (Playwright) + forward n+1/n+2 (S17-β: generic
        # preview via HTTP, no Playwright) — all in parallel. After scrape, detect Axelgaard
        # not-found sentinel on current-stage TV2 and fall back to the generic URL.
        app.logger.info(f"Scraping intel for Stage {stage}...")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from scraper import (scrape_all_intel, fetch_tv2_generic_preview,
                             scrape_phase1b_sources, scrape_phase1c_sources)
        # S17-INTEL Phase 1b (2026-05-16): scrape_phase1b_sources runs in
        # parallel with the existing scrape_all_intel + forward TV2 calls.
        # Returns {inner_ring, touretappe, total_velo, cyclingnews}.
        # S17-INTEL Phase 1c (2026-05-16): scrape_phase1c_sources adds
        # {wielerflits, indeleiderstrui, cicloweb, todaycycling,
        #  cyclingstage}. Wielerflits uses Playwright; the other four are
        # HTTP. ThreadPoolExecutor handles all five in parallel.
        # SpazioCiclismo deferred to Phase 4 (yaml entry retained as
        # placeholder; orchestrator never invokes it).
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as scrape_executor:
            current_scrape_future = scrape_executor.submit(scrape_all_intel, int(stage))
            n1_fwd_future = scrape_executor.submit(fetch_tv2_generic_preview, int(stage) + 1)
            n2_fwd_future = scrape_executor.submit(fetch_tv2_generic_preview, int(stage) + 2)
            phase1b_future = scrape_executor.submit(scrape_phase1b_sources, int(stage))
            phase1c_future = scrape_executor.submit(scrape_phase1c_sources, int(stage))
            raw_sources = current_scrape_future.result()
            n1_fwd = n1_fwd_future.result()
            n2_fwd = n2_fwd_future.result()
            phase1b_sources = phase1b_future.result()
            phase1c_sources = phase1c_future.result()

        # S17-β: current-stage Axelgaard fallback. If the Playwright scraper returned the
        # not-found sentinel (Axelgaard hasn't published his detailed column yet), substitute
        # the generic preview prose. The generic URL 301-redirects to Axelgaard when his
        # detailed article exists, so source detection from the final URL is authoritative.
        current_source = 'axelgaard'
        tv2_prose = raw_sources['tv2']
        if tv2_prose.startswith('[TV2/Axelgaard:') or tv2_prose.startswith('[TV2 '):
            fallback = fetch_tv2_generic_preview(int(stage))
            if fallback['source'] != 'not_found':
                tv2_prose = fallback['prose']
                raw_sources['tv2'] = tv2_prose
                current_source = fallback['source']
            else:
                current_source = 'both_failed'

        # S17-INTEL Phase 1b (2026-05-16): log adds Phase 1b source sizes
        # (inner_ring / touretappe / total_velo / cyclingnews) alongside the
        # existing TV2/Feltet/Inner-Ring-deprecated entries. Note: the
        # `inrng` log field below references the OLD Playwright Inner Ring
        # scrape via scrape_all_intel — kept for backward-compat with
        # log-parsing tooling. The NEW direct-HTTP Inner Ring lives in
        # phase1b_sources['inner_ring'] and feeds source_texts.
        app.logger.info(
            f"TV2: {len(raw_sources['tv2'])} chars (source={current_source}) | "
            f"Feltet: {len(raw_sources['feltet'])} chars | "
            f"Inner Ring (old PW): {len(raw_sources['inner_ring'])} chars | "
            f"TV2 n+1: {len(n1_fwd.get('prose', ''))} chars (source={n1_fwd.get('source')}) | "
            f"TV2 n+2: {len(n2_fwd.get('prose', ''))} chars (source={n2_fwd.get('source')}) | "
            f"Phase1b: inner_ring={len(phase1b_sources.get('inner_ring') or '')} "
            f"touretappe={len(phase1b_sources.get('touretappe') or '')} "
            f"total_velo={len(phase1b_sources.get('total_velo') or '')} "
            f"cyclingnews={len(phase1b_sources.get('cyclingnews') or '')}"
        )
        _log(
            f"gather-intel stage={stage} scraped "
            f"tv2={len(raw_sources['tv2'])}/{current_source} "
            f"feltet={len(raw_sources['feltet'])} "
            f"inrng_old={len(raw_sources['inner_ring'])} "
            f"tv2_n1={len(n1_fwd.get('prose',''))}/{n1_fwd.get('source')} "
            f"tv2_n2={len(n2_fwd.get('prose',''))}/{n2_fwd.get('source')} "
            f"p1b_inner_ring={len(phase1b_sources.get('inner_ring') or '')} "
            f"p1b_touretappe={len(phase1b_sources.get('touretappe') or '')} "
            f"p1b_total_velo={len(phase1b_sources.get('total_velo') or '')} "
            f"p1b_cyclingnews={len(phase1b_sources.get('cyclingnews') or '')} "
            f"p1c_wielerflits={len(phase1c_sources.get('wielerflits') or '')} "
            f"p1c_indeleiderstrui={len(phase1c_sources.get('indeleiderstrui') or '')} "
            f"p1c_cicloweb={len(phase1c_sources.get('cicloweb') or '')} "
            f"p1c_todaycycling={len(phase1c_sources.get('todaycycling') or '')} "
            f"p1c_cyclingstage={len(phase1c_sources.get('cyclingstage') or '')}"
        )

        # Step 2: structure with 3 parallel Haiku calls — current stage + forward n+1 + forward n+2 (S17-15)
        # S17-INTEL Phase 1a (2026-05-16): refactored to yaml-driven N-source
        # iteration. expert_sources.yaml lists 13 sources (canonical + weight
        # + scraper); _haiku_current builds per-source context blocks via
        # iteration, injecting "[Article not found for this stage]" for
        # sources where scraper hasn't been wired (Phase 1b/1c) or returned
        # no content. Wired in Phase 1a: tv2_axelgaard, tv2_generic, feltet.
        sources_config = yaml.safe_load(open(EXPERT_SOURCES))['sources']
        all_known_sources = [s['canonical'] for s in sources_config]

        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

        # Per-source article-text dispatch. Phase 1a wires 3; the other 10
        # return None (placeholder). The fallback logic above already
        # mutated raw_sources['tv2'] to the generic preview when Axelgaard
        # was absent — for the new tv2_axelgaard / tv2_generic separation,
        # use the ORIGINAL Axelgaard text (sentinel → None) and ALWAYS
        # attempt the generic shell separately (independent source).
        _axelgaard_orig = raw_sources.get('tv2', '')
        _axelgaard_failed = (_axelgaard_orig.startswith('[TV2/Axelgaard:')
                             or _axelgaard_orig.startswith('[TV2 '))
        _tv2_axelgaard_text = None if _axelgaard_failed else (_axelgaard_orig or None)
        # tv2_generic: reuse fallback result if already fetched; else fetch now.
        _tv2_generic_result = locals().get('fallback') or fetch_tv2_generic_preview(int(stage))
        _tv2_generic_text = _tv2_generic_result.get('prose') or None
        # Feltet: existing scrape; sentinel-check.
        _feltet_text = raw_sources.get('feltet', '')
        if not _feltet_text or _feltet_text.startswith('[Feltet'):
            _feltet_text = None

        # Source-text dispatch.
        #   Phase 1a wired: tv2_axelgaard, tv2_generic, feltet.
        #   Phase 1b (2026-05-16) wired via scrape_phase1b_sources:
        #     inner_ring, touretappe, total_velo, cyclingnews.
        #   Phase 1c (2026-05-16) wired via scrape_phase1c_sources:
        #     wielerflits (Playwright), indeleiderstrui, cicloweb,
        #     todaycycling, cyclingstage (hub-section).
        #   SpazioCiclismo deferred to Phase 4 (yaml entry retains as
        #     placeholder; no orchestrator call → automatic
        #     "[Article not found for this stage]" injection in Haiku
        #     prompt).
        source_texts = {
            'tv2_axelgaard':   _tv2_axelgaard_text,
            'tv2_generic':     _tv2_generic_text,
            'feltet':          _feltet_text,
            'inner_ring':      phase1b_sources.get('inner_ring')      or None,
            'touretappe':      phase1b_sources.get('touretappe')      or None,
            'total_velo':      phase1b_sources.get('total_velo')      or None,
            'cyclingnews':     phase1b_sources.get('cyclingnews')     or None,
            'wielerflits':     phase1c_sources.get('wielerflits')     or None,
            'indeleiderstrui': phase1c_sources.get('indeleiderstrui') or None,
            'cicloweb':        phase1c_sources.get('cicloweb')        or None,
            'todaycycling':    phase1c_sources.get('todaycycling')    or None,
            'cyclingstage':    phase1c_sources.get('cyclingstage')    or None,
        }

        def _haiku_current():
            # Build SOURCE WEIGHTS section + per-source context blocks via
            # yaml iteration. Placeholder injected for un-wired or failed
            # scrapers — keeps Haiku aware of attempted-but-absent sources.
            weight_lines = []
            source_blocks = []
            for src in sources_config:
                canonical = src['canonical']
                weight_lines.append(f"- {src['name']} ({canonical}): weight {src['weight']}")
                article = source_texts.get(canonical)
                header = f"=== {src['name'].upper()} (canonical: {canonical}, weight: {src['weight']}, lang: {src['language']}) ==="
                if article:
                    source_blocks.append(f"{header}\n{article[:2500]}")
                else:
                    source_blocks.append(f"{header}\n[Article not found for this stage]")

            weights_section = "\n".join(weight_lines)
            articles_section = "\n\n".join(source_blocks)
            canonical_list = ", ".join(all_known_sources)

            prompt = f"""Structure this cycling expert analysis for Stage {stage} Giro d'Italia 2026 into JSON.

SOURCE WEIGHTS (canonical names in parentheses; use canonical names in source_ratings output):
{weights_section}

{articles_section}

Return ONLY the JSON object below. No text before or after. No markdown fences.
{{
  "sources_consulted": ["<canonical names where article text was provided>"],
  "sources_not_found": ["<canonical names where '[Article not found for this stage]' was injected>"],
  "source_ratings": [
    {{
      "source": "tv2_axelgaard",
      "weight": 1.5,
      "ratings": [{{"rider": "Jonathan Milan", "stars": 5}}, {{"rider": "Paul Magnier", "stars": 4}}]
    }},
    {{
      "source": "feltet",
      "weight": 1.2,
      "ratings": [{{"rider": "Corbin Strong", "stars": 5}}]
    }}
  ],
  "key_signals": [
    {{"rider": "Name", "signal": "what was said", "direction": "up/down/neutral", "strength": "strong/moderate/weak"}}
  ],
  "stage_signals": {{
    "stage_type": "sprint"
  }},
  "weather": "weather summary if mentioned, else empty string",
  "stage_notes": "key tactical notes in 1-2 sentences",
  "summary": "two sentence summary"
}}

Rules:
- For source_ratings, emit ONE entry per source where article text was provided (not "[Article not found for this stage]"). List sources without article text in sources_not_found.
- Use these EXACT canonical source names (snake_case) for the `source` field: {canonical_list}
- direction: up = favoured beyond raw odds, down = risk not in odds, neutral = in line with odds
- strength: strong / moderate / weak
- Include every rider mentioned by any source's article in that source's source_ratings.ratings list
- TV2 / Feltet content is in Danish — translate and summarise each rider mention in English. Other-language sources similarly.
- Keep stage_notes and summary short (max 2 sentences each)

SOURCE-SPECIFIC EXTRACTION RULES (S17-INTEL substrate-quality fix 2026-05-16):

For sources that use explicit rating systems (stars, chain-rings, or other symbols
indicating tiered rider strength), prioritize the rating table/list over rider
mentions in prose discussion.

- Inner Ring (`inner_ring`) content is scraper-preprocessed (S17-INTEL
  Inner Ring scraper preprocessing, 2026-05-17): you receive ONLY the
  "The Contenders" section text — Stage Review, Route/Finish description,
  and Postcard historical sidebar have been stripped at the scraper layer
  before reaching this prompt. Inner Ring's chain-ring tier images are
  converted to plain-text markers in the article body:
    `[3-rings]` — top tier (highest probability contenders) → 5 stars
    `[2-rings]` — mid tier (strong contenders) → 4 stars
    `[1-ring]`  — lower tier (still contenders, lower probability) → 3 stars
  Expected substrate shape:
    "[prose paragraph naming today's top picks and breakaway candidates]
     [3-rings] Rider A, Rider B
     [2-rings] Rider C, Rider D, Rider E
     [1-ring] Rider F, Rider G, ..."
  Extract ratings ONLY from the tier-marked rider lists. Rider names
  appearing in the prose contender discussion (BEFORE the tier table) that
  ALSO appear in a tier-marked list use the tier-list rating. Rider names
  appearing ONLY in prose as counterexamples (e.g., "80kg riders like Max
  Walscheid stand no chance") are NOT contenders and should NOT be rated.
  If the `[3-rings]` / `[2-rings]` / `[1-ring]` markers are absent from the
  text (unexpected article shape), fall back to extracting riders explicitly
  identified in the Contenders prose as today's favourites; map prose
  strength signals to stars conservatively (4-5 for top picks, 3 for
  strong mentions, 2 for brief mentions).

- Touretappe (`touretappe`) uses literal asterisk symbols inline in the article
  body (e.g., "*** Milan ** Groenewegen * Vernon"). Map directly:
  *** → 5 stars, ** → 4 stars, * → 3 stars (typical 3-star max scale).
  Confirm the source's max-star convention from the article before extraction.

- Total-velo (`total_velo`) and TodayCycling (`todaycycling`) use star emoji
  symbols inline (e.g., ⭐⭐⭐ MAGNIER ⭐⭐ MILAN ⭐ VERNON). Map directly;
  max convention is typically 3 stars.

When a source has BOTH a rating table AND prose discussion, the rating table is
AUTHORITATIVE. Riders mentioned only in prose context (race recap, historical
references, narrative color commentary) are NOT extracted as rated for the
upcoming stage.

CURRENT STARTLIST CONSTRAINT (applies to ALL sources):

Only extract ratings for riders who are confirmed starters in the 2026 Giro
d'Italia. Ignore:
- Historical references to past winners (e.g., "this stage recalls Merckx's
  1972 win", "Argentin's style would have suited this profile", "channeling
  Pantani on this climb")
- Comparisons to retired riders, riders not on this year's startlist, or
  non-starters
- Color commentary that names riders not on the current startlist
- Stage profile descriptions that use historical rider names for narrative
  effect

If a source's preview text contains many historical references (common in
Cyclingstage hub-section content and SpazioCiclismo historical-context coverage),
extract only the riders explicitly identified as contenders for the UPCOMING
stage in the current year's race — not the historical / comparative names.
- key_signals coverage: generate 15-25 directional signals about specific riders for this stage, INDEPENDENT of how many sources provided articles. Even if some sources show "[Article not found for this stage]" placeholders, generate signals based on (a) available source content, (b) stage profile and known rider characteristics implied by stage_signals + general race context, (c) recent form signals if available in any source, (d) cross-stage continuity with prior stages. Coverage target: 15-25 key_signals per stage. Do NOT produce fewer than 10 signals even if source coverage is thin — generate from available evidence. This applies regardless of source-fetch-success ratio.
- stage_signals.stage_type — classify the stage into ONE of these categories:
  * "sprint" — flat or rolling, expected bunch sprint finish, minimal GC movement
  * "gc_day" — mountain stage with summit finish or hard climb in final 20km, GC time gaps expected to be significant (>30s)
  * "breakaway" — terrain favors a breakaway sticking (transitional mountain stages, classics-style profiles), GC peloton may finish together
  * "itt" — individual time trial
  * "hybrid_mountain" — mountain stage that doesn't fit cleanly into gc_day or breakaway (long descent after final climb, medium-mountain with multiple small climbs, etc.)
  Pick the closest single category. If genuinely ambiguous, prefer the more conservative (smaller-GC-movement) option."""

            # S17-INTEL Phase 1b (2026-05-16): max_tokens bumped 8000 → 16384
            # to accommodate 7-source extraction output. Phase 1a measured
            # 3-source state at ~3,900 output tokens (49% of 8000); linear
            # projection to 7-source state is ~9,000+ tokens, exceeding
            # 8000 cap. Haiku 4.5 supports up to 64K output tokens; 16384
            # is a defensive 2x headroom for Phase 1b/1c growth without
            # over-budgeting.
            return call_with_retry(lambda: client.messages.create(
                model='claude-haiku-4-5-20251001',
                max_tokens=16384,
                messages=[{'role': 'user', 'content': prompt}]
            ))

        # Run current-stage Haiku + forward n+1 + forward n+2 in parallel.
        # Forward Haiku helpers swallow their own errors (return None) so a
        # forward failure can't kill the current-stage write; current-stage
        # exceptions propagate to the outer try/except as before.
        # S17-β: forward prose now comes from the generic-preview HTTP fetch above,
        # not from a (now-removed) Playwright forward scrape.
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            current_future = executor.submit(_haiku_current)
            n1_future = executor.submit(
                _haiku_extract_forward, int(stage) + 1, n1_fwd.get('prose', ''), client
            )
            n2_future = executor.submit(
                _haiku_extract_forward, int(stage) + 2, n2_fwd.get('prose', ''), client
            )
            structure_message = current_future.result()
            n1_intel = n1_future.result()
            n2_intel = n2_future.result()

        raw = structure_message.content[0].text
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON object in gather-intel response: {raw[:200]}")
        result = json.loads(m.group())
        result['gathered_at'] = _dt.now().isoformat()
        result['stage'] = stage
        # S17-β: source field on current-stage intel block tracks whether the prose
        # came from Axelgaard's detailed Playwright scrape (or the generic URL's
        # redirect to it) versus the lighter generic preview page.
        result['source'] = current_source

        # S17-INTEL Phase 1a (2026-05-16): derive expert_stars per-rider ×
        # per-source matrix from Haiku's source_ratings output. Co-exists
        # with source_ratings (diagnostic value preserved); Phase 3
        # consumer math reads expert_stars only.
        try:
            _rider_data = _load_riders_merged()
            _active_riders_for_match = [r for r in _rider_data['riders']
                                        if not r.get('isOut') and r.get('status') != 'dns']
        except Exception as _e:
            _log(f"gather-intel: failed to load active_riders for derive_expert_stars: {_e}")
            _active_riders_for_match = []
        result['expert_stars'] = _derive_expert_stars(
            result.get('source_ratings', []),
            all_known_sources,
            _active_riders_for_match,
        )

        # Phase 1a token-budget verification logging — captures input/output
        # token usage so 13-source budget can be characterised before
        # Phase 1b/1c add real scrapers (which expand source_ratings output).
        try:
            _usage = getattr(structure_message, 'usage', None)
            if _usage:
                _log(
                    f"gather-intel haiku usage stage={stage} "
                    f"input_tokens={getattr(_usage, 'input_tokens', '?')} "
                    f"output_tokens={getattr(_usage, 'output_tokens', '?')} "
                    f"sources_wired={sum(1 for v in source_texts.values() if v)} "
                    f"sources_total={len(all_known_sources)} "
                    f"expert_stars_riders={len(result['expert_stars'])}"
                )
        except Exception as _e:
            _log(f"gather-intel: usage capture failed: {_e}")
        # S17-15: nest forward intel inside the inner intel dict so the dashboard's
        # /load-intel unwrap pattern finds it. Omit the key entirely when extraction
        # failed. S17-γ note: forward intel is now UI substrate only (rendered by
        # S17-α dashboard rectangles); the optimizer's build_forward_probabilities
        # no longer consumes it (architectural revert — see CLAUDE_SESSION).
        # S17-β: forward intel blocks gain `source` (axelgaard | generic_preview | both_failed)
        # tracking the final-URL inspection from fetch_tv2_generic_preview.
        if n1_intel is not None:
            result['forward_n1_intel'] = {
                'key_signals': n1_intel.get('key_signals', []),
                'stage_classification': n1_intel.get('stage_classification', ''),
                'source': n1_fwd.get('source', 'unknown'),
            }
        if n2_intel is not None:
            result['forward_n2_intel'] = {
                'key_signals': n2_intel.get('key_signals', []),
                'stage_classification': n2_intel.get('stage_classification', ''),
                'source': n2_fwd.get('source', 'unknown'),
            }
        intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
        with open(intel_path, 'w') as f:
            json.dump({'stage': stage, 'intel': result,
                       'gathered_at': _dt.now().isoformat()}, f, indent=2, ensure_ascii=False)
        _log(
            f"gather-intel saved to {intel_path} "
            f"source={current_source} "
            f"forward_n1={'present/'+n1_fwd.get('source','?') if n1_intel else 'absent'} "
            f"forward_n2={'present/'+n2_fwd.get('source','?') if n2_intel else 'absent'}"
        )
        result['_gathered_at'] = _dt.now().isoformat()
        return jsonify(result)
    except json.JSONDecodeError as e:
        _log(f"gather-intel JSON error: {e} | raw: {raw[:200]}")
        return jsonify({'status': 'error', 'message': str(e), 'raw': raw}), 500
    except Exception as e:
        _log(f"gather-intel error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Race standings (GC + jerseys, used by Sub-B1+ EV refinements) ────────────

@app.route('/gather-standings', methods=['POST', 'OPTIONS'])
def gather_standings():
    """Scrape TV2 GC + sprint + KOM + young-rider classifications, name-match
    against riders.json's active roster, write stage_N_standings.json.

    Source: tv2.dk/cykling/giro-d-italia/etapeN/klassement/{samlet,sprint,bjerg,ungdom}
    """
    if request.method == 'OPTIONS':
        return '', 204
    body = request.json or {}
    stage = body.get('stage', '?')
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from scraper import scrape_tv2_standings
        raw = scrape_tv2_standings(int(stage))

        scrape_errors = raw.get('errors', [])
        if scrape_errors:
            _log(f"gather-standings stage={stage} scrape errors: {scrape_errors}")
        sizes = {k: len(raw.get(k, [])) for k in
                 ('gc', 'points_classification', 'kom_classification', 'young_rider')}
        _log(f"gather-standings stage={stage} rows={sizes} errors={len(scrape_errors)}")

        rider_data = _load_riders_merged()
        active     = [r for r in rider_data['riders']
                      if not r.get('isOut') and r.get('status') != 'dns']

        warnings  = []
        seen_warn = set()  # dedupe across the four classifications

        def resolve(row, value_key):
            raw_name = row['name_raw']
            match = match_rider_name(raw_name, active)
            entry = {
                'rider_id': match.get('holdet_id') if match else None,
                'name':     match['name']          if match else raw_name,
                'name_raw': raw_name,
                'rank':     row['rank'],
            }
            entry[value_key] = row[value_key]
            if not match and raw_name not in seen_warn:
                warnings.append(raw_name)
                seen_warn.add(raw_name)
            return entry

        gc_rows     = [resolve(r, 'time_gap_seconds') for r in raw.get('gc', [])]
        points_rows = [resolve(r, 'points')           for r in raw.get('points_classification', [])]
        kom_rows    = [resolve(r, 'points')           for r in raw.get('kom_classification', [])]
        young_rows  = [resolve(r, 'time_gap_seconds') for r in raw.get('young_rider', [])]

        # Jerseys derived from rank-1 of each classification (explicitly stored
        # for downstream ergonomics).
        def _jersey(rows):
            if not rows:
                return None
            top = rows[0]
            return {'rider_id': top.get('rider_id'), 'name': top.get('name')}

        snapshot = {
            'stage':                  int(stage),
            'captured_at':            _dt.utcnow().isoformat() + 'Z',
            'source':                 'tv2',
            'gc':                     gc_rows,
            'points_classification':  points_rows,
            'kom_classification':     kom_rows,
            'young_rider':            young_rows,
            'jerseys': {
                'maglia_rosa':   _jersey(gc_rows),
                'ciclamino':     _jersey(points_rows),
                'azzurra':       _jersey(kom_rows),
                'maglia_bianca': _jersey(young_rows),
            },
            'name_match_warnings': warnings,
            'scrape_errors':       scrape_errors,
        }
        path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_standings.json')
        with open(path, 'w') as f:
            json.dump(snapshot, f, indent=2, ensure_ascii=False)
        _log(f"gather-standings stage={stage} saved to {path} warnings={len(warnings)}")
        return jsonify(snapshot)
    except Exception as e:
        _log(f"gather-standings error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Ingemann benchmark ───────────────────────────────────────────────────────

@app.route('/paste-expert-team', methods=['POST', 'OPTIONS'])
def paste_expert_team():
    """Source-agnostic expert team input via vision model.

    Replaces the Feltet scraper, which broke when Feltet stopped publishing
    the Girospillet column for Giro 2026 (S16-2 diagnosis). Accepts a pasted
    screenshot of any expert team view (Holdet's "view team", a tweet, etc.),
    extracts 8 riders + captain via Haiku, name-matches against the active
    roster, and writes the same stage_N_ingemann.json schema downstream
    /score-ingemann already consumes.
    """
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_ANTHROPIC:
        return jsonify({'status': 'error', 'message': 'anthropic package not installed'}), 500

    body       = request.json or {}
    stage      = body.get('stage', '?')
    image_data = body.get('image')
    media_type = body.get('media_type', 'image/png')
    if not image_data:
        return jsonify({'status': 'error', 'message': 'No image provided'}), 400

    raw = ''
    try:
        prompt = (
            "You are extracting a fantasy cycling team from a screenshot.\n\n"
            "Return ONLY valid JSON in this exact format:\n"
            '{\n'
            '  "riders": [\n'
            '    {"name": "<rider name as shown>", "price_kr": <integer kroner>},\n'
            '    ... 8 entries total\n'
            '  ],\n'
            '  "captain": "<name of the rider with the gold star icon>"\n'
            '}\n\n'
            "Rules:\n"
            "- Extract exactly 8 riders.\n"
            "- Names: copy them as shown in the image. Do not expand initials.\n"
            "  (e.g. \"J. Milan\" stays \"J. Milan\", \"Paul Magnier\" stays \"Paul Magnier\".)\n"
            "- Prices: convert European format like \"9.575.000\" to integer 9575000.\n"
            "  Ignore any price-change deltas like \"+575.000\" — those are not the price.\n"
            "- Captain: the rider with a gold/yellow STAR icon next to their price.\n"
            "  The green \"+\" square icon is NOT the captain marker — it appears\n"
            "  next to multiple riders.\n"
            "- Ignore non-rider visual elements like sponsor logos (e.g. MERIDA).\n"
            "- If you cannot identify exactly 8 riders or cannot identify a captain,\n"
            '  return {"error": "<reason>"} instead.\n'
            "- No prose, no markdown fences, no explanation. JSON only."
        )
        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        message = call_with_retry(lambda: client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2000,
            messages=[{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'media_type': media_type, 'data': image_data}},
                {'type': 'text',  'text': prompt},
            ]}],
        ))
        raw = message.content[0].text.strip()
        _log(f"paste-expert-team stage={stage} raw={raw[:400]}")
        raw = re.sub(r'^[\s]*```[a-z]*\s*', '', raw)
        raw = re.sub(r'\s*```[\s]*$', '', raw).strip()
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            return jsonify({'status': 'error',
                            'message': 'No JSON object in vision response — try a cleaner screenshot.',
                            'raw': raw}), 500
        parsed = json.loads(m.group())

        if 'error' in parsed:
            return jsonify({'status': 'error',
                            'message': f"Vision model could not extract team: {parsed['error']}",
                            'raw': raw}), 400

        rider_objs = parsed.get('riders', [])
        captain_raw = (parsed.get('captain') or '').strip()
        if len(rider_objs) != 8:
            return jsonify({'status': 'error',
                            'message': f'Expected 8 riders, got {len(rider_objs)}. Try a cleaner screenshot.',
                            'raw': raw}), 400
        if not captain_raw:
            return jsonify({'status': 'error',
                            'message': 'No captain identified — make sure the gold star icon is visible.',
                            'raw': raw}), 400

        # Name-match against active roster, collect warnings for unresolved names.
        rider_data = _load_riders_merged()
        active     = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

        resolved_riders = []   # what we write to the snapshot (canonical names if matched)
        display_riders  = []   # what we return to the UI (with prices)
        warnings = []
        for ro in rider_objs:
            raw_name = (ro.get('name') or '').strip()
            price    = ro.get('price_kr', 0)
            match = match_rider_name(raw_name, active)
            if match:
                resolved_riders.append(match['name'])
                display_riders.append({'name': match['name'], 'raw_name': raw_name, 'price_kr': price})
            else:
                resolved_riders.append(raw_name)
                display_riders.append({'name': raw_name, 'raw_name': raw_name, 'price_kr': price})
                warnings.append(f"Unmatched rider: {raw_name!r}")

        captain_match = match_rider_name(captain_raw, active)
        captain_resolved = captain_match['name'] if captain_match else captain_raw
        if not captain_match:
            warnings.append(f"Unmatched captain: {captain_raw!r}")

        snapshot = {
            'riders':       resolved_riders,
            'captain':      captain_resolved,
            'notes':        'Pasted expert team (image input)',
            'stage':        stage,
            'gathered_at':  _dt.now().isoformat(),
        }
        path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_ingemann.json')
        with open(path, 'w') as f:
            json.dump(snapshot, f, indent=2)
        _log(f"paste-expert-team stage={stage} matched={8 - len(warnings)}/8 captain_matched={bool(captain_match)}")

        return jsonify({
            'status':   'ok',
            'riders':   display_riders,
            'captain':  captain_resolved,
            'captain_raw': captain_raw,
            'warnings': warnings,
            'stage':    stage,
        })
    except json.JSONDecodeError as e:
        _log(f"paste-expert-team JSON error: {e}")
        return jsonify({'status': 'error', 'message': f'JSON parse error: {e}', 'raw': raw}), 500
    except Exception as e:
        _log(f"paste-expert-team error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/gather-ingemann', methods=['POST', 'OPTIONS'])
def gather_ingemann():
    if request.method == 'OPTIONS':
        return '', 204
    stage = request.json.get('stage')
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from scraper import scrape_ingemann_team
        raw_text = scrape_ingemann_team(int(stage))
        app.logger.info(f"Ingemann raw: {len(raw_text)} chars")
        _log(f"gather-ingemann stage={stage} chars={len(raw_text)}")

        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        message = call_with_retry(lambda: client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=1000,
            messages=[{'role': 'user', 'content': f"""Extract Ingemann's Holdet team from this Feltet.dk article for Stage {stage} Giro d'Italia 2026.

{raw_text[:3000]}

Return ONLY the JSON object below. No text before or after. No markdown fences.
{{"riders":["Rider Name 1","Rider Name 2","Rider Name 3","Rider Name 4","Rider Name 5","Rider Name 6","Rider Name 7","Rider Name 8"],"captain":"Rider Name","notes":"brief tactical notes"}}

Extract exactly 8 rider names and 1 captain. Use full rider names as they appear in the text."""}]
        ))
        raw = message.content[0].text
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON object found in Ingemann response: {raw[:200]}")
        result = json.loads(m.group())
        result['stage'] = stage
        result['gathered_at'] = _dt.now().isoformat()
        path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_ingemann.json')
        with open(path, 'w') as f:
            json.dump(result, f, indent=2)
        return jsonify(result)
    except json.JSONDecodeError as e:
        return jsonify({'status': 'error', 'message': str(e), 'raw': raw}), 500
    except Exception as e:
        _log(f"gather-ingemann error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/score-ingemann', methods=['POST', 'OPTIONS'])
def score_ingemann():
    if request.method == 'OPTIONS':
        return '', 204
    stage = request.json.get('stage')
    try:
        ingemann_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_ingemann.json')
        if not os.path.exists(ingemann_path):
            return jsonify({'status': 'error', 'message': 'Ingemann team not scraped yet'}), 400

        ingemann = json.load(open(ingemann_path))
        rider_names  = ingemann.get('riders', [])
        captain_name = ingemann.get('captain', '')

        rider_data    = _load_riders_merged()
        active        = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

        odds_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
        raw_odds  = json.load(open(odds_path)) if os.path.exists(odds_path) else {}
        odds = raw_odds.get('odds', raw_odds) if isinstance(raw_odds, dict) else raw_odds

        intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
        intel = json.load(open(intel_path)) if os.path.exists(intel_path) else {}

        from optimizer import (build_probabilities, simulate_stage,
                               load_stage_scoring, get_stage_config)
        scoring      = load_stage_scoring()
        stage_config = get_stage_config(stage, scoring)
        probs = build_probabilities(active, odds, intel, {}, stage_config=stage_config, scoring=scoring)

        team = []
        for name in rider_names:
            match = match_rider_name(name, active)
            if match:
                team.append(match)

        # Resolve captain to canonical roster name so simulate_stage's exact-match
        # at optimizer.py:1074 finds it (image paste may give "A. Vendrame").
        captain_match = match_rider_name(captain_name, active) if captain_name else None
        if captain_match:
            captain_name = captain_match['name']

        if len(team) != 8:
            return jsonify({
                'status': 'error',
                'message': f'Could only match {len(team)}/8 riders — check names',
                'matched': [r['name'] for r in team],
                'requested': rider_names,
            }), 400

        # S16-3: seed Plackett-Luce so Ingemann EV is stable across re-runs.
        # Seed varies per stage + per team so different inputs produce
        # different sample paths, but identical inputs are bit-identical.
        from optimizer import compute_seed as _compute_seed_opt
        sim_seed = _compute_seed_opt(stage, {'team': sorted(r['name'] for r in team),
                                             'captain': captain_name}, [], [], False)
        sim = simulate_stage(team, probs, captain_name, all_riders=active,
                             stage_config=stage_config, scoring=scoring,
                             seed=sim_seed)

        result = {
            'label':       "Ingemann's Benchmark",
            'strategy':    'ingemann',
            'description': 'Feltet.dk expert recommendation — Ingemann (previous Holdet winner)',
            'riders':      [{'name': r['name'], 'team': r.get('team', ''),
                             'price': r['price'], 'type': r.get('type', '')} for r in team],
            'captain':     {'name': captain_name, 'rationale': "Ingemann's pick"},
            'total_price': sum(r['price'] for r in team),
            'ev_estimate': sim['mean'],
            'ev_breakdown': sim['breakdown'],
            'cdf':         sim['cdf'],
            'forward':     {},
            'notes':       ingemann.get('notes', ''),
            'stage':       stage,
        }

        out_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_ingemann_scored.json')
        with open(out_path, 'w') as f:
            json.dump(result, f, indent=2)
        _log(f"score-ingemann stage={stage} ev={int(sim['mean'])}")
        return jsonify(result)
    except Exception as e:
        _log(f"score-ingemann error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/load-ingemann-scored', methods=['GET'])
def load_ingemann_scored():
    stage = request.args.get('stage')
    path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_ingemann_scored.json')
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify({})


@app.route('/current-team', methods=['GET'])
def current_team_endpoint():
    target_stage = request.args.get('target_stage', type=int, default=1)
    source_stage = max(1, target_stage - 1)
    path = os.path.join(SNAPSHOT_DIR, f'stage_{source_stage}_holdet.json')
    if not os.path.exists(path):
        return jsonify({'riders': [], 'stage': source_stage, 'found': False})

    snapshot = json.load(open(path))
    team_ids  = set(snapshot.get('team_composition', []))
    rider_data = _load_riders_merged()
    team = [r for r in rider_data['riders']
            if r['name'] in team_ids or str(r.get('holdet_id', '')) in team_ids]

    return jsonify({
        'riders':       team,
        'bank_balance': snapshot.get('bank_balance', 0),
        'captain':      snapshot.get('captain', ''),
        'stage':        source_stage,
        'found':        True,
    })


@app.route('/save-current-team', methods=['POST', 'OPTIONS'])
def save_current_team():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        data    = request.get_json(force=True)
        stage   = data.get('stage')
        team    = data.get('team', [])
        captain = data.get('captain', '')
        path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_holdet.json')
        existing = {}
        if os.path.exists(path):
            with open(path) as f:
                existing = json.load(f)
        existing['team_composition'] = team
        existing['captain']          = captain
        existing['stage']            = stage
        with open(path, 'w') as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
        return jsonify({'status': 'ok', 'team_size': len(team)})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/stage-results', methods=['GET'])
def stage_results():
    """Return scored results for the completed stage (target_stage - 1).
    Loads stage_{n}_results.json; returns {found: false} if absent."""
    target_stage = request.args.get('target_stage', type=int, default=1)
    completed    = target_stage - 1
    if completed < 1:
        return jsonify({'found': False})
    path = os.path.join(SNAPSHOT_DIR, f'stage_{completed}_results.json')
    if not os.path.exists(path):
        return jsonify({'found': False, 'completed_stage': completed})
    with open(path) as f:
        data = json.load(f)
    data['found'] = True
    data['completed_stage'] = completed
    return jsonify(data)


# ── Fetch stage results from Holdet ──────────────────────────────────────────

@app.route('/fetch-stage-results', methods=['POST', 'OPTIONS'])
def fetch_stage_results_endpoint():
    if request.method == 'OPTIONS':
        return '', 204
    body  = request.get_json(force=True) or {}
    stage = body.get('stage', 1)
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from fetch_riders import fetch_stage_results
        data = fetch_stage_results(int(stage))
        scored = data.get('scored', False)
        _log(f"fetch-stage-results stage={stage} scored={scored} riders={len(data.get('rider_results', []))}")
        data['found'] = scored
        data['completed_stage'] = stage
        return jsonify({'status': 'ok', 'found': scored, 'data': data})
    except SystemExit as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500
    except Exception as e:
        _log(f"fetch-stage-results error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Save weights ──────────────────────────────────────────────────────────────

@app.route('/sources-config', methods=['GET', 'OPTIONS'])
def sources_config():
    """S17-INTEL Phase 2 (2026-05-16): expose current expert_sources.yaml
    to dashboard for per-source controls + star-matrix rendering. Filters
    out deferred sources (scraper field starts with `deferred_`) so the
    UI shows only operationally-wired sources.

    Response shape: JSON array of source objects, each with name,
    canonical, weight, language, scraper, enabled. Order matches yaml
    order (Phase 1 source-list canonical ordering).
    """
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_YAML:
        return jsonify({'status': 'error', 'message': 'pyyaml not installed'}), 500
    try:
        with open(EXPERT_SOURCES) as f:
            config = yaml.safe_load(f) or {}
        sources = config.get('sources', []) or []
        visible = []
        for src in sources:
            scraper = src.get('scraper') or ''
            if scraper.startswith('deferred_'):
                continue
            visible.append({
                'name':      src.get('name'),
                'canonical': src.get('canonical'),
                'weight':    float(src.get('weight', 1.0)),
                'language':  src.get('language', ''),
                'scraper':   scraper,
                'enabled':   bool(src.get('enabled', True)),
            })
        return jsonify(visible)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/save-weights', methods=['POST', 'OPTIONS'])
def save_weights():
    """S17-INTEL Phase 2 (2026-05-16): hardened to preserve yaml fields
    (canonical / language / scraper) on weight/enabled updates. Phase 1a
    finding §7.4 noted the prior shape overwrote yaml with name+weight
    only, dropping the Phase 1a additions; this fix merges updates into
    the existing yaml structure.

    Accepts both payload shapes for backward compat:
      (a) legacy: {'weights': [{'name': '<display>', 'weight': 1.5}, ...]}
          — keyed by display name; weight-only update
      (b) new:    {'<canonical>': {'weight': 1.5, 'enabled': true}, ...}
          — keyed by canonical; weight + optional enabled toggle
      (c) new bare-weight: {'<canonical>': 1.5, ...}
          — convenience scalar variant of (b)
    """
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_YAML:
        return jsonify({'status': 'error', 'message': 'pyyaml not installed'}), 500
    try:
        body = request.get_json(force=True) or {}

        # Load existing yaml — every field other than weight/enabled is
        # preserved per source. Sources not mentioned in the payload pass
        # through unchanged.
        with open(EXPERT_SOURCES) as f:
            config = yaml.safe_load(f) or {}
        sources = config.get('sources', []) or []

        updated = []

        # Shape (a): legacy {'weights': [{'name', 'weight'}, ...]} — match by display name
        if isinstance(body, dict) and 'weights' in body and isinstance(body['weights'], list):
            by_name = {w.get('name'): w for w in body['weights'] if isinstance(w, dict)}
            for src in sources:
                if src.get('name') in by_name:
                    w = by_name[src['name']].get('weight')
                    if w is not None:
                        src['weight'] = round(float(w), 1)
                        updated.append(src.get('canonical', src.get('name')))
        else:
            # Shape (b)/(c): {<canonical>: <update>, ...}
            for src in sources:
                canonical = src.get('canonical')
                if canonical not in body:
                    continue
                update = body[canonical]
                if isinstance(update, (int, float)):
                    src['weight'] = round(float(update), 1)
                elif isinstance(update, dict):
                    if 'weight' in update and update['weight'] is not None:
                        src['weight'] = round(float(update['weight']), 1)
                    if 'enabled' in update:
                        src['enabled'] = bool(update['enabled'])
                updated.append(canonical)
                # name / canonical / language / scraper preserved by construction
                # (mutating other keys via this endpoint is intentionally not allowed)

        # Atomic write: tmpfile + rename so a mid-write interruption can't
        # corrupt expert_sources.yaml.
        tmp_path = EXPERT_SOURCES + '.tmp'
        with open(tmp_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False,
                      allow_unicode=True, sort_keys=False)
        os.replace(tmp_path, EXPERT_SOURCES)

        return jsonify({'status': 'ok', 'sources_updated': updated})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Snapshot (legacy) ─────────────────────────────────────────────────────────

@app.route('/snapshot', methods=['GET'])
def snapshot():
    try:
        stage = request.args.get('stage', type=int)
        if stage:
            path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_holdet.json')
            if not os.path.exists(path):
                return jsonify({'found': False, 'bank_balance': 50_000_000, 'team_composition': [], 'captain': ''})
            data = json.load(open(path))
            return jsonify({
                'found':            True,
                'bank_balance':     data.get('bank_balance', 50_000_000),
                'team_composition': data.get('team_composition', []),
                'captain':          data.get('captain', ''),
                'player_rank':      data.get('player_rank'),
                'player_points':    data.get('player_points'),
                'refreshed_at':     data.get('refreshed_at'),
            })
        # No stage param — canonical rider master list lives in
        # stage_1_holdet.json (per fetch_riders.py); later-stage snapshots
        # are per-stage stubs without a riders field (S17-27).
        path = os.path.join(SNAPSHOT_DIR, 'stage_1_holdet.json')
        if not os.path.exists(path):
            return jsonify({'status': 'no_snapshot'}), 404
        data = json.load(open(path))
        # S17-AFFINITY: apply terrain_affinity overrides at the load boundary
        # so the dashboard's loadRiders() sees merged values and deriveType()
        # re-classifies based on the override (e.g., Magnier sprint 0.55 → 0.88
        # flips Puncheur → Sprinter). Symmetric with the /riders endpoint.
        data['riders'] = _apply_affinity_overrides(data.get('riders', []))
        data['_filename'] = 'stage_1_holdet.json'
        return jsonify(data)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Data freshness (dashboard status display) ────────────────────────────────

@app.route('/data-freshness', methods=['GET'])
def data_freshness():
    """Returns metadata for the dashboard's under-Refresh-button freshness display:
       (a) most recently written holdet snapshot timestamp
       (b) most recent standings file (highest stage_N_standings.json that exists)
    Uses the in-file timestamp first, file mtime as fallback.
    """
    out = {'riders': None, 'standings': None}

    # (a) Most recent holdet snapshot. Prefer timestamp / refreshed_at fields,
    # fall back to filesystem mtime if neither is present.
    try:
        holdet_files = [f for f in os.listdir(SNAPSHOT_DIR) if f.endswith('_holdet.json')]
        if holdet_files:
            holdet_files.sort(
                key=lambda f: os.path.getmtime(os.path.join(SNAPSHOT_DIR, f)),
                reverse=True,
            )
            path = os.path.join(SNAPSHOT_DIR, holdet_files[0])
            d = json.load(open(path))
            ts = d.get('timestamp') or d.get('refreshed_at')
            if not ts:
                ts = _dt.utcfromtimestamp(os.path.getmtime(path)).isoformat() + 'Z'
            out['riders'] = {
                'timestamp':    ts,
                'rider_count':  len(d.get('riders', [])),
                'source_file':  holdet_files[0],
            }
    except Exception as e:
        _log(f"data-freshness riders error: {e}")

    # (b) Highest stage_N_standings.json present.
    try:
        for s in range(21, 0, -1):
            path = os.path.join(SNAPSHOT_DIR, f'stage_{s}_standings.json')
            if os.path.exists(path):
                d = json.load(open(path))
                out['standings'] = {
                    'stage':       d.get('stage', s),
                    'captured_at': d.get('captured_at'),
                    'source':      d.get('source', 'unknown'),
                }
                break
    except Exception as e:
        _log(f"data-freshness standings error: {e}")

    return jsonify(out)


if __name__ == '__main__':
    print('Dashboard: http://localhost:5050')
    app.run(port=5050, debug=False)
