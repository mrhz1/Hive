#!/usr/bin/env bash
# Cloudera AI Application entrypoint for the FastAPI service.
#
# An Application runs a command, so this is that command. It is a script
# rather than a one-liner in the UI so the install step and the run step
# are versioned together -- the two drift otherwise, and the symptom is
# an Application that starts against last month's dependencies.
#
# Note what is NOT here: neither OCR virtualenv. With DEID_BACKEND=cml_job
# the API only marks the row and asks Cloudera to start the Job, so the
# web process carries none of the ML stack.
set -euo pipefail

cd "$(dirname "$0")/.."

# pip installs into /home/cdsw/.local, which persists, so this is a no-op
# on every restart after the first.
pip install --quiet -r requirements-dev.txt

# 0.0.0.0 because the platform's proxy connects from outside the process
# namespace. CDSW_APP_PORT is injected; the fallback only matters when
# running this script locally.
exec uvicorn app.main:app \
    --host "${CDSW_APP_HOST:-0.0.0.0}" \
    --port "${CDSW_APP_PORT:-8100}"
