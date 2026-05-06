# API_NOTES.md — Holdet API Reference
# Confirmed working as of May 2026 (Phase 2b)
# Base URL: https://nexus-app-fantasy-fargate.holdet.dk

---

## Authentication

Holdet.dk uses **Better Auth** (not NextAuth). The session is stored in two cookies
set on `www.holdet.dk` plus an additional `session` cookie set on the API domain
after the first API call.

**Full cookie string required (as of May 2026):**
```
HOLDET_COOKIE=__Secure-better-auth.session_token=<token>; __Secure-better-auth.session_data=<jwt>; session=<uuid>; AWSALB=<token>; AWSALBCORS=<token>
```

Store in `.env` (all 5 cookies needed for authenticated endpoints):
```
HOLDET_COOKIE=<full cookie string above>
HOLDET_GAME_ID=612
HOLDET_GAME_ID_GIRO=612
HOLDET_GAME_ID_TDF=TBC
HOLDET_FANTASY_TEAM_ID=6796783
HOLDET_CARTRIDGE=giro-d-italia-2026
HOLDET_CARTRIDGE_TDF=tour-de-france-2026
```

**Automated cookie capture (recommended):**
Run `engine/siv/capture_cookie.py` — uses Playwright to log in and write cookies to .env.
Requires `HOLDET_EMAIL` and `HOLDET_PASSWORD` in .env. Takes ~15 seconds.

**Manual cookie capture (fallback):**
1. Chrome → holdet.dk → log in
2. F12 → Network → Fetch/XHR
3. Navigate to `/da/giro-d-italia-2026/me/fantasyteams/6796783`
4. Find any request → Headers → copy full Cookie header value → update `.env`

Refresh cookie when requests return 401/403.

**Never commit `.env` to git.**

**⚠️ AWSALB is IP-sticky.** The `AWSALB` and `AWSALBCORS` tokens are tied to
the IP address of the browser that created them. The cookie will return 403 from
any other machine or network (including CI, sandboxes, or other computers).
Always capture the cookie from the same machine you will run the tool on.

**Public vs authenticated endpoints:**
- `/api/games/612/players` — public (no auth needed for rider list)
- `/api/cartridges/giro-d-italia-2026/favorites` — requires auth (user lineup)
- `/api/cartridges/giro-d-italia-2026/fantasyteams` — requires auth (user teams)

---

## Confirmed Endpoints

### 1. Full Rider Market
```
GET /api/games/{GAME_ID}/players
```
Returns all riders + embedded persons + teams in one call.
See README.md for full field mapping and sample ingestion code.

**Key fields:**
- `items[].id` → holdet_id (primary key)
- `items[].price` → current value in kr
- `items[].isOut` → true = DNS/deactivated
- `_embedded.persons` → rider names by personId
- `_embedded.teams` → team names by teamId

---

### 2. Race Schedule + Stage Metadata
```
GET /api/games/{GAME_ID}
```
Returns complete race schedule with all 21 stages.

**Key fields:**
- `rounds[]` → array of 21 rounds with `start`, `close`, `end` timestamps
  - `close` = trading window closes = stage start time
  - `end` = stage finish / results expected
- `events{}` → keyed by event_id, each stage has:
  - `id` → event_id (48281–48301 for Giro 2026)
  - `name` → "Start - Finish" e.g. "Nessebar - Burgas"
  - `start` → stage start datetime
  - `properties.stageType` → Danish stage type (see translation below)
  - `properties.stageDistance` → distance in metres (divide by 1000 for km)
  - `participants[]` → teams starting (populated for confirmed stages)
- `_embedded.teams{}` → team lookup by teamId
- `rounds[N]` maps to `events[N]` by index (round 0 = event 48281 etc.)

**Stage type translation:**
| Danish | English | Code |
|--------|---------|------|
| Flad | Flat | flat |
| Medium bjerg | Hilly | hilly |
| Bjerg | Mountain | mountain |
| Enkeltstart | Individual Time Trial | itt |
| Holdtidskørsel | Team Time Trial | ttt |

