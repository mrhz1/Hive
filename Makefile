# The API venv. Checked rather than hardcoded because the repo has been
# built both ways; override with `make PYTHON=... <target>`.
PYTHON ?= $(shell [ -x app/.venv/bin/python ] && echo app/.venv/bin/python || echo .venv/bin/python)
include .env.local
export

.PHONY: up down logs init check verify test run \
        ocr-install ocr-models ocr-check-models ocr-preflight ocr-verify \
        deid dashboard intake intake-apply intake-deid intake-run intake-watch

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

init:
	$(PYTHON) scripts/init_db.py

check:
	$(PYTHON) scripts/check_hive.py

verify:
	$(PYTHON) scripts/verify_acid.py

test:
	$(PYTHON) -m pytest

run:
	# --reload-exclude, not --reload-dir: uvicorn's watchfiles supervisor
	# folds any --reload-dir back into watching the whole cwd whenever
	# that dir is (as it always is here) a subdirectory of cwd -- see
	# WatchFilesReload.__init__ in uvicorn/supervisors/watchfilesreload.py.
	# --reload-exclude does not go through that path.
	#
	# storage/ is excluded because uploads land under storage/patient_files,
	# inside the project tree uvicorn otherwise watches. A stored .py file
	# (nothing stops one being uploaded) looked like a source change and
	# restarted the server mid-batch -- taking the in-memory upload-job
	# registry with it, so the frontend's next poll got 404 for a batch
	# that had, in fact, finished.
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port $(CDSW_APP_PORT) --reload --reload-exclude "$(CURDIR)/storage"

# --- de-identification -------------------------------------------------
# Two virtualenvs: paddle and presidio cannot share one. See OCR/README.md.
ocr-install:
	$(MAKE) -C OCR venvs install

# Fill OCR/models from the network. Run this where there IS network:
# Cloudera AI blocks github and huggingface, so the store is built here
# and copied there. See OCR/models/README.md.
ocr-models:
	$(MAKE) -C OCR models

# Load every staged model with the network off. Run this ON the target
# after copying OCR/models across -- it is the only check that catches a
# truncated weight file.
ocr-check-models:
	$(MAKE) -C OCR check-models

ocr-preflight:
	$(MAKE) -C OCR preflight

# The check that matters: re-OCR the redacted sample and hunt for leaks.
ocr-verify:
	$(MAKE) -C OCR run verify

# What a dropped batch would do. Reads only -- see scripts/intake_sweep.py.
intake:
	$(PYTHON) scripts/intake_sweep.py

# The same sweep, recorded in Hive. Still redacts nothing.
intake-apply:
	$(PYTHON) scripts/intake_sweep.py --apply

# The automatic path: once a push has finished landing, sweep and redact.
# Once, as a scheduled Job would; or for ever, checking every minute.
intake-run:
	$(PYTHON) scripts/intake_run.py

intake-watch:
	$(PYTHON) scripts/intake_run.py --watch

# Redact everything the sweep queued, DEID_WORKERS at a time.
intake-deid:
	$(PYTHON) scripts/intake_deid.py

# Drain the de-identification queue, the same way the Cloudera Job does.
deid:
	$(PYTHON) scripts/deid_worker.py

# Serve frontend/dist the way the Cloudera Application does. Run
# `npm run build` in frontend/ first.
dashboard:
	$(PYTHON) scripts/serve_frontend.py
