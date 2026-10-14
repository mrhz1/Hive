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
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port $(CDSW_APP_PORT) --reload --reload-dir app

ocr-install:
	$(MAKE) -C OCR venvs install

ocr-models:
	$(MAKE) -C OCR models

ocr-check-models:
	$(MAKE) -C OCR check-models

ocr-preflight:
	$(MAKE) -C OCR preflight

ocr-verify:
	$(MAKE) -C OCR run verify

intake-preview:
	$(PYTHON) scripts/intake_preview.py

intake-start:
	$(PYTHON) scripts/intake_run.py

deid:
	$(PYTHON) scripts/deid_worker.py

dashboard:
	$(PYTHON) scripts/serve_frontend.py
