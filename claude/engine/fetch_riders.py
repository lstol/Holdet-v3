"""
engine/siv/fetch_riders.py — Phase 2b rider enrichment

Fetches live rider data from holdet.dk API and enriches
data/riders/riders_giro2026_v1.json with real holdet_id, prices,
and status fields. Also writes price snapshot and team state files.

Usage:
    python engine/siv/fetch_riders.py [--team] [--dry-run]

Options:
    --team      Also fetch team state from HTML page (slower)
    --dry-run   Fetch and match but do not write files
"""

import argparse
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
RIDERS_FILE          = ROOT / "shared" / "data" / "riders"    / "giro_2026" / "riders.json"
PRICES_SNAPSHOT_FILE = ROOT / "shared" / "data" / "riders"    / "giro_2026" / "prices_stage0_pre.json"
TEAM_STATE_FILE      = ROOT / "shared" / "data" / "snapshots" / "team_state_pre_race.json"
SNAPSHOT_FILE        = ROOT / "shared" / "data" / "snapshots" / "stage_1_holdet.json"

BASE_URL = "https://nexus-app-fantasy-fargate.holdet.dk"

FUZZY_THRESHOLD = 0.82  # below this score → "uncertain match" warning


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _norm(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(ascii_name.lower().split())


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _best_match(api_name: str, local_names: list[str]) -> tuple[str | None, float]:
    """Return (best_local_name, score). Returns (None, 0) if no candidates."""
    if not local_names:
        return None, 0.0
    scored = [(_similarity(api_name, n), n) for n in local_names]
    score, name = max(scored)
    return name, score


def _cookie() -> str:
    cookie = os.getenv("HOLDET_COOKIE", "")
    if not cookie:
        sys.exit(
            "ERROR: HOLDET_COOKIE not set.\n"
            "  1. Open Chrome → holdet.dk → log in\n"
            "  2. F12 → Network → Fetch/XHR\n"
            "  3. Navigate to the rider market\n"
            "  4. Find a 'players' request → Headers → copy Cookie value\n"
            "  5. Add to .env:  HOLDET_COOKIE=<paste here>"
        )
    return cookie


# ---------------------------------------------------------------------------
# Step 1 — Fetch all riders from API
# ---------------------------------------------------------------------------

def fetch_riders_api(game_id: str, cookie: str) -> list[dict]:
    url = f"{BASE_URL}/api/games/{game_id}/players"
    resp = requests.get(url, headers={"Cookie": cookie}, timeout=15)
    if resp.status_code == 401:
        sys.exit("ERROR: 401 Unauthorized — cookie expired. Refresh from DevTools.")
    if resp.status_code == 403:
        sys.exit(
            "ERROR: 403 Forbidden — AWSALB token is IP-sticky.\n"
            "  Capture the cookie from the same machine/network you are running this on."
        )
    resp.raise_for_status()
    data = resp.json()

    persons = data["_embedded"]["persons"]
    teams = data["_embedded"]["teams"]

    riders = []
    for item in data["items"]:
        pid = str(item["personId"])
        tid = str(item["teamId"])
        person = persons.get(pid, {})
        team = teams.get(tid, {})
        riders.append({
            "holdet_id": item["id"],
            "name": f"{person.get('firstName', '')} {person.get('lastName', '')}".strip(),
            "team": team.get("name", "Unknown"),
            "team_abbr": team.get("abbreviation", "???"),
            "startPrice": item.get("startPrice", item.get("price", 0)),
            "price": item["price"],
            "points": item.get("points") or 0,
            "isOut": item.get("isOut", False),
            "isInjured": item.get("isInjured", False),
            "isEliminated": item.get("isEliminated", False),
            "captainPopularity": item.get("captainPopularity") or 0.0,
            "owners": item.get("owners") or 0,
        })
    return riders


# ---------------------------------------------------------------------------
# Step 2 — Enrich local riders file
# ---------------------------------------------------------------------------

def enrich_riders(api_riders: list[dict], dry_run: bool = False) -> dict:
    local_data = json.loads(RIDERS_FILE.read_text())
    local_riders = local_data["riders"]

    local_by_name: dict[str, int] = {r["name"]: i for i, r in enumerate(local_riders)}
    local_norm_map: dict[str, str] = {_norm(n): n for n in local_by_name}

    matched = []
    uncertain = []
    unmatched_api = []

    for api_r in api_riders:
        api_name = api_r["name"]
        api_norm = _norm(api_name)

        # Exact normalised match
        if api_norm in local_norm_map:
            local_name = local_norm_map[api_norm]
            idx = local_by_name[local_name]
            _apply_market_fields(local_riders[idx], api_r)
            matched.append(api_name)
            continue

        # Fuzzy match
        local_name, score = _best_match(api_name, list(local_by_name.keys()))
        if local_name and score >= FUZZY_THRESHOLD:
            idx = local_by_name[local_name]
            _apply_market_fields(local_riders[idx], api_r)
            if score < 0.95:
                uncertain.append((api_name, local_name, round(score, 3)))
            else:
                matched.append(api_name)
        else:
            unmatched_api.append(api_r)

    # Initial build: filter to active riders only (establishes the locked set)
    # Update runs: refresh market data for the locked set — never add, never remove
    already_populated = any(r.get("holdet_id") for r in local_riders)
    if already_populated:
        offered = [r for r in local_riders if r.get("holdet_id")]
    else:
        offered = [r for r in local_riders if r.get("holdet_id") and not r.get("isEliminated") and r.get("status") != "dns"]
    local_data["riders"] = offered
    local_data["meta"]["rider_count"] = len(offered)
    local_data["meta"]["enriched_at"] = datetime.now(timezone.utc).isoformat()

    _print_summary(matched, uncertain, unmatched_api, [], len(offered))

    if not dry_run:
        RIDERS_FILE.write_text(json.dumps(local_data, ensure_ascii=False, indent=2))
        print(f"\n✓ Written: {RIDERS_FILE}")

    return local_data


def _apply_market_fields(local_rider: dict, api_rider: dict) -> None:
    local_rider["holdet_id"] = api_rider["holdet_id"]
    local_rider["startPrice"] = api_rider["startPrice"]
    local_rider["price"] = api_rider["price"]
    local_rider["status"] = "dns" if api_rider["isOut"] else "active"
    local_rider["isInjured"] = api_rider["isInjured"]
    local_rider["isEliminated"] = api_rider["isEliminated"]
    local_rider["captainPopularity"] = api_rider["captainPopularity"]
    local_rider["owners"] = api_rider["owners"]


def _make_stub(api_rider: dict) -> dict:
    """Minimal stub for an API rider not found in local file."""
    return {
        "rider_id": "_".join(_norm(api_rider["name"]).split()),
        "name": api_rider["name"],
        "team": api_rider["team"],
        "nationality": "UNK",
        "age": None,
        "data_version": "v1_api_stub",
        "holdet_id": api_rider["holdet_id"],
        "startPrice": api_rider["startPrice"],
        "price": api_rider["price"],
        "status": "dns" if api_rider["isOut"] else "active",
        "isInjured": api_rider["isInjured"],
        "isEliminated": api_rider["isEliminated"],
        "captainPopularity": api_rider["captainPopularity"],
        "owners": api_rider["owners"],
        "provenance": {"source": "holdet_api_live", "retrieved_at": datetime.now(timezone.utc).isoformat()},
    }


def _print_summary(matched, uncertain, unmatched_api, no_id, total):
    print("\n" + "=" * 60)
    print(f"ENRICHMENT SUMMARY — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 60)
    print(f"  Exact + confident matches : {len(matched)}")
    print(f"  Uncertain fuzzy matches   : {len(uncertain)}")
    print(f"  New stubs from API        : {len(unmatched_api)}")
    print(f"  Local riders without ID   : {len(no_id)}")
    print(f"  Total riders in file      : {total}")

    if uncertain:
        print("\n⚠  UNCERTAIN MATCHES (verify manually):")
        for api_name, local_name, score in uncertain:
            print(f"    {score:.3f}  API='{api_name}'  →  LOCAL='{local_name}'")

    if no_id:
        print(f"\nℹ  {len(no_id)} riders in local file have no holdet_id")
        print("   (they are in the Giro startlist but not offered by holdet.dk)")
        if len(no_id) <= 20:
            for n in no_id:
                print(f"    - {n}")
        else:
            for n in no_id[:10]:
                print(f"    - {n}")
            print(f"    … and {len(no_id) - 10} more")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Step 3 — Write price snapshot
# ---------------------------------------------------------------------------

def write_price_snapshot(api_riders: list[dict], dry_run: bool = False) -> None:
    snapshot = {
        "snapshot_type": "pre_race",
        "stage": 0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prices": [
            {
                "holdet_id": r["holdet_id"],
                "name": r["name"],
                "team": r["team"],
                "price": r["price"],
                "startPrice": r["startPrice"],
            }
            for r in sorted(api_riders, key=lambda x: x["holdet_id"])
        ],
    }
    if not dry_run:
        PRICES_SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
        print(f"✓ Written: {PRICES_SNAPSHOT_FILE}")
    else:
        print(f"  [dry-run] Would write price snapshot with {len(api_riders)} riders")


# ---------------------------------------------------------------------------
# Step 4 — Write stage snapshot (shared/data/snapshots/stage_1_holdet.json)
# ---------------------------------------------------------------------------

def write_stage_snapshot(enriched_data: dict, dry_run: bool = False) -> None:
    snapshot = {
        "stage_number": 1,
        "snapshot_type": "pre_race",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "riders": [
            {
                "holdet_id": r.get("holdet_id"),
                "name": r["name"],
                "team": r.get("team", ""),
                "price": r.get("price", 0),
                "startPrice": r.get("startPrice", 0),
                "isOut": r.get("isEliminated", False) or r.get("status") == "dns",
                "isInjured": r.get("isInjured", False),
                "terrain_affinity": r.get("terrain_affinity", {}),
            }
            for r in enriched_data.get("riders", [])
        ],
    }
    if not dry_run:
        SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
        SNAPSHOT_FILE.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2))
        print(f"✓ Written: {SNAPSHOT_FILE}")
    else:
        print(f"  [dry-run] Would write stage snapshot with {len(snapshot['riders'])} riders")


