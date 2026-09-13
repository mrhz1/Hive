#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

pip install --quiet -r requirements-dev.txt

exec uvicorn app.main:app \
    --host "${CDSW_APP_HOST:-0.0.0.0}" \
    --port "${CDSW_APP_PORT:-8100}"