**Event IDs (Giro 2026):**
| Stage | Event ID | Name | Date | Distance | Type |
|-------|----------|------|------|----------|------|
| 1 | 48281 | Nessebar - Burgas | 8 May | 156km | Flat |
| 2 | 48282 | Burgas - Veliko Tarnovo | 9 May | 220km | Hilly |
| 3 | 48283 | Plovdiv - Sofia | 10 May | 174km | Flat |
| 4 | 48284 | Catanzaro - Cosenza | 12 May | 144km | Flat |
| 5 | 48285 | Praia a Mare - Potenza | 13 May | 204km | Hilly |
| 6 | 48286 | Paestum - Napoli | 14 May | 161km | Flat |
| 7 | 48287 | Formia - Blockhaus | 15 May | 246km | Mountain |
| 8 | 48288 | Chieti - Fermo | 16 May | 159km | Hilly |
| 9 | 48289 | Cervia - Corno alle Scale | 17 May | 184km | Hilly |
| 10 | 48290 | Viareggio - Massa TUDOR ITT | 19 May | 40.2km | ITT |
| 11 | 48291 | Porcari - Chiavari | 20 May | 178km | Hilly |
| 12 | 48292 | Imperia - Novi Ligure | 21 May | 177km | Flat |
| 13 | 48293 | Alessandria - Verbania | 22 May | 186km | Flat |
| 14 | 48294 | Aosta - Pila | 23 May | 133km | Mountain |
| 15 | 48295 | Voghera - Milano | 24 May | 136km | Flat |
| 16 | 48296 | Bellinzona - Carì | 26 May | 113km | Mountain |
| 17 | 48297 | Cassano d'Adda - Andalo | 27 May | 200km | Hilly |
| 18 | 48298 | Fai della Paganella - Pieve di Soligo | 28 May | 167km | Flat |
| 19 | 48299 | Feltre - Alleghe | 29 May | 151km | Mountain |
| 20 | 48300 | Gemona - Piancavallo | 30 May | 199km | Mountain |
| 21 | 48301 | Roma - Roma | 31 May | 131km | Flat |

Rest days: 11 May (after Stage 3), 25 May (after Stage 15)

---

### 3. Fantasy Teams List
```
GET /api/cartridges/{CARTRIDGE}/fantasyteams
```
Returns your fantasy teams for this competition.

**Response:**
```json
{
  "items": [
    {
      "id": 6796783,
      "name": "Project Win The Giro",
      "tier": "gold",
      "isActive": true
    }
  ]
}
```

**Your team:**
- Fantasy Team ID: `6796783`
- Name: "Project Win The Giro"
- Tier: gold (unlimited transfers)

---

### 4. In-Play Status
```
GET /api/cartridges/{CARTRIDGE}/in-play  (or similar path)
```
Returns empty `items: []` when no stage is in progress.
Will return active lineup data during live stages — check again on Stage 1.

---

### 5. Notifications Check
```
GET /api/check  (or similar)
```
Returns `{hasNewMessages: true, hasMessages: true}` — notification status only.
Not useful for team data.

---

## Session 5 Probe Results (2026-04-17, pre-race)

Probed with live cookie via `probe_extra_endpoints("612", cookie)`:

| Endpoint | HTTP | Result |
|----------|------|--------|
| `/api/games/612/rounds` | 200 | Returns **HTML** (Next.js page render, not JSON) |
| `/api/games/612/standings` | 200 | Returns `[]` — empty array, race not started |
| `/api/games/612/statistics` | 200 | Returns **HTML** (Next.js page render, not JSON) |

**Key findings:**
- `/rounds` and `/statistics` are Next.js frontend routes masquerading as API paths —
  they return the full server-rendered HTML, not JSON. Not useful for data ingestion.
- `/standings` returns `[]` pre-race. Check again after Stage 1 — may contain GC
  standings once racing starts.
