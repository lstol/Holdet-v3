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

BASE_DIR       = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SNAPSHOT_DIR   = os.path.join(BASE_DIR, 'shared', 'data', 'snapshots')
RIDERS_FILE    = os.path.join(BASE_DIR, 'shared', 'data', 'riders', 'giro_2026', 'riders.json')
EXPERT_SOURCES = os.path.join(BASE_DIR, 'claude', 'engine', 'expert_sources.yaml')
FETCH_RIDERS   = os.path.join(BASE_DIR, 'claude', 'engine', 'fetch_riders.py')
LOG_FILE       = os.path.join(BASE_DIR, 'claude', 'logs', 'server.log')


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
    odds = json.load(open(odds_path)) if os.path.exists(odds_path) else []

    rider_data = json.load(open(RIDERS_FILE))
    active_riders = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

    intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    intel_data = json.load(open(intel_path)).get('intel', {}) if os.path.exists(intel_path) else {}

    def sl(key):
        s = sliders.get(key, {})
        return (f"Sprint {s.get('sprint',0)}%  Hilly {s.get('hilly',0)}%  "
                f"Hard GC {s.get('hardgc',0)}%  Mixed {s.get('mixed',0)}%")

    riders_json = json.dumps(
        [{'name': r['name'], 'price': r.get('price', 0), 'team': r.get('team', '')}
         for r in active_riders],
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

AVAILABLE RIDERS (name, price, team):
{riders_json}

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
        message = client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=4000,
            messages=[{'role': 'user', 'content': prompt}],
        )
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
    odds = json.load(open(odds_path)) if os.path.exists(odds_path) else []

    rider_data    = json.load(open(RIDERS_FILE))
    active_riders = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

    intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    intel_data = json.load(open(intel_path)) if os.path.exists(intel_path) else {}

    try:
        # Build probability distributions
        probs = build_probabilities(active_riders, odds, intel_data, sliders)

        # Generate candidate teams (hard constraints enforced inside)
        candidates = generate_candidate_teams(active_riders, probs, force_in, force_out)

        if not candidates:
            return jsonify({'status': 'error', 'message': 'No valid teams found — check budget/constraints'}), 500

        # Simulate each team and build output
        teams_out = []
        for cand in candidates:
            team_riders = cand['riders']
            cap         = select_captain(team_riders, probs)
            sim         = simulate_stage(team_riders, probs, cap['name'], all_riders=active_riders)

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
            'teams':   teams_out,
            'captain': overall_captain,
            'tier_a':  [t['riders'][0] for t in teams_out[:2]],
        }

        out_path = os.path.join(BASE_DIR, 'claude', 'output', f'stage_{stage}_claude_py.json')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

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
        json.dump({'stage': stage, 'intel': intel}, f, indent=2, ensure_ascii=False)
    return jsonify({'status': 'ok'})


@app.route('/load-intel', methods=['GET'])
def load_intel():
    stage = request.args.get('stage')
    path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    if os.path.exists(path):
        with open(path) as f:
            data = json.load(f)
        return jsonify(data.get('intel', {}))
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


# ── Save / load odds ─────────────────────────────────────────────────────────

@app.route('/save-odds', methods=['POST', 'OPTIONS'])
def save_odds():
    if request.method == 'OPTIONS':
        return '', 204
    stage = request.json.get('stage')
    odds = request.json.get('odds')
    path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
    with open(path, 'w') as f:
        json.dump(odds, f, indent=2)
    return jsonify({'status': 'ok'})


@app.route('/load-odds', methods=['GET'])
def load_odds():
    stage = request.args.get('stage')
    path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_odds.json')
    if os.path.exists(path):
        with open(path) as f:
            return jsonify(json.load(f))
    return jsonify([])


# ── Parse odds image ─────────────────────────────────────────────────────────