# ---------------------------------------------------------------------------
# Step 5 — Fetch team state (HTML scraping)
# ---------------------------------------------------------------------------

def fetch_team_state(cartridge: str, fantasy_team_id: str, cookie: str, dry_run: bool = False) -> None:
    url = f"{BASE_URL}/da/{cartridge}/me/fantasyteams/{fantasy_team_id}"
    print(f"\nFetching team page: {url}")
    resp = requests.get(url, headers={"Cookie": cookie}, timeout=20)
    if resp.status_code in (401, 403):
        print(f"  ✗ HTTP {resp.status_code} — cookie issue. Skipping team state fetch.")
        return
    resp.raise_for_status()

    html = resp.text
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)', html, re.DOTALL)

    team_data = None
    for chunk in chunks:
        if "initialLineup" not in chunk:
            continue
        try:
            raw = chunk.encode().decode("unicode_escape")
        except (UnicodeDecodeError, ValueError):
            raw = chunk
        match = re.search(r'\{"fantasyTeamId":\d+.*\}', raw, re.DOTALL)
        if match:
            try:
                team_data = json.loads(match.group())
                break
            except json.JSONDecodeError:
                continue

    if not team_data:
        print("  ✗ Could not extract team data from page — Next.js payload structure may have changed.")
        print("    Verify manually: open holdet.dk → your team page → F12 → search 'initialLineup'")
        return

    lineup = team_data.get("initialLineup", [])
    captain_id = team_data.get("initialCaptain")
    bank = team_data.get("initialBank", 0)

    state = {
        "snapshot_type": "pre_race",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "fantasy_team_id": int(fantasy_team_id),
        "bank": bank,
        "captain_holdet_id": captain_id,
        "riders": [
            {
                "holdet_id": r["id"],
                "name": f"{r.get('firstName', '')} {r.get('lastName', '')}".strip() if "firstName" in r else r.get("name", ""),
                "price": r.get("price", 0),
                "startPrice": r.get("startPrice", 0),
                "captainPopularity": r.get("captainPopularity"),
                "slot": r.get("favorite"),
            }
            for r in lineup
        ],
    }

    print(f"\nTeam state extracted:")
    print(f"  Bank   : {bank:,} kr")
    print(f"  Captain: holdet_id {captain_id}")
    print(f"  Riders : {len(state['riders'])}")
    for r in state["riders"]:
        cap_marker = " ⭐" if r["holdet_id"] == captain_id else ""
        print(f"    [{r['slot']}] {r['name']} ({r['holdet_id']}) — {r['price']:,} kr{cap_marker}")

    if not dry_run:
        TEAM_STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))
        print(f"\n✓ Written: {TEAM_STATE_FILE}")
    else:
        print("  [dry-run] Would write team state")


