PYTHON := .venv/bin/python
include .env.local
export

.PHONY: up down logs init check verify test run

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
