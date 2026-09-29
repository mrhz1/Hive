# use app/.venv if it exists, otherwise .venv (override with PYTHON=...)
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
	# exclude storage/ so uploaded files don't trigger a reload
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port $(CDSW_APP_PORT) --reload --reload-exclude "$(CURDIR)/storage"

# de-identification (two venvs, see OCR/README.md)
ocr-install:
	$(MAKE) -C OCR venvs install

# download models (needs internet, then copy OCR/models to Cloudera)
ocr-models:
	$(MAKE) -C OCR models

# load all models offline to check the copy is complete
ocr-check-models:
	$(MAKE) -C OCR check-models

ocr-preflight:
	$(MAKE) -C OCR preflight

# re-OCR the redacted sample and check for leaks
ocr-verify:
	$(MAKE) -C OCR run verify

# intake dry run
intake:
	$(PYTHON) scripts/intake_sweep.py

# intake sweep, saved to Hive
intake-apply:
	$(PYTHON) scripts/intake_sweep.py --apply

# sweep + redact once a push has finished (once, or every minute)
intake-run:
	$(PYTHON) scripts/intake_run.py

intake-watch:
	$(PYTHON) scripts/intake_run.py --watch

# redact all queued intake files
intake-deid:
	$(PYTHON) scripts/intake_deid.py

# run the de-id queue like the Cloudera Job
deid:
	$(PYTHON) scripts/deid_worker.py

# serve frontend/dist (run npm run build first)
dashboard:
	$(PYTHON) scripts/serve_frontend.py