@app.route('/parse-odds-image', methods=['POST', 'OPTIONS'])
def parse_odds_image():
    if request.method == 'OPTIONS':
        return '', 204
    if not HAS_ANTHROPIC:
        return jsonify({'status': 'error', 'message': 'anthropic package not installed'}), 500
    stage = request.json.get('stage', '?')
    image_data = request.json.get('image')
    media_type = request.json.get('media_type', 'image/png')
    raw = ''
    try:
        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2000,
            messages=[{
                'role': 'user',
                'content': [
                    {
                        'type': 'image',
                        'source': {'type': 'base64', 'media_type': media_type, 'data': image_data},
                    },
                    {
                        'type': 'text',
                        'text': (
                            f"These are Oddschecker odds for Stage {stage} Giro d'Italia 2026. "
                            'Each row is a rider. Columns are different bookmakers showing decimal odds. '
                            'For each rider: calculate the average of all visible decimal odds across all bookmakers, '
                            'then convert to implied win probability: win_pct = 100 / avg_odds. '
                            'Return ONLY a JSON array, no preamble, no markdown, no code fences: '
                            '[{"name": "Rider Name", "win_pct": 5.2, "top3_pct": null}] '
                            'sorted by win_pct descending. Include only riders where win_pct >= 1.0.'
                        ),
                    },
                ],
            }],
        )
        raw = message.content[0].text.strip()
        _log(f"parse-odds-image stage={stage} raw={raw[:300]}")
        if raw.startswith('```'):
            raw = re.sub(r'^```[a-z]*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
            raw = raw.strip()
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        if m:
            raw = m.group(0)
        return jsonify(json.loads(raw))
    except json.JSONDecodeError as e:
        _log(f"parse-odds-image JSON error: {e}")
        return jsonify({'status': 'error', 'message': str(e), 'raw': raw}), 500
    except Exception as e:
        _log(f"parse-odds-image error: {e}")
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
        client = anthropic.Anthropic(api_key=os.getenv('ANTHROPIC_API_KEY'))

        # Load sources from yaml, sorted by weight descending
        sources = yaml.safe_load(open(EXPERT_SOURCES))['sources']
        sources_sorted = sorted(sources, key=lambda x: x['weight'], reverse=True)

        source_instructions = '\n'.join([
            f"{i+1}. {s['name']} (weight {s['weight']}): "
            f"Search \"{s['name'].split('/')[0].strip()} Giro 2026 stage {stage}\" "
            f"and read whatever you find from this source."
            for i, s in enumerate(sources_sorted)
        ])

        # Step 1 — gather raw intel via web search, one query per source
        search_message = call_with_retry(lambda: client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=3000,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            messages=[{'role': 'user', 'content': f"""Search for Stage {stage} Giro d'Italia 2026 expert analysis.

You MUST search for each of these sources separately and in order:
{source_instructions}

Special instructions:
- Emil Axelgaard / TV2: search in Danish. URL pattern: sport.tv2.dk/cykling/YYYY-MM-DD-axelgaards-optakt-til-{stage}-etape-af-giro-ditalia. Read and summarize in English.
- The Inner Ring: search "inrng.com giro 2026 stage {stage}"
- VeloNews: search "velonews.com giro 2026 stage {stage} preview"
- CyclingNews: search "cyclingnews.com giro 2026 stage {stage} preview"
- ProCyclingStats: search "procyclingstats giro 2026 stage {stage}"
- FirstCycling: search "firstcycling giro 2026 stage {stage}"

For each source found, note which source it came from.
If a source is unavailable or paywalled, note it as "not found" and continue.
Collect ALL rider mentions, team tactics, weather, and finish analysis from ALL sources.
Return detailed prose — do not summarize yet, collect everything."""}],
        ))
        raw_intel = ' '.join(b.text for b in search_message.content if b.type == 'text')
        _log(f"gather-intel stage={stage} raw_intel={raw_intel[:300]}")

        sources_list_str = ', '.join([f"{s['name']} ({s['weight']})" for s in sources_sorted])

        # Step 2 — structure into JSON (Haiku: small input, no search tool)
        structure_message = call_with_retry(lambda: client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=4000,
            messages=[{'role': 'user', 'content': f"""Convert this raw cycling analysis into structured JSON.

Sources searched (by weight): {sources_list_str}

Raw analysis:
{raw_intel}

Return ONLY this JSON, no markdown:
{{
  "sources_consulted": ["source name", ...],
  "sources_not_found": ["source name", ...],
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
  "stage_notes": "tactical notes",
  "summary": "two sentence summary"
}}

Include every rider mentioned by any source.
Attribute star ratings per source — if a source did not mention a rider, omit them from that source's ratings.
Star scale: favourite=5, strong contender=4, contender=3, outside chance=2, mention only=1.
direction: up = favoured beyond raw odds, down = risk not in odds, neutral = in line with odds."""}],
        ))
        raw = structure_message.content[0].text.strip()
        _log(f"gather-intel stage={stage} structured={raw[:200]}")
        if raw.startswith('```'):
            raw = re.sub(r'^```[a-z]*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
            raw = raw.strip()
        result = json.loads(raw)
        intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
        with open(intel_path, 'w') as f:
            json.dump({'stage': stage, 'intel': result}, f, indent=2, ensure_ascii=False)
        _log(f"gather-intel saved to {intel_path}")
        return jsonify(result)
    except json.JSONDecodeError as e:
        _log(f"gather-intel JSON error: {e}")
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
