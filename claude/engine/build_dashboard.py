"""
build_dashboard.py — embed rider data into claude/dashboard/claude.html

Reads shared/data/riders/giro_2026/riders.json and injects the rider array
as window.RIDERS_DATA between the <!-- BEGIN:RIDERS_DATA --> and
<!-- END:RIDERS_DATA --> markers in claude.html.

Run after every fetch_riders.py to keep embedded data current.

Usage:
    python3 claude/engine/build_dashboard.py
"""

import json
import sys
from pathlib import Path

ROOT      = Path(__file__).resolve().parents[2]
RIDERS    = ROOT / "shared" / "data" / "riders" / "giro_2026" / "riders.json"
DASHBOARD = ROOT / "claude" / "dashboard" / "claude.html"

BEGIN = "<!-- BEGIN:RIDERS_DATA -->"
END   = "<!-- END:RIDERS_DATA -->"


def main():
    riders = json.loads(RIDERS.read_text()).get("riders", [])

    block = (
        f"{BEGIN}\n"
        f"<script>window.RIDERS_DATA = "
        f"{json.dumps(riders, ensure_ascii=False, separators=(',', ':'))};</script>\n"
        f"{END}"
    )

    html = DASHBOARD.read_text()
    start = html.find(BEGIN)
    end   = html.find(END)
    if start == -1 or end == -1:
        sys.exit("ERROR: markers not found in claude.html")

    html = html[:start] + block + html[end + len(END):]
    DASHBOARD.write_text(html)
    print(f"✓ Embedded {len(riders)} riders into {DASHBOARD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