# ---------------------------------------------------------------------------
# Step 6 — fetch_team_as_dict (returns dict, does not write files)
# ---------------------------------------------------------------------------

def fetch_team_as_dict(cartridge: str, fantasy_team_id: str, cookie: str) -> dict:
    """
    Scrape user's Holdet team page and return bank_balance, team_composition,
    captain holdet_id, player_rank, player_points as a plain dict.
    Falls back gracefully if the page structure has changed.
    """
    url = f"{BASE_URL}/da/{cartridge}/me/fantasyteams/{fantasy_team_id}"
    print(f"\n[fetch_team_as_dict] Fetching: {url}")
    result = {
        'bank_balance': None,
        'team_composition': [],
        'captain': None,
        'player_rank': None,
        'player_points': None,
    }

    resp = requests.get(url, headers={"Cookie": cookie}, timeout=20)
    if resp.status_code in (401, 403):
        print(f"  [fetch_team_as_dict] HTTP {resp.status_code} — cookie issue")
        return result
    resp.raise_for_status()

    html = resp.text
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)', html, re.DOTALL)

    for chunk in chunks:
        if "initialLineup" not in chunk:
            continue
        try:
            raw = chunk.encode().decode("unicode_escape")
        except (UnicodeDecodeError, ValueError):
            raw = chunk
        match = re.search(r'\{"fantasyTeamId":\d+.*\}', raw, re.DOTALL)
        if not match:
            continue
        try:
            team_data = json.loads(match.group())
        except json.JSONDecodeError:
            continue

        lineup      = team_data.get("initialLineup", [])
        captain_id  = team_data.get("initialCaptain")
        bank        = team_data.get("initialBank", 0)
        rank        = team_data.get("rank") or team_data.get("globalRank")
        points      = team_data.get("points") or team_data.get("totalPoints")

        # Resolve captain name from lineup
        captain_name = ""
        for r in lineup:
            if r.get("id") == captain_id:
                captain_name = f"{r.get('firstName', '')} {r.get('lastName', '')}".strip()
                break

        result.update({
            'bank_balance':     bank,
            'team_composition': [
                f"{r.get('firstName', '')} {r.get('lastName', '')}".strip()
                for r in lineup
            ],
            'captain':      captain_name,
            'captain_id':   captain_id,
            'player_rank':  rank,
            'player_points': points,
        })
        print(f"  [fetch_team_as_dict] bank={bank:,}  captain={captain_name!r}  riders={len(result['team_composition'])}  rank={rank}")
        break

    if not result['team_composition']:
        print("  [fetch_team_as_dict] No team data found.")
        print(f"  URL fetched: {url}")
        print(f"  HTTP status: {resp.status_code}")
        print(f"  Response preview: {html[:500]!r}")
        print("  Hint: check that HOLDET_COOKIE is valid and the URL resolves to your team page")

    return result


