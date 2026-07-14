#!/usr/bin/env bash
# Restart the Flask dev server: kills any existing instance on port 5000,
# then starts a fresh one.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

echo "Stopping any existing server..."
pkill -f "python3 app.py" 2>/dev/null || true
sleep 1

echo "Starting server..."
python3 app.py
