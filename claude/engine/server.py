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

# ── Load .env FIRST — before any anthropic instantiation ─────────────────────
from dotenv import load_dotenv

_HERE    = os.path.dirname(os.path.abspath(__file__))          # …/claude/engine
_ENV     = os.path.join(_HERE, '..', '..', '.env')             # repo root .env
load_dotenv(os.path.abspath(_ENV), override=True)              # explicit abs path; override=True so shell env blanks don't win

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


def _ascii_fold(s: str) -> str:
    """NFKD-decompose, drop combining marks, lowercase. So 'González' → 'gonzalez',
    'Tjøtta' → 'tjotta'. Used by match_rider_name so ASCII-only paste input
    (e.g. vision OCR dropping accents) still matches accented roster names."""
    nfkd = unicodedata.normalize('NFKD', s)
    return ''.join(c for c in nfkd if not unicodedata.combining(c)).lower()


# Bidirectional nickname / formal-expansion aliases. Used when the matcher's
# structural rules can't bridge a source-vs-canonical gap (e.g. TV2 publishes
# Spanish riders' formal-name expansions; riders.json carries the nickname).
# Keys/values are ASCII-folded. The reverse direction is added at module load
# so a query in either form resolves the other.
# If this grows past ~10 entries, lift to a dedicated aliases.json file.
_NICKNAME_ALIASES_RAW = {
    "juanpe lopez": "juan pedro lopez",  # roster: "Juanpe Lopez", TV2: "Juan Pedro Lopez"
}
_NICKNAME_ALIASES: dict = {}
for _a, _b in _NICKNAME_ALIASES_RAW.items():
    _NICKNAME_ALIASES[_a] = _b
    _NICKNAME_ALIASES[_b] = _a


def match_rider_name(query: str, roster: list):
    """Match a free-form rider name against a roster of {'name': ...} dicts.
    Returns the matched rider dict or None.

    Resolution order (first single-match wins; multi-match returns None):
      1. Exact accent-/case-folded equality, alias-aware
      2. Initial+lastname  ('J. Milan' → 'Jonathan Milan')
      3. Rule X: first-word AND last-word match  (drops middle names)
                 ('Einer Rubio' → 'Einer Augusto Rubio')
      4. Rule Y: every query word appears as a complete whitespace-delimited
                 word in the rider name  (handles missing-first / extra-middle)
                 ('Thomas Silva' → 'Guillermo Thomas Silva')
      5. Last-word-of-query == last-word-of-rider
                 ('Milan' → 'Jonathan Milan')

    All comparisons are ASCII-folded.
    """
    q = query.strip()
    if not q:
        return None
    qf      = _ascii_fold(q)
    qparts  = qf.split()
    qf_alt  = _NICKNAME_ALIASES.get(qf)  # alternative form, or None

    # 1. Exact (alias-aware)
    def _matches(rf: str) -> bool:
        return rf == qf or (qf_alt is not None and rf == qf_alt)
    exact = next((r for r in roster if _matches(_ascii_fold(r['name']))), None)
    if exact:
        return exact

    # 2. Initial+lastname (e.g. "J. Milan")
    parts = q.split()
    if len(parts) >= 2 and len(parts[0]) <= 3 and parts[0].endswith('.'):
        initial  = _ascii_fold(parts[0][0])
        lastname = _ascii_fold(' '.join(parts[1:]))
        candidates = [
            r for r in roster
            if _ascii_fold(r['name']).endswith(lastname)
            and _ascii_fold(r['name'].split()[0][0]) == initial
        ]
        if len(candidates) == 1:
            return candidates[0]

    # 3. Rule X: first-word AND last-word match (handles middle-name drops)
    if len(qparts) >= 2:
        qf_first, qf_last = qparts[0], qparts[-1]
        candidates = [
            r for r in roster
            if _ascii_fold(r['name'].split()[0])  == qf_first
            and _ascii_fold(r['name'].split()[-1]) == qf_last
        ]
        if len(candidates) == 1:
            return candidates[0]

    # 4. Rule Y: every query word is a whole word in the rider name
    if len(qparts) >= 2:
        candidates = [
            r for r in roster
            if all(qw in _ascii_fold(r['name']).split() for qw in qparts)
        ]
        if len(candidates) == 1:
            return candidates[0]

    # 5. Last-word-of-query == last-word-of-rider
    # (Pre-fix bug: compared full folded query against rider's last word —
    # 'einer rubio' could never equal 'rubio'. Existing callers route through
    # rules 1–2 with single-word or initial-form queries, so the bug was
    # latent for them; multi-word "first last" queries from TV2 surfaced it.)
    qf_last_word = qparts[-1] if qparts else qf
    candidates = [r for r in roster if _ascii_fold(r['name']).split()[-1] == qf_last_word]
    if len(candidates) == 1:
        return candidates[0]
    return None


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