# ---------------------------------------------------------------------------
# Step 6b — fetch_stage_results (raw Holdet history payload for one stage)
# ---------------------------------------------------------------------------

def fetch_stage_results(stage: int) -> dict:
    """
    Build stage N results from three nexus JSON endpoints (no HTML scraping):

      1. /api/fantasyteams/{team}/rounds/{stage}/lineup
             → 8 player IDs + who is captain
      2. /api/games/{game}/rounds/{stage}/players
             → priceChange per player (the "assets" score, works without auth)
      3. /api/fantasyteams/{team}/history
             → round-level totals: bank value, total change, captainBonus, specialBonus

    Returns a dict compatible with stage_N_results.json / renderStageResults().
    Writes stage_N_results.json to SNAPSHOT_DIR if the round is scored
    (i.e. assets.change != 0 in the history).
    """
    load_dotenv(ROOT / ".env", override=True)
    game_id         = os.getenv("HOLDET_GAME_ID_GIRO", "612")
    fantasy_team_id = os.getenv("HOLDET_FANTASY_TEAM_ID", "6796783")
    cookie          = _cookie()
    headers         = {"Cookie": cookie}

    SNAPSHOT_DIR = ROOT / "shared" / "data" / "snapshots"

    # --- Step 1: lineup (player IDs + captain for this round) ---
    lineup_url = f"{BASE_URL}/api/fantasyteams/{fantasy_team_id}/rounds/{stage}/lineup"
    print(f"[fetch_stage_results] GET {lineup_url}")
    lr = requests.get(lineup_url, headers=headers, timeout=15)
    if lr.status_code == 401:
        raise ValueError("Nexus 401 on lineup endpoint — check HOLDET_FANTASY_TEAM_ID")
    lr.raise_for_status()
    lineup_items = lr.json().get("items", [])
    if not lineup_items:
        print(f"  Empty lineup for round {stage} — stage not open yet?")
        return {"rider_results": [], "bank_balance": 50_000_000, "stage_total": 0,
                "player_rank": None, "captain_name": "", "depth_bonus": 0,
                "captain_bonus": 0, "riders_in_top15": 0, "scored": False}

    captain_player_id = next(
        (it["playerId"] for it in lineup_items if it.get("role") == "captain"), None
    )
    lineup_player_ids = {it["playerId"] for it in lineup_items}
    print(f"  {len(lineup_player_ids)} lineup players, captain playerId={captain_player_id}")

    # --- Step 2: round players (priceChange per player) ---
    round_url = f"{BASE_URL}/api/games/{game_id}/rounds/{stage}/players"
    print(f"[fetch_stage_results] GET {round_url}")
    rr = requests.get(round_url, headers=headers, timeout=15)
    rr.raise_for_status()
    round_items = rr.json().get("items", [])

    # Build playerId → priceChange map
    round_map = {it["playerId"]: it for it in round_items}

    # --- Step 3: person names (from main players endpoint) ---
    players_url = f"{BASE_URL}/api/games/{game_id}/players"
    print(f"[fetch_stage_results] GET {players_url}")
    pr = requests.get(players_url, headers=headers, timeout=15)
    pr.raise_for_status()
    players_data = pr.json()
    persons = players_data["_embedded"]["persons"]
    # playerId → name
    player_names = {}
    for it in players_data["items"]:
        pid_str = str(it["personId"])
        person  = persons.get(pid_str, {})
        player_names[it["id"]] = (
            f"{person.get('firstName', '')} {person.get('lastName', '')}".strip()
            or f"player_{it['id']}"
        )

    # --- Step 4: history (round-level totals) ---
    hist_url = f"{BASE_URL}/api/fantasyteams/{fantasy_team_id}/history"
    print(f"[fetch_stage_results] GET {hist_url}")
    hr = requests.get(hist_url, headers=headers, timeout=15)
    hr.raise_for_status()
    hist_items = hr.json().get("items", [])
    round_hist = next((h for h in hist_items if h.get("round") == stage), None)

    bank_balance  = 50_000_000
    stage_total   = 0
    captain_bonus = 0
    special_bonus = 0
    player_rank   = None

    if round_hist:
        assets        = round_hist.get("assets", {})
        bank_balance  = assets.get("value", 50_000_000)
        stage_total   = assets.get("change", 0)
        captain_bonus = assets.get("captainBonus", 0)
        special_bonus = assets.get("specialBonus", 0)
        print(f"  History: bank={bank_balance:,}  change={stage_total:,}  captainBonus={captain_bonus:,}  specialBonus={special_bonus:,}")
    else:
        print(f"  No history entry for round {stage} yet")

    # --- Build rider_results ---
    rider_results = []
    captain_name  = ""
    for player_id in lineup_player_ids:
        name       = player_names.get(player_id, f"player_{player_id}")
        round_item = round_map.get(player_id, {})
        price_chg  = round_item.get("priceChange", 0) or 0
        is_cap     = (player_id == captain_player_id)
        if is_cap:
            captain_name = name
        rider_results.append({
            "name":          name,
            "finish":        "—",
            "stage_pts":     price_chg,
            "sprint_pts":    0,
            "jersey_bonus":  0,
            "gc_bonus":      0,
            "team_bonus":    0,
            "captain_bonus": captain_bonus if is_cap else 0,
            "total":         price_chg + (captain_bonus if is_cap else 0),
        })

    rider_results.sort(key=lambda r: r["total"], reverse=True)
    scored = stage_total != 0 or any(r["stage_pts"] != 0 for r in rider_results)

    # Reverse-map specialBonus → riders-in-top-15 count via the authoritative
    # Holdet curve (shared/rules/game_strategy.md). The API doesn't expose
    # per-rider finish positions on this endpoint, but the curve values are
    # unique so the bonus → count mapping is exact.
    DEPTH_BONUS_CURVE = {
        0: 0, 1: 4_000, 2: 8_000, 3: 15_000, 4: 35_000,
        5: 65_000, 6: 120_000, 7: 220_000, 8: 400_000,
    }
    riders_in_top15 = next(
        (n for n, v in DEPTH_BONUS_CURVE.items() if v == special_bonus),
        None,  # bonus value off-curve → unknown
    )

    result = {
        "rider_results":   rider_results,
        "bank_balance":    bank_balance,
        "stage_total":     stage_total,
        "player_rank":     player_rank,
        "captain_name":    captain_name,
        "depth_bonus":     special_bonus,
        "captain_bonus":   captain_bonus,
        "riders_in_top15": riders_in_top15,
        "scored":          scored,
    }

    if scored:
        out = SNAPSHOT_DIR / f"stage_{stage}_results.json"
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"  Saved → {out}")

        holdet_snap = SNAPSHOT_DIR / f"stage_{stage}_holdet.json"
        if not holdet_snap.exists():
            holdet_snap.write_text(json.dumps({
                "team_composition": [r["name"] for r in rider_results],
                "bank_balance":     bank_balance,
                "captain":          captain_name,
                "stage":            stage,
            }, indent=2, ensure_ascii=False))
            print(f"  Wrote team snapshot → {holdet_snap}")
    else:
        print(f"  Stage {stage} not yet scored — no file written")

    return result


