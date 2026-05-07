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

from flask import Flask, jsonify, request, send_from_directory
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env'))

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
        client = anthropic.Anthropic()
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
    source_list = 'TV2/Axelgaard (1.5), Inner Ring (1.2), VeloNews (1.0), CyclingNews (1.0), ProCyclingStats (0.8), FirstCycling (0.8)'
    if HAS_YAML:
        try:
            with open(EXPERT_SOURCES) as f:
                sources = yaml.safe_load(f)
            source_list = ', '.join(
                f"{s['name']} (weight {s['weight']})" for s in sources.get('sources', [])
            )
        except Exception:
            pass
    try:
        client = anthropic.Anthropic()
        message = client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=2000,
            tools=[{'type': 'web_search_20250305', 'name': 'web_search'}],
            messages=[{
                'role': 'user',
                'content': (
                    f"Search and summarize expert analysis for Stage {stage} Giro d'Italia 2026 "
                    f'from these sources weighted by importance: {source_list}. '
                    'Summarize as concise bullet points covering: who is favoured, team tactics, '
                    'weather, road conditions, any late changes. Decision-relevant only, no fluff.'
                ),
            }],
        )
        raw = ''
        for block in message.content:
            if block.type == 'text':
                raw += block.text
        return jsonify({'intel': raw.strip()})
    except Exception as e:
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
