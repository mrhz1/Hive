#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

pip install --quiet -r requirements-dev.txt

if [ ! -f "${FRONTEND_DIST:-frontend/dist}/index.html" ]; then
    echo "No dashboard build found. Run 'npm ci && VITE_API_BASE_URL=/api npm run build'" >&2
    echo "in frontend/ from a Session before starting this Application." >&2
    exit 1
fi

exec python scripts/serve_frontend.py
