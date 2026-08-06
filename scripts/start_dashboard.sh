#!/usr/bin/env bash
# Cloudera AI Application entrypoint for the React dashboard.
#
# Cloudera AI cannot serve a static build directly -- an Application runs
# a process -- so a small Flask server (scripts/serve_frontend.py) serves
# frontend/dist with SPA fallback and an optional API proxy.
#
# The build itself is NOT done here. `npm run build` bakes
# VITE_API_BASE_URL into the bundle, so it belongs in the deployment
# step, not in a script that reruns on every restart: rebuilding at boot
# would make a restart able to change what the app talks to.
set -euo pipefail

cd "$(dirname "$0")/.."

pip install --quiet -r requirements-dev.txt

if [ ! -f "${FRONTEND_DIST:-frontend/dist}/index.html" ]; then
    echo "No dashboard build found. Run 'npm ci && VITE_API_BASE_URL=/api npm run build'" >&2
    echo "in frontend/ from a Session before starting this Application." >&2
    exit 1
fi

# Serving the API through this process puts both on one origin, which
# removes CORS configuration entirely. Requires the build to have used
# VITE_API_BASE_URL=/api. Set API_PROXY_TARGET as a project variable, or
# uncomment the derivation below.
# export API_PROXY_TARGET="https://patients-api.${CDSW_DOMAIN}"

exec python scripts/serve_frontend.py
