#!/bin/bash
STAGE=$1
echo "Search current bookmaker odds for Stage ${STAGE} Giro d'Italia 2026. Return implied win probability and top-3 probability for every rider with win% >= 1%. Format as JSON array: [{name, win_pct, top3_pct}] sorted by win_pct descending." | pbcopy
open "https://claude.ai"
