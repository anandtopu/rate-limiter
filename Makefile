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
TELEMETRY_DB ?= data/telemetry.sqlite3

.PHONY: install dev test coverage lint security sbom format compose-up compose-down load-test ai-eval ai-eval-persisted ai-live-eval ai-live-eval-outage ai-research-report ai-ci-dry-run dashboard-screenshots redis-outage-demo

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

ai-eval:
	$(PYTHON) scripts/ai_eval.py

ai-eval-persisted:
	$(PYTHON) scripts/ai_eval.py --telemetry-db $(TELEMETRY_DB)

ai-live-eval:
	$(PYTHON) scripts/ai_live_eval.py --base-url $(BASE_URL)

ai-live-eval-outage:
	$(PYTHON) scripts/ai_live_eval.py --base-url $(BASE_URL) --include-redis-outage

ai-research-report:
	$(PYTHON) scripts/ai_research_report.py --output docs/AI_RESEARCH_REPORT.md

ai-ci-dry-run:
	$(PYTHON) scripts/ai_ci_dry_run.py

dashboard-screenshots:
	$(PYTHON) scripts/dashboard_screenshots.py --base-url $(BASE_URL)

redis-outage-demo:
	$(PYTHON) scripts/redis_outage_demo.py --base-url $(BASE_URL)
