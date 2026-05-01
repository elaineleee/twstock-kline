#!/usr/bin/env bash
# Expose the local Flask server (127.0.0.1:8080) on a public *.trycloudflare.com URL.
# This is a temporary "quick tunnel" — no Cloudflare account required.
#
# Usage:
#   ./scripts/start_tunnel.sh
#
# Output:
#   The script tails cloudflared's stderr; look for a line like
#     https://random-words-here.trycloudflare.com
#   That URL is your public link. Ctrl+C kills the tunnel.

set -euo pipefail

PORT="${PORT:-8080}"

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "cloudflared not found. Install with:"
  echo "  brew install cloudflared"
  exit 1
fi

echo "Starting cloudflared tunnel → http://127.0.0.1:${PORT}"
echo "Look for the trycloudflare.com URL below — that's your public link."
echo
exec cloudflared tunnel --url "http://127.0.0.1:${PORT}" --no-autoupdate