- GC standings and jersey data are still NOT available via any confirmed JSON endpoint.
  Continue using manual input for these fields until confirmed post Stage 1.

**Real API field discovery** (from live `/players` response):

Additional fields present in `items[]` not previously documented:
| Field | Value | Notes |
|-------|-------|-------|
| `positionId` | 264 (all riders) | Position type — 264 appears to be "cyclist". Single value for all, not useful for differentiation yet. |
| `popularity` | null (pre-race) | Expected to populate once race starts — likely % ownership or captain pick rate. |

Real ID mapping for known riders:
| Rider | holdet_id | personId | teamId |
|-------|-----------|----------|--------|
| Jonas Vingegaard | 47372 | 4196 | 205 (TVL) |
| Jonathan Milan | 47373 | — | — (LIT) |
| Joao Almeida | 47370 | — | — (UAD) |

Person objects in `_embedded.persons` have an `appearance` sub-object (empty pre-race).
Team objects in `_embedded.teams` have numeric keys in the API.

Total roster: **~179 riders**, 23 teams.

NOTE: An earlier probe (April 2026, pre-race) returned only 91 riders because the
full startlist had not yet been confirmed in the Holdet system. This was a timing
artifact, not the real market size. The full Giro d'Italia roster is ~179 tradeable
players across 23 teams. Always re-fetch after official startlist confirmation.

---

## Endpoints Still To Investigate

Try these while logged in — paste URL in browser address bar:

```
# Team composition and bank balance
GET /api/cartridges/giro-d-italia-2026/fantasyteams/6796783
GET /api/cartridges/giro-d-italia-2026/fantasyteams/6796783/players
GET /api/cartridges/giro-d-italia-2026/fantasyteams/6796783/rounds
GET /api/games/612/fantasyteams/6796783

# Stage results (once race starts — use event_id)
GET /api/games/612/events/48281/results
GET /api/games/612/rounds/0/results
GET /api/games/612/events/48281/standings

# Player stats and injuries
GET /api/games/612/statistics
GET /api/cartridges/giro-d-italia-2026/statistics
GET /api/cartridges/giro-d-italia-2026/injuries?lang=da
GET /api/cartridges/giro-d-italia-2026/suspensions

# Leaderboard / rankings
GET /api/cartridges/giro-d-italia-2026/leaderboard
GET /api/games/612/leaderboard
```

Document any useful responses here.

---

## Python Ingestion Code

### Fetch all riders
```python
import requests, os
from dotenv import load_dotenv
load_dotenv()

def fetch_riders() -> list[dict]:
    url = f"https://nexus-app-fantasy-fargate.holdet.dk/api/games/{os.getenv('HOLDET_GAME_ID_GIRO')}/players"
    response = requests.get(url, headers={"Cookie": os.getenv("HOLDET_COOKIE")})
    if response.status_code == 401:
        raise PermissionError("Cookie expired — refresh from browser DevTools")
    data = response.json()
    persons = data["_embedded"]["persons"]
    teams = data["_embedded"]["teams"]
    riders = []
    for item in data["items"]:
        pid, tid = str(item["personId"]), str(item["teamId"])
        person, team = persons.get(pid, {}), teams.get(tid, {})
        riders.append({
            "holdet_id": str(item["id"]),
            "name": f"{person.get('firstName','')} {person.get('lastName','')}".strip(),
            "team": team.get("name", "Unknown"),
            "team_abbr": team.get("abbreviation", "???"),
            "value": item["price"],
            "start_value": item["startPrice"],
            "points": item["points"] or 0,
            "status": "dns" if item["isOut"] else "active",
            "gc_position": None,
            "jerseys": [],
        })
    return riders
```

