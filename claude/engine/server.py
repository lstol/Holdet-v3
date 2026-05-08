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

# ── Load .env FIRST — before any anthropic instantiation ─────────────────────
from dotenv import load_dotenv

_HERE    = os.path.dirname(os.path.abspath(__file__))          # …/claude/engine
_ENV     = os.path.join(_HERE, '..', '..', '.env')             # repo root .env
load_dotenv(os.path.abspath(_ENV))                             # explicit abs path

_API_KEY = os.getenv('ANTHROPIC_API_KEY')
if not _API_KEY:
    raise RuntimeError("ANTHROPIC_API_KEY not set — check .env at repo root")

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
RIDERS_FILE       = os.path.join(BASE_DIR, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')
STAGE_SCORING_FILE= os.path.join(BASE_DIR, 'shared', 'data', 'stages', 'giro_2026', 'stage_scoring.json')
EXPERT_SOURCES    = os.path.join(BASE_DIR, 'claude', 'engine', 'expert_sources.yaml')
FETCH_RIDERS      = os.path.join(BASE_DIR, 'claude', 'engine', 'fetch_riders.py')
LOG_FILE          = os.path.join(BASE_DIR, 'claude', 'logs', 'server.log')

def _load_stage_scoring():
    if os.path.exists(STAGE_SCORING_FILE):
        with open(STAGE_SCORING_FILE) as f:
            return json.load(f)
    return {}


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


@app.after_request
def cors(r):
    r.headers['Access-Control-Allow-Origin'] = '*'
    r.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    r.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
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
    """Return riders from latest snapshot (live pricing) or riders.json (static)."""
    try:
        snapshots = sorted([f for f in os.listdir(SNAPSHOT_DIR) if f.endswith('_holdet.json')])
        if snapshots:
            with open(os.path.join(SNAPSHOT_DIR, snapshots[-1])) as f:
                data = json.load(f)
            return jsonify({
                'riders': data.get('riders', []),
                'timestamp': data.get('timestamp'),
                'source': 'snapshot',
                '_filename': snapshots[-1],
            })
    except Exception:
        pass
    try:
        with open(RIDERS_FILE) as f:
            data = json.load(f)
        return jsonify({'riders': data.get('riders', []), 'source': 'riders.json'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Refresh ───────────────────────────────────────────────────────────────────

@app.route('/refresh', methods=['POST', 'OPTIONS'])
def refresh():
    if request.method == 'OPTIONS':
        return '', 204
    try:
        result = subprocess.run(
            [sys.executable, FETCH_RIDERS],
            capture_output=True, text=True, timeout=60,
            cwd=BASE_DIR,
        )
        if result.returncode != 0:
            return jsonify({'status': 'error', 'message': result.stderr}), 500

        snapshots = sorted([f for f in os.listdir(SNAPSHOT_DIR) if f.endswith('_holdet.json')])
        rider_count = 0
        if snapshots:
            with open(os.path.join(SNAPSHOT_DIR, snapshots[-1])) as f:
                rider_count = len(json.load(f).get('riders', []))

        return jsonify({
            'status': 'ok',
            'timestamp': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ'),
            'rider_count': rider_count,
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Run optimizer ────────────────────────────────────────────────────────────

@app.route('/run-optimizer', methods=['POST', 'OPTIONS'])
def run_optimizer():
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

    rider_data = json.load(open(RIDERS_FILE))
    active_riders = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

    intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    intel_data = json.load(open(intel_path)).get('intel', {}) if os.path.exists(intel_path) else {}

    def sl(key):
        s = sliders.get(key, {})
        return (f"Sprint {s.get('sprint',0)}%  Hilly {s.get('hilly',0)}%  "
                f"Hard GC {s.get('hardgc',0)}%  Mixed {s.get('mixed',0)}%")

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


# ── Run Python optimizer ─────────────────────────────────────────────────────

@app.route('/run-optimizer-py', methods=['POST', 'OPTIONS'])
def run_optimizer_py():
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_OPTIMIZER:
        return jsonify({'status': 'error', 'message': 'optimizer.py not importable (numpy missing?)'}), 500

    data       = request.json or {}
    stage      = data.get('stage', 1)
    sliders    = data.get('sliders', {})
    force_in   = data.get('force_in', [])
    force_out  = data.get('force_out', [])

    # Load data files
    odds_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
    if os.path.exists(odds_path):
        raw_odds = json.load(open(odds_path))
        odds = raw_odds.get('odds', raw_odds) if isinstance(raw_odds, dict) else raw_odds
    else:
        odds = []

    rider_data    = json.load(open(RIDERS_FILE))
    active_riders = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

    intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    intel_data = json.load(open(intel_path)) if os.path.exists(intel_path) else {}

    # Read actual budget from Holdet snapshot; fall back to 50M
    snapshot_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_holdet.json')
    snapshot = json.load(open(snapshot_path)) if os.path.exists(snapshot_path) else {}
    budget = int(snapshot.get('bank_balance', 50_000_000))
    app.logger.info(f"run-optimizer-py stage={stage} budget={budget:,}")
    _log(f"run-optimizer-py stage={stage} budget={budget:,}")

    try:
        # Load stage scoring config
        scoring      = _load_stage_scoring()
        stage_config = scoring.get('stages', {}).get(str(stage), {})
        sprint_type  = stage_config.get('sprint_type', 'A')
        app.logger.info(
            f"run-optimizer-py stage={stage} sprint_type={sprint_type} "
            f"n_inter={stage_config.get('n_intermediate_sprints','?')} "
            f"climbs={len(stage_config.get('climbs',[]))}"
        )

        # Build probability distributions (annotates with sprint/jersey/gc/kom EVs)
        probs = build_probabilities(active_riders, odds, intel_data, sliders,
                                    stage_config=stage_config, scoring=scoring)

        # Generate candidate teams using actual budget
        candidates = generate_candidate_teams(active_riders, probs, force_in, force_out,
                                              budget=budget, stage_config=stage_config,
                                              scoring=scoring)

        if not candidates:
            return jsonify({'status': 'error', 'message': 'No valid teams found — check budget/constraints'}), 500

        # Simulate each team and build output
        teams_out = []
        for cand in candidates:
            team_riders = cand['riders']
            cap         = select_captain(team_riders, probs)
            sim         = simulate_stage(team_riders, probs, cap['name'],
                                         all_riders=active_riders,
                                         stage_config=stage_config, scoring=scoring)

            total_price = sum(r['price'] for r in team_riders)
            teams_out.append({
                'label':            cand['label'],
                'riders':           [r['name'] for r in team_riders],
                'total_price':      total_price,
                'ev_estimate':      int(sim['mean']),
                'ev_breakdown':     sim['breakdown'],
                'cdf':              sim['cdf'],
                'forward_pressure': cand['forward_pressure'],
                'rationale':        cand['rationale'],
            })

        # Sort by EV descending
        teams_out.sort(key=lambda t: t['ev_estimate'], reverse=True)

        # Overall best captain (from highest-EV team)
        best_team_riders = candidates[0]['riders']
        overall_captain  = select_captain(best_team_riders, probs)

        result = {
            'teams':        teams_out,
            'captain':      overall_captain,
            'tier_a':       [t['riders'][0] for t in teams_out[:2]],
            'budget':       budget,
            'stage_config': stage_config,
        }

        out_path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_claude_py.json')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        meta_path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_last_optimizer.json')
        with open(meta_path, 'w') as f:
            json.dump({'last': 'py'}, f)

        _log(f"run-optimizer-py stage={stage} teams={len(teams_out)}")
        return jsonify(result)

    except Exception as e:
        _log(f"run-optimizer-py error: {e}")
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

        for item in parsed:
            name = item.get('name', '')
            # Model sometimes returns field-specific keys (win_pct, top3_pct, top10_pct)
            # instead of the requested 'pct' key — accept both
            pct  = item.get('pct') or item.get(field_name) or item.get('win_pct') or 0
            if not name:
                continue
            if name in existing_map:
                existing_map[name][field_name] = pct
            else:
                # New rider — create row with only the pasted field populated
                existing_map[name] = {'name': name, field_name: pct}

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


# ── Gather intel ──────────────────────────────────────────────────────────────

@app.route('/gather-intel', methods=['POST', 'OPTIONS'])
def gather_intel():
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_ANTHROPIC:
        return jsonify({'status': 'error', 'message': 'anthropic package not installed'}), 500
    stage = request.json.get('stage', '?')
    raw = ''
    try:
        # Step 1: scrape all three sources with Playwright (zero API tokens)
        app.logger.info(f"Scraping intel for Stage {stage}...")
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from scraper import scrape_all_intel
        raw_sources = scrape_all_intel(int(stage))
        app.logger.info(
            f"TV2: {len(raw_sources['tv2'])} chars | "
            f"Feltet: {len(raw_sources['feltet'])} chars | "
            f"Inner Ring: {len(raw_sources['inner_ring'])} chars"
        )
        _log(f"gather-intel stage={stage} scraped tv2={len(raw_sources['tv2'])} feltet={len(raw_sources['feltet'])} inrng={len(raw_sources['inner_ring'])}")

        # Step 2: structure with single Haiku call (no web_search tool)
        sources = yaml.safe_load(open(EXPERT_SOURCES))['sources']
        source_weights = {s['name']: s['weight'] for s in sources}

        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        structure_message = call_with_retry(lambda: client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=4000,
            messages=[{'role': 'user', 'content': f"""Structure this cycling expert analysis for Stage {stage} Giro d'Italia 2026 into JSON.

SOURCE WEIGHTS:
- TV2/Axelgaard: {source_weights.get('Emil Axelgaard / TV2 Sport', 1.5)} (highest priority, content in Danish)
- Feltet.dk: {source_weights.get('Feltet.dk', 1.3)}
- Inner Ring: {source_weights.get('Inner Ring', 1.2)}

TV2/AXELGAARD (Danish — summarise in English):
{raw_sources['tv2'][:3000]}

FELTET.DK:
{raw_sources['feltet'][:3000]}

INNER RING:
{raw_sources['inner_ring'][:3000]}

Return ONLY this JSON, no markdown:
{{
  "sources_consulted": ["TV2/Axelgaard", "Feltet.dk", "Inner Ring"],
  "sources_not_found": [],
  "source_ratings": [
    {{
      "source": "TV2/Axelgaard",
      "weight": 1.5,
      "ratings": [
        {{"rider": "Jonathan Milan", "stars": 5}},
        {{"rider": "Paul Magnier", "stars": 4}}
      ]
    }}
  ],
  "key_signals": [
    {{"rider": "Name", "signal": "what was said", "direction": "up/down/neutral", "strength": "strong/moderate/weak"}}
  ],
  "weather": "weather summary",
  "stage_notes": "key tactical notes",
  "summary": "two sentence summary"
}}

direction: up = favoured beyond raw odds, down = risk not in odds, neutral = in line with odds.
strength: strong / moderate / weak.
Include every rider mentioned by any source.
TV2/Axelgaard content is in Danish — translate and summarise in English."""}]
        ))
        raw = structure_message.content[0].text.strip()
        if raw.startswith('```'):
            raw = re.sub(r'^```[a-z]*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
            raw = raw.strip()
        result = json.loads(raw)
        result['gathered_at'] = _dt.now().isoformat()
        result['stage'] = stage
        intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
        with open(intel_path, 'w') as f:
            json.dump({'stage': stage, 'intel': result,
                       'gathered_at': _dt.now().isoformat()}, f, indent=2, ensure_ascii=False)
        _log(f"gather-intel saved to {intel_path}")
        result['_gathered_at'] = _dt.now().isoformat()
        return jsonify(result)
    except json.JSONDecodeError as e:
        _log(f"gather-intel JSON error: {e} | raw: {raw[:200]}")
        return jsonify({'status': 'error', 'message': str(e), 'raw': raw}), 500
    except Exception as e:
        _log(f"gather-intel error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Save weights ──────────────────────────────────────────────────────────────

@app.route('/save-weights', methods=['POST', 'OPTIONS'])
def save_weights():
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_YAML:
        return jsonify({'status': 'error', 'message': 'pyyaml not installed'}), 500
    try:
        weights = request.get_json(force=True).get('weights', [])
        payload = {'sources': [{'name': w['name'], 'weight': round(float(w['weight']), 1)} for w in weights]}
        with open(EXPERT_SOURCES, 'w') as f:
            yaml.dump(payload, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ── Snapshot (legacy) ─────────────────────────────────────────────────────────

@app.route('/snapshot', methods=['GET'])
def snapshot():
    try:
        snapshots = sorted([f for f in os.listdir(SNAPSHOT_DIR) if f.endswith('_holdet.json')])
        if not snapshots:
            return jsonify({'status': 'no_snapshot'}), 404
        with open(os.path.join(SNAPSHOT_DIR, snapshots[-1])) as f:
            data = json.load(f)
        data['_filename'] = snapshots[-1]
        return jsonify(data)
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    print('Dashboard: http://localhost:5050')
    app.run(port=5050, debug=False)
