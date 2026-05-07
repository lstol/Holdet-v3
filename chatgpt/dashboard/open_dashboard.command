#!/bin/zsh
set -e

SCRIPT_DIR="${0:A:h}"
REPO_ROOT="${SCRIPT_DIR:h:h}"

cd "$REPO_ROOT"
open -a Safari chatgpt/dashboard/index.html
