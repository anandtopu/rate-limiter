# Distributed Rate Limiter

A scalable, production-ready distributed rate limiter built with **FastAPI** and **Redis**. This project implements the **Token Bucket algorithm** utilizing robust Redis Lua scripting for atomic execution, guaranteeing exact consistency across distributed application clusters preventing race conditions.

Built as a demonstration of high-performance system design architectures, it intercepts incoming API requests, evaluates dynamic configurations instantaneously, and governs flow exactly according to defined metric ruleses.

## 🚀 Features

- **Token Bucket Engine**: Continuous token regeneration tracked safely in Redis.
- **Race Condition Prevention**: Employs pure Redis Lua scripting for atomic `HGET`, math computations, and `HSET` operations in a single synchronous Redis execution step.
- **Dynamic Rules Management**: Configure granular global limits and unique override thresholds (per IP or API Key) gracefully via `rules.json`.
- **Standards Compliant Headers**: Out-of-the-box support for appending standard rate limit tracking metrics seamlessly directly to the response wrapper:
  - `X-RateLimit-Limit`
  - `X-RateLimit-Remaining`
  - `X-RateLimit-Reset`
  - `Retry-After` (On HTTP 429)
- **High Availability (Fail-Open)**: Resilient degradation logic. If the Redis cluster collapses, the limiter natively fails open locally to avoid severing platform uptime.
- **AI / Agentic Signals (Passive Telemetry)**: A built-in, opt-in-by-consumption telemetry sidecar that observes rate-limit outcomes and produces actionable signals for application teams.
- **AI / Agentic Recommendations**: A lightweight “agent” generates tuning and reliability recommendations from recent request behavior (without auto-enforcing changes).

## 🛠 Tech Stack

- **Backend Framework**: Python 3.11+ / FastAPI (Async context, high-performance middleware)
- **State Integrity**: Redis (Alpine)
- **Deployment**: Docker & Docker Compose
- **Testing Engine**: Pytest with Pytest-Asyncio
- **AI Telemetry**: In-process signals aggregation (no external ML service required)

## 🏗 System Architecture

1. **Request Interception**: The FastAPI application catches all incoming traffic through the `rate_limit` dependency injected dynamically across routes.
2. **Identifier Extraction**: Resolves uniquely by `X-API-Key` or IP fallback (`request.client.host`).
3. **Atomic Redis Evaluation**: Executes the pre-loaded Lua script on the Redis cluster to recalculate remaining tokens matching elapsed timestamps. 
4. **Header Injection / Rejection**: On pass, headers decorate the HTTP 200 payload. On exhaustion, it forcibly denies access with an explicit standard HTTP 429 Error natively throwing the estimated `Retry-After` window.

### AI / Agentic Enhancements (Signals + Recommendations)

This project includes a small AI-oriented observability layer that helps teams answer questions like:

- Which routes are producing the most `429` responses?
- Which identifiers (API keys / IPs) are the top offenders?
- Are we operating in **fail-open** mode due to Redis errors (rate limiting bypass risk)?
- Which routes likely need tuning (too strict) vs. which clients are misbehaving?

The AI layer is implemented as **passive telemetry**:

- It does **not** change allow/deny decisions.
- It aggregates signals in-memory in a rolling time window.
- It exposes internal endpoints for dashboards/alerts.

#### AI Endpoints

- `GET /ai/signals`
  - Returns a snapshot of recent traffic signals: per-route request volume, `429` ratio, top offenders, and Redis fail-open counts.
- `POST /ai/recommendations`
  - Generates a fresh set of recommendations based on the last few minutes of observed behavior.

> Recommendation output is designed to be consumed by application teams or automation pipelines. It intentionally avoids making automated policy changes.

## 🐳 Running the Project (Docker)

To run the application and Redis side-by-side using the provided containerization strategy:

```bash
docker-compose up --build -d
```

The API will instantly become available locally at `http://localhost:8000`.

## 🧑‍💻 Running Locally (Python 3.13)

This repo supports Python 3.13. For local development, use a virtual environment so dependencies install into the same interpreter used for tests.

```bash
py -3.13 -m venv .venv
./.venv/Scripts/python -m pip install -r requirements.txt
./.venv/Scripts/python -m uvicorn app.main:app --reload
```

### Health Check (Testing Limits)
Once the instance is available, you can blast the endpoint to view rate limits in real-time. Wait for it to breach the threshold and monitor the output:

```bash
# Powershell
for ($i=1; $i -le 15; $i++) { curl.exe -s -v http://localhost:8000/health }

# Bash
for i in {1..15}; do curl -s -v http://localhost:8000/health; done
```

## ⚙️ Configuration (`rules.json`)

Adjust limits natively without rebuilding the underlying codebase by altering `rules.json`.

```json
{
  "routes": {
    "/api/data": {
      "global_limit": {
        "rate": 1.0,        // Tokens to add per second
        "capacity": 5       // Maximum burst capacity
      },
      "overrides": {
        "premium_user_key": {
          "rate": 10.0,
          "capacity": 100
        }
      }
    }
  }
}
```

## 🧪 Automated Testing

We cover full Integration / Edge Case analysis (Simulating massive Race Conditions concurrently).

*Testing natively outside docker demands a local Redis Instance, or compatible Lua configurations.*
```bash
# If running through compose:
docker-compose exec web pytest
```

If running locally with the Python 3.13 venv:

```bash
./.venv/Scripts/pytest -q
```
