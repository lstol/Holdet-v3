"""
build_dashboard.py — embed rider and stage data into claude/dashboard/claude.html

Reads shared/data/riders/giro_2026/riders.json and
shared/data/stages/giro_2026/stages_giro2026.json and injects both arrays
as window.RIDERS_DATA and window.STAGES_DATA between the respective
<!-- BEGIN:* --> / <!-- END:* --> markers in claude.html.

Run after every fetch_riders.py to keep embedded data current.

Usage:
    python3 claude/engine/build_dashboard.py
"""

import json
import sys
from pathlib import Path

ROOT      = Path(__file__).resolve().parents[2]
RIDERS    = ROOT / "shared" / "data" / "riders" / "giro_2026" / "riders.json"
STAGES    = ROOT / "shared" / "data" / "stages" / "giro_2026" / "stages_giro2026.json"
DASHBOARD = ROOT / "claude" / "dashboard" / "claude.html"


def inject(html: str, begin: str, end: str, script: str) -> str:
    start = html.find(begin)
    stop  = html.find(end)
    if start == -1 or stop == -1:
        sys.exit(f"ERROR: markers '{begin}' not found in claude.html")
    return html[:start] + f"{begin}\n{script}\n{end}" + html[stop + len(end):]


def main():
    riders = json.loads(RIDERS.read_text()).get("riders", [])
    stages = json.loads(STAGES.read_text()).get("stages", [])

    html = DASHBOARD.read_text()

    html = inject(
        html,
        "<!-- BEGIN:RIDERS_DATA -->", "<!-- END:RIDERS_DATA -->",
        f"<script>window.RIDERS_DATA = {json.dumps(riders, ensure_ascii=False, separators=(',', ':'))};</script>",
    )
    html = inject(
        html,
        "<!-- BEGIN:STAGES_DATA -->", "<!-- END:STAGES_DATA -->",
        f"<script>window.STAGES_DATA = {json.dumps(stages, ensure_ascii=False, separators=(',', ':'))};</script>",
    )

    DASHBOARD.write_text(html)
    print(f"✓ Embedded {len(riders)} riders + {len(stages)} stages into {DASHBOARD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
