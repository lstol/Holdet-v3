#!/bin/bash
cd /Users/lassestoltenberg/Claude/Holdet-v3
python3 claude/engine/fetch_riders.py
python3 claude/engine/build_dashboard.py
open claude/dashboard/claude.html
