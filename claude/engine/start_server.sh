#!/bin/bash
# Starts the Claude dashboard server in the current terminal.
# Double-click in Finder (macOS) or run: bash claude/engine/start_server.sh
cd "$(dirname "$0")/../.."
echo "Starting server at http://localhost:5050/dashboard"
python3 claude/engine/server.py