# ---------------------------------------------------------------------------
# Step 7 — fetch_all (riders + team, returns combined dict for /refresh)
# ---------------------------------------------------------------------------

def fetch_all(stage: int) -> dict:
    """
    Full Holdet scrape: all rider market data + user team snapshot.
    Returns { riders_data: {...}, snapshot: {...}, timestamp: '...' }
    Used by /refresh endpoint in server.py.
    """
    load_dotenv(ROOT / ".env")
    game_id         = os.getenv("HOLDET_GAME_ID_GIRO", "612")
    cartridge       = os.getenv("HOLDET_CARTRIDGE", "giro-d-italia-2026")
    fantasy_team_id = os.getenv("HOLDET_FANTASY_TEAM_ID", "6796783")
    cookie          = _cookie()

    print(f"[fetch_all] stage={stage}  game={game_id}")
    api_riders   = fetch_riders_api(game_id, cookie)
    enriched     = enrich_riders(api_riders)
    team_snapshot = fetch_team_as_dict(cartridge, fantasy_team_id, cookie)
    team_snapshot['stage'] = stage
    team_snapshot['timestamp'] = datetime.now(timezone.utc).isoformat()

    return {
        'riders_data': enriched,
        'snapshot':    team_snapshot,
        'timestamp':   datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Enrich rider data from holdet.dk API")
    parser.add_argument("--team", action="store_true", help="Also fetch team state (HTML scraping)")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and match but do not write files")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    game_id = os.getenv("HOLDET_GAME_ID_GIRO", "612")
    cartridge = os.getenv("HOLDET_CARTRIDGE", "giro-d-italia-2026")
    fantasy_team_id = os.getenv("HOLDET_FANTASY_TEAM_ID", "6796783")
    cookie = _cookie()

    print(f"Fetching riders from game {game_id}…")
    api_riders = fetch_riders_api(game_id, cookie)
    print(f"  → {len(api_riders)} riders returned by API")

    enriched = enrich_riders(api_riders, dry_run=args.dry_run)
    write_price_snapshot(api_riders, dry_run=args.dry_run)
    write_stage_snapshot(enriched, dry_run=args.dry_run)

    if args.team:
        fetch_team_state(cartridge, fantasy_team_id, cookie, dry_run=args.dry_run)

    # build_dashboard.py removed — dashboard loads riders via GET /riders


if __name__ == "__main__":
    main()