### Fetch race schedule and auto-populate stages
```python
def fetch_schedule() -> dict:
    url = f"https://nexus-app-fantasy-fargate.holdet.dk/api/games/{os.getenv('HOLDET_GAME_ID_GIRO')}"
    response = requests.get(url, headers={"Cookie": os.getenv("HOLDET_COOKIE")})
    data = response.json()
    stages = []
    for i, (round_info, event_id) in enumerate(zip(data["rounds"], data["events"])):
        event = data["_embedded"]["events"][str(event_id)]
        stage_type_da = event["properties"].get("stageType", "Flad")
        type_map = {
            "Flad": "flat", "Medium bjerg": "hilly",
            "Bjerg": "mountain", "Enkeltstart": "itt", "Holdtidskørsel": "ttt"
        }
        stages.append({
            "number": i + 1,
            "event_id": event_id,
            "name": event["name"],
            "date": event["start"][:10],
            "trading_close": round_info["close"],
            "stage_end": round_info["end"],
            "distance_km": int(event["properties"].get("stageDistance", 0)) / 1000,
            "stage_type_da": stage_type_da,
            "stage_type": type_map.get(stage_type_da, "flat"),
            "is_ttt": stage_type_da == "Holdtidskørsel",
            "sprint_points": [],
            "kom_points": [],
        })
    return stages
```

---

## Key Observations

- **cartridge slug** pattern: `giro-d-italia-2026` — TdF will be `tour-de-france-2026`
- **game_id** (612) and **cartridge slug** are two parallel ways to identify the competition
- **event_ids** (48281–48301) are likely the keys for fetching stage-specific results
- Stage 1 starts in **Bulgaria** (unusual grand tour opener) before moving to Italy Stage 4
- Trading window **close time** = stage start time (from `rounds[].close`)
- Stage 10 is a **40.2km ITT** — significant late arrival penalty risk for non-specialists
- Stages 7, 14, 16, 19, 20 are mountain stages — the five key GC days

---

## Additional Confirmed Endpoints (from DevTools screenshots)

### Injuries
```
GET /api/games/612/injuries?lang=da
```
Returns injury news in Danish. Empty before race starts.
Will populate during race — check daily for DNS risk alerts.

### Suspensions
```
GET /api/games/612/suspensions
```
Returns suspension data. Empty before race starts.

### Server Time
```
GET /api/time
```
Current server time. Useful for verifying trading window open/close.

### In-Play (correct full URL)
```
GET /api/editions/354/persons/in-play
```
Edition ID = 354 (not game ID 612). Returns empty when no stage running.
Check during Stage 1 to see what active lineup data it returns.

### Schedules (alias)
```
GET /api/schedules/612
```
Identical to /api/games/612. Alternative path, same data.

### Fantasy Team Page URL (confirmed working via HTML scraping)
```
GET /da/giro-d-italia-2026/me/fantasyteams/6796783
```
Returns 200, 284k chars of Next.js HTML. `initialLineup`, `initialBank`, and
`initialCaptain` confirmed present in the page payload. See HTML scraping
section below for full field list and extraction approach.

### Still to check when race starts
```
GET /api/games/612/injuries?lang=da     ← DNS/injury alerts
GET /api/games/612/suspensions          ← suspensions
GET /api/editions/354/persons/in-play   ← live lineup during stage
GET /api/cartridges/giro-d-italia-2026/favorites
```

---

## Team Composition — HTML Page Scraping (CONFIRMED)

The team composition is embedded in the Next.js server-rendered HTML page.
There is no separate clean REST endpoint — data is in the page payload.

### URL
```
GET /da/{CARTRIDGE}/me/fantasyteams/{FANTASY_TEAM_ID}
Auth: Cookie header (same session cookie)
```

Example:
```
GET /da/giro-d-italia-2026/me/fantasyteams/6796783
```

### What it contains
The HTML contains a large `self.__next_f.push(...)` block with JSON including:

- `initialLineup[]` — your 8 current riders with full player objects
- `initialCaptain` — holdet_id of current captain
- `initialBank` — current bank balance in kr
- `allPlayers[]` — full enriched market (all riders) with extra fields

