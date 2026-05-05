PYTHON ?= .venv/Scripts/python.exe
PYTEST ?= .venv/Scripts/pytest.exe
RUFF ?= .venv/Scripts/ruff.exe
UVICORN ?= .venv/Scripts/uvicorn.exe
UV ?= uv
PIP_AUDIT ?= .venv/Scripts/pip-audit.exe
PIP_AUDIT_CACHE ?= .pip-audit-cache
BANDIT ?= .venv/Scripts/bandit.exe
CYCLONEDX ?= .venv/Scripts/cyclonedx-py.exe
SBOM_PATH ?= sbom.json
BASE_URL ?= http://localhost:8001

.PHONY: install dev test coverage lint security sbom format compose-up compose-down load-test redis-outage-demo

install:
	$(UV) pip install --python $(PYTHON) -r requirements-dev.txt

dev:
	$(UVICORN) app.main:app --reload

test:
	$(PYTEST) -q

coverage:
	$(PYTEST) --cov=app --cov=scripts --cov-report=term-missing --cov-report=xml

lint:
	$(RUFF) check .

security:
	$(PIP_AUDIT) -r requirements.txt --cache-dir $(PIP_AUDIT_CACHE)
	$(BANDIT) -q -r app -c pyproject.toml

sbom:
	$(CYCLONEDX) requirements requirements.txt --of JSON --output-reproducible --output-file $(SBOM_PATH)

format:
	$(RUFF) format .

compose-up:
	docker compose up --build

compose-down:
	docker compose down

load-test:
	$(PYTHON) scripts/load_test.py --base-url $(BASE_URL)

redis-outage-demo:
	$(PYTHON) scripts/redis_outage_demo.py --base-url $(BASE_URL)
