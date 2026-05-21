#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -d .venv ]]; then
    echo "error: .venv not found — run: python3 -m venv .venv && source .venv/bin/activate && pip install -e ." >&2
    exit 1
fi

source .venv/bin/activate
exec python btb-bot.py
