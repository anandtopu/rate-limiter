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

## 🛠 Tech Stack

- **Backend Framework**: Python 3.11+ / FastAPI (Async context, high-performance middleware)
- **State Integrity**: Redis (Alpine)
- **Deployment**: Docker & Docker Compose
- **Testing Engine**: Pytest with Pytest-Asyncio

## 🏗 System Architecture

1. **Request Interception**: The FastAPI application catches all incoming traffic through the `rate_limit` dependency injected dynamically across routes.
2. **Identifier Extraction**: Resolves uniquely by `X-API-Key` or IP fallback (`request.client.host`).
3. **Atomic Redis Evaluation**: Executes the pre-loaded Lua script on the Redis cluster to recalculate remaining tokens matching elapsed timestamps. 
4. **Header Injection / Rejection**: On pass, headers decorate the HTTP 200 payload. On exhaustion, it forcibly denies access with an explicit standard HTTP 429 Error natively throwing the estimated `Retry-After` window.

## 🐳 Running the Project (Docker)

To run the application and Redis side-by-side using the provided containerization strategy:

```bash
docker-compose up --build -d
```

The API will instantly become available locally at `http://localhost:8000`.

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
