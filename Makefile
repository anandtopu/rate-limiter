PYTHON ?= .venv/Scripts/python.exe
PYTEST ?= .venv/Scripts/pytest.exe
RUFF ?= .venv/Scripts/ruff.exe
UVICORN ?= .venv/Scripts/uvicorn.exe
UV ?= uv
PIP_AUDIT ?= .venv/Scripts/pip-audit.exe
PIP_AUDIT_CACHE ?= .pip-audit-cache
BANDIT ?= .venv/Scripts/bandit.exe
BASE_URL ?= http://localhost:8001

.PHONY: install dev test lint security format compose-up compose-down load-test

install:
	$(UV) pip install --python $(PYTHON) -r requirements-dev.txt

dev:
	$(UVICORN) app.main:app --reload

test:
	$(PYTEST) -q

lint:
	$(RUFF) check .

security:
	$(PIP_AUDIT) -r requirements.txt --cache-dir $(PIP_AUDIT_CACHE)
	$(BANDIT) -q -r app -c pyproject.toml

format:
	$(RUFF) format .

compose-up:
	docker compose up --build

compose-down:
	docker compose down

load-test:
	$(PYTHON) scripts/load_test.py --base-url $(BASE_URL)