def _latest_stage():
    """Return the most recently active stage number based on today's date."""
    stages_path = os.path.join(BASE_DIR, 'shared', 'data', 'stages', 'giro_2026', 'stages_giro2026.json')
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

        snapshots = sorted([f for f in os.listdir(SNAPSHOT_DIR) if f.endswith('_holdet.json')])
        rider_count = 0
        if snapshots:
            with open(os.path.join(SNAPSHOT_DIR, snapshots[-1])) as f:
                data = json.load(f)
                rider_count = len(data.get('riders', []))

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

    rider_data = json.load(open(RIDERS_FILE))
    active_riders = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

    intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    intel_data = json.load(open(intel_path)).get('intel', {}) if os.path.exists(intel_path) else {}

    def sl(key):
        s = sliders.get(key, {})
        return (f"Bunch sprint {s.get('bunch_sprint',0)}%  "
                f"Reduced sprint {s.get('reduced_sprint',0)}%  "
                f"Breakaway {s.get('breakaway',0)}%  GC {s.get('gc',0)}%")

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

    rider_data    = json.load(open(RIDERS_FILE))
    active_riders = [r for r in rider_data['riders'] if not r.get('isOut') and r.get('status') != 'dns']

    intel_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_intel.json')
    intel_data = json.load(open(intel_path)) if os.path.exists(intel_path) else {}

    # Bank balance still comes from the target-stage holdet snapshot.
    snapshot_path = os.path.join(SNAPSHOT_DIR, f'stage_{stage}_holdet.json')
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
        probs_current = build_probabilities(
            active_riders, odds, intel_data, sliders.get('n1', {}),
            stage_config=stage_config, scoring=scoring,
            use_race_type=use_race_type,
        )

        # Forward stages: slider-based inference only (no odds)
        probs_n1 = build_forward_probabilities(active_riders, sliders.get('n2', {}))
        probs_n2 = build_forward_probabilities(active_riders, sliders.get('n3', {}))

        teams = generate_candidate_teams(
            active_riders, probs_current,
            probs_n1, probs_n2,
            force_in, force_out, budget,
            stage_config, scoring, active_riders,
            current_team=current_team if current_team else None,
            seed=base_seed,
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
        tv2_w    = source_weights.get('Emil Axelgaard / TV2 Sport', 1.5)
        feltet_w = source_weights.get('Feltet.dk', 1.3)
        structure_message = call_with_retry(lambda: client.messages.create(
            model='claude-haiku-4-5-20251001',
            max_tokens=8000,
            messages=[{'role': 'user', 'content': f"""Structure this cycling expert analysis for Stage {stage} Giro d'Italia 2026 into JSON.

SOURCE WEIGHTS:
- TV2/Axelgaard: {tv2_w} (highest priority, content in Danish)
- Feltet.dk: {feltet_w}

TV2/AXELGAARD (Danish — summarise in English):
{raw_sources['tv2'][:2500]}

FELTET.DK:
{raw_sources['feltet'][:2500]}

INNER RING (background context only, no weight):
{raw_sources['inner_ring'][:1500]}

Return ONLY the JSON object below. No text before or after. No markdown fences.
{{
  "sources_consulted": ["TV2/Axelgaard", "Feltet.dk"],
  "sources_not_found": [],
  "source_ratings": [
    {{
      "source": "TV2/Axelgaard",
      "weight": {tv2_w},
      "ratings": [{{"rider": "Jonathan Milan", "stars": 5}}, {{"rider": "Paul Magnier", "stars": 4}}]
    }},
    {{
      "source": "Feltet.dk",
      "weight": {feltet_w},
      "ratings": [{{"rider": "Corbin Strong", "stars": 5}}]
    }}
  ],
  "key_signals": [
    {{"rider": "Name", "signal": "what was said", "direction": "up/down/neutral", "strength": "strong/moderate/weak"}}
  ],
  "weather": "weather summary if mentioned, else empty string",
  "stage_notes": "key tactical notes in 1-2 sentences",
  "summary": "two sentence summary"
}}

Rules:
- direction: up = favoured beyond raw odds, down = risk not in odds, neutral = in line with odds
- strength: strong / moderate / weak
- Include every rider mentioned by either source in source_ratings
- TV2 content is in Danish — translate and summarise each rider mention in English
- Keep stage_notes and summary short (max 2 sentences each)"""}]
        ))
        raw = structure_message.content[0].text
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            raise ValueError(f"No JSON object in gather-intel response: {raw[:200]}")
        result = json.loads(m.group())
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

        rider_data = json.load(open(RIDERS_FILE))
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
        rider_data = json.load(open(RIDERS_FILE))
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

        rider_data    = json.load(open(RIDERS_FILE))
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
    rider_data = json.load(open(RIDERS_FILE))
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
        # No stage param — return latest snapshot (legacy behaviour)
        snapshots = sorted([f for f in os.listdir(SNAPSHOT_DIR) if f.endswith('_holdet.json')])
        if not snapshots:
            return jsonify({'status': 'no_snapshot'}), 404
        with open(os.path.join(SNAPSHOT_DIR, snapshots[-1])) as f:
            data = json.load(f)
        data['_filename'] = snapshots[-1]
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
