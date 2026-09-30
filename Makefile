# use app/.venv if it exists, otherwise .venv (override with PYTHON=...)
PYTHON ?= $(shell [ -x app/.venv/bin/python ] && echo app/.venv/bin/python || echo .venv/bin/python)
include .env.local
export

.PHONY: up down logs init check verify test run \
        ocr-install ocr-models ocr-check-models ocr-preflight ocr-verify \
        deid dashboard intake-preview intake-start

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

# show what an intake run would do (moves nothing)
intake-preview:
	$(PYTHON) scripts/intake_preview.py

# de-identify everything in the intake folder
intake-start:
	$(PYTHON) scripts/intake_run.py

# run the de-id queue like the Cloudera Job
deid:
	$(PYTHON) scripts/deid_worker.py

# serve frontend/dist (run npm run build first)
dashboard:
	$(PYTHON) scripts/serve_frontend.py
