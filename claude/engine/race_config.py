"""
Race configuration — active-race dispatch for Giro / TdF pipelines.

Reads HOLDET_ACTIVE_RACE from environment (default: 'giro') and resolves the
canonical (game_id, cartridge slug, data directory, stages metadata filename)
tuple for the current race. All hardcoded 'giro-d-italia-2026' / 'giro_2026'
references in fetch_riders.py / server.py / optimizer.py / capture_cookie.py
resolve through this module.

Env variable convention:
  HOLDET_ACTIVE_RACE=giro    → Giro d'Italia 2026 (default; backward-compat)
  HOLDET_ACTIVE_RACE=tdf     → Tour de France 2026

Per-race env variables (fallback defaults hardcoded here):
  HOLDET_GAME_ID_GIRO         (default 612)
  HOLDET_GAME_ID_TDF          (default 618)
  HOLDET_CARTRIDGE (Giro)     (default giro-d-italia-2026)
  HOLDET_CARTRIDGE_TDF        (default tour-de-france-2026)
"""

from __future__ import annotations

import os
from typing import TypedDict


class RaceConfig(TypedDict):
    race: str            # 'giro' | 'tdf'
    game_id: str         # Holdet API numeric game ID
    cartridge: str       # URL slug ('giro-d-italia-2026', 'tour-de-france-2026')
    data_dir: str        # shared/data subdir ('giro_2026', 'tour_de_france_2026')
    stages_file: str     # stages metadata filename


_RACE_TABLE = {
    'giro': {
        'game_id_env': 'HOLDET_GAME_ID_GIRO',
        'game_id_default': '612',
        'cartridge_env': 'HOLDET_CARTRIDGE',
        'cartridge_default': 'giro-d-italia-2026',
        'data_dir': 'giro_2026',
        'stages_file': 'stages_giro2026.json',
    },
    'tdf': {
        'game_id_env': 'HOLDET_GAME_ID_TDF',
        'game_id_default': '618',
        'cartridge_env': 'HOLDET_CARTRIDGE_TDF',
        'cartridge_default': 'tour-de-france-2026',
        'data_dir': 'tour_de_france_2026',
        'stages_file': 'stages_tour2026.json',
    },
}


def active_race() -> str:
    """Returns 'giro' (default) or 'tdf' per HOLDET_ACTIVE_RACE env."""
    r = os.getenv('HOLDET_ACTIVE_RACE', 'giro').strip().lower()
    if r not in _RACE_TABLE:
        raise ValueError(
            f"HOLDET_ACTIVE_RACE={r!r} is invalid. Valid: {sorted(_RACE_TABLE)}"
        )
    return r


def race_config(race: str | None = None) -> RaceConfig:
    """Resolve canonical config for a race (default: active_race())."""
    r = race or active_race()
    if r not in _RACE_TABLE:
        raise ValueError(f"Unknown race {r!r}. Valid: {sorted(_RACE_TABLE)}")
    row = _RACE_TABLE[r]
    return {
        'race': r,
        'game_id': os.getenv(row['game_id_env'], row['game_id_default']),
        'cartridge': os.getenv(row['cartridge_env'], row['cartridge_default']),
        'data_dir': row['data_dir'],
        'stages_file': row['stages_file'],
    }


if __name__ == '__main__':
    from dotenv import load_dotenv
    from pathlib import Path
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    import json
    print(json.dumps({
        'active_race': active_race(),
        'config': race_config(),
        'giro_config': race_config('giro'),
        'tdf_config': race_config('tdf'),
    }, indent=2))