### Confirmed fields in initialLineup[] objects (live QC 2026-04-17)

These fields are present on each rider object inside `initialLineup`. They are
richer than `/api/games/612/players` and are the primary source for state.json.

| Field | Example | Meaning |
|-------|---------|---------|
| `id` | 47380 | holdet_id (primary key) |
| `gameId` | 612 | game this rider belongs to |
| `personId` | 4922 | key into persons lookup |
| `teamId` | 200 | key into teams lookup |
| `positionId` | 264 | always 264 ("cyclist") — not useful for differentiation |
| `startPrice` | 2500000 | value at race start |
| `price` | 2500000 | current value |
| `points` | 0 | cumulative race points |
| `popularity` | null | pre-race null; expected to populate during race |
| `captainPopularity` | 0.0021 | fraction of teams using as captain (0.21%) |
| `favorite` | 1 | slot number in your team (1–8) |
| `owners` | 45 | number of teams that own this rider |
| `captainOwners` | 1 | number of teams using as captain |
| `isOutOfGame` | false | rider removed from game entirely |
| `isActive` | true | rider active for this round |
| `isInjured` | false | injury flag — check daily |
| `isPublished` | true | rider visible in market |
| `isEliminated` | false | rider eliminated from race |
| `validFrom` | "2026-04-15T…" | when this record became valid |
| `validTo` | null | expiry (null = still current) |
| `_embedded` | {} | empty pre-race; may populate during race |

### Python extraction approach
```python
import re, json, requests

def fetch_my_team(fantasy_team_id: str, cartridge: str, cookie: str) -> dict:
    url = f"https://nexus-app-fantasy-fargate.holdet.dk/da/{cartridge}/me/fantasyteams/{fantasy_team_id}"
    response = requests.get(url, headers={"Cookie": cookie})
    html = response.text

    # Extract all __next_f.push payloads and concatenate
    chunks = re.findall(r'self\.__next_f\.push\(\[1,\s*"(.*?)"\]\)', html, re.DOTALL)

    # Find the chunk containing initialLineup
    for chunk in chunks:
        if 'initialLineup' in chunk:
            # Unescape the JSON string
            raw = chunk.encode().decode('unicode_escape')
            # Extract the JSON object containing initialLineup
            # Look for the pattern starting with fantasyTeamId
            match = re.search(r'\{\"fantasyTeamId\":\d+,.*\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
                return {
                    "lineup": data["initialLineup"],
                    "captain": data["initialCaptain"],
                    "bank": data["initialBank"],
                    "all_players": data["allPlayers"]
                }
    raise ValueError("Could not extract team data from page")
```

Note: The regex approach is fragile. Consider using BeautifulSoup or a proper
HTML parser for production. The key is finding the `__next_f.push` block
that contains `initialLineup`.

### Known team state (dummy team, pre-Giro)
| Rider | Holdet ID | Team | Value |
|-------|-----------|------|-------|
| Lorenzo Germani | 47380 | Groupama-FDJ | 2,500,000 |
| Liam Slock | 47378 | Lotto Intermarché | 2,500,000 |
| Manuele Tarozzi ⭐ | 47382 | Bardiani CSF | 2,500,000 |
| Jonas Vingegaard | 47372 | Visma LAB | 17,500,000 |
| Filippo Conca | 47350 | Jayco AlUla | 2,500,000 |
| Dion Smith | 47341 | NSN Cycling | 2,500,000 |
| Lennert Van Eetvelt | 47377 | Lotto Intermarché | 7,500,000 |
| Jay Vine | 47368 | UAE XRG | 8,000,000 |

⭐ = captain (id 47382)
Bank: 4,500,000 kr
Total: 50,000,000 kr

### Additional data found in page
- Username: "Lasse Stoltenberg"
- League: "Præmiepuljen" (league id 10021991)
- `captainPopularity` data — shows Vingegaard at 42% captain ownership
  across all teams, Milan at 24%, Tarozzi at 0.68% (your dummy pick)
