#!/usr/bin/env bash
# J.A.R.V.I.S. — quick start
set -e
cd "$(dirname "$0")"

# Free port 3000 if something's already on it
PORT="${PORT:-3000}"
lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true

# Sanity check: real API key present?
if ! grep -q '^ANTHROPIC_API_KEY=sk-ant-' .env 2>/dev/null; then
  echo "⚠️  No real ANTHROPIC_API_KEY in .env — chat won't respond. Edit JARVIS/.env first."
fi

echo "⚡  Starting J.A.R.V.I.S. on http://localhost:$PORT  (Ctrl+C to stop)"

# Open the browser once the server is up (background, non-blocking)
( for _ in $(seq 1 30); do
    if curl -s -o /dev/null http://localhost:"$PORT"/; then open "http://localhost:$PORT"; break; fi
    sleep 0.5
  done ) &

exec python3 server.py
