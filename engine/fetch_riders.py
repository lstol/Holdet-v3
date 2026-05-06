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
RIDERS_FILE = ROOT / "data" / "riders" / "riders_giro2026_v1.json"
PRICES_SNAPSHOT_FILE = ROOT / "data" / "riders" / "prices_giro2026_stage0_pre.json"
TEAM_STATE_FILE = ROOT / "data" / "snapshots" / "team_state_pre_race.json"

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
    new_from_api = []

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
            # API rider not in our local file at all
            unmatched_api.append(api_r)
            new_from_api.append(_make_stub(api_r))

    # Append new stubs
    local_riders.extend(new_from_api)
    local_data["meta"]["rider_count"] = len(local_riders)
    local_data["meta"]["enriched_at"] = datetime.now(timezone.utc).isoformat()

    no_id = [r["name"] for r in local_riders if not r.get("holdet_id")]

    _print_summary(matched, uncertain, unmatched_api, no_id, len(local_riders))

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
# Step 4 — Fetch team state (HTML scraping)
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

    enrich_riders(api_riders, dry_run=args.dry_run)
    write_price_snapshot(api_riders, dry_run=args.dry_run)

    if args.team:
        fetch_team_state(cartridge, fantasy_team_id, cookie, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
