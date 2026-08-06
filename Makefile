# The API venv. Checked rather than hardcoded because the repo has been
# built both ways; override with `make PYTHON=... <target>`.
PYTHON ?= $(shell [ -x app/.venv/bin/python ] && echo app/.venv/bin/python || echo .venv/bin/python)
include .env.local
export

.PHONY: up down logs init check verify test run \
        ocr-install ocr-models ocr-check-models ocr-preflight ocr-verify \
        deid dashboard

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
	$(PYTHON) -m uvicorn app.main:app --host 0.0.0.0 --port $(CDSW_APP_PORT) --reload

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

# Drain the de-identification queue, the same way the Cloudera Job does.
deid:
	$(PYTHON) scripts/deid_worker.py

# Serve frontend/dist the way the Cloudera Application does. Run
# `npm run build` in frontend/ first.
dashboard:
	$(PYTHON) scripts/serve_frontend.py
