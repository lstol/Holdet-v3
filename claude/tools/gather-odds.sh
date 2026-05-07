#!/bin/bash
STAGE=$1
open "https://claude.ai/new?q=Search+current+bookmaker+odds+for+Stage+${STAGE}+Giro+d%27Italia+2026.+Return+implied+win+probability+and+top-3+probability+for+every+rider+with+win%25+%3E%3D+1%25.+Format+as+JSON+array%3A+%5B%7Bname%2C+win_pct%2C+top3_pct%7D%5D+sorted+by+win_pct+descending."
