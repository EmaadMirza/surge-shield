# Surge Shield

**An anti-scalper ticket gateway built to survive flash-sale chaos.**

Surge Shield is a high-concurrency ticket booking backend that simulates a real-world flash-sale scenario — *"500 seats, sale opens at 10:00 AM sharp, thousands of people click Buy in the same second"* — and guarantees: no crashes, no double-bookings, no bots winning, and real humans getting fair treatment.

---

## The 5 Core Objectives

| # | Objective | How It's Solved |
|---|-----------|-----------------|
| 1 | **No crashes under load** | FastAPI's async architecture holds thousands of open connections without freezing. The API sustained **189 RPS** across **6,302 requests** with zero `500` errors. |
| 2 | **Zero double-bookings** | A Redis Lua script atomically checks `SISMEMBER` and `SREM` in a single uninterruptible operation. Two buyers picking the same seat in the same millisecond? One wins, one gets a `409`. Always. |
| 3 | **Scalper / bot blocking** | A sliding-window rate limiter (30 req / 10s) with a 15-minute penalty box. Legitimate users pass through; a single IP spamming requests gets banned before it ever touches a seat. |
| 4 | **Fast response times** | The `/buy` endpoint never waits for PostgreSQL. It locks the seat in Redis (~1ms), responds `200 OK` to the user, and offloads the heavy database write to a Celery background worker. |
| 5 | **Reliable data persistence** | Celery drains the purchase queue into Postgres. If a DB write fails, the rollback mechanism re-adds the seats back into the Redis set so they aren't lost forever. |

---

## Architecture

```
                    ┌─────────────┐
                    │   Locust /  │
                    │   Client    │
                    └──────┬──────┘
                           │  HTTP
                           ▼
                    ┌─────────────┐
                    │   FastAPI   │──── Rate Limit Check (Redis Lua) ──→ 429 Ban
                    │  (uvicorn)  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼                         ▼
     ┌────────────────┐       ┌──────────────────┐
     │  Redis (Lua)   │       │  Celery Worker   │
     │  Atomic Lock   │       │  (Write-Behind)  │
     │  SISMEMBER +   │       │                  │
     │  SREM in one   │       │  Drains purchase │
     │  operation     │       │  queue → Postgres│
     └────────────────┘       └────────┬─────────┘
                                       │
                                       ▼
                              ┌──────────────────┐
                              │   PostgreSQL     │
                              │  (Source of      │
                              │   Truth)         │
                              └──────────────────┘
```

**Request Flow:**
1. Client sends `POST /buy` → FastAPI receives it.
2. Rate limiter (Redis Lua script) checks if this IP/user is flooding. If yes → `429`.
3. Seat lock (Redis Lua script) atomically checks if all requested seats exist in the Redis set and removes them. If any seat is missing → `409`.
4. FastAPI responds `200 OK` instantly.
5. A Celery task is dispatched to persist the purchase in PostgreSQL in the background.
6. If the Postgres write fails, the Celery task rolls back by re-adding the seats to the Redis set.

---

## Tech Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **API** | FastAPI + Uvicorn | Async HTTP server handling thousands of concurrent connections |
| **Database** | PostgreSQL + SQLAlchemy | Permanent source of truth for events and seat ownership |
| **Cache & Locks** | Redis / Memurai + Lua Scripts | Atomic seat locking & sliding-window rate limiting |
| **Task Queue** | Celery (Redis broker) | Async write-behind for database persistence |
| **Load Testing** | Locust | Simulating flash-sale surge traffic and bot attacks |
| **Package Manager** | uv | Fast Python package management |

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/events` | Create an event with a seat grid (`rows` × `seats_per_row`) |
| `POST` | `/buy` | Purchase up to 5 seats (rate-limited, atomic Redis lock) |
| `GET` | `/event/{id}` | Check available seat count for an event |
| `GET` | `/seats/{id}` | List all seats with their status and buyer info |

---

## Project Structure

```
surge-shield/
├── app/
│   ├── main.py             # FastAPI routes & rate-limit middleware
│   ├── models.py           # SQLAlchemy models (Event, Seat)
│   ├── schemas.py          # Pydantic request/response schemas
│   ├── database.py         # PostgreSQL engine & session factory
│   ├── redis_client.py     # Redis connection + Lua scripts (lock & rate-limit)
│   ├── celery_worker.py    # Celery app configuration
│   └── tasks.py            # Background task: persist purchase to Postgres
├── tests/
│   ├── test_concurrency.py      # Phase 2: Race condition proof (20 threads, 10 seats)
│   ├── test_rate_limit.py       # Phase 3: Rate limiter unit test
│   └── test_regression_phase4.py # Phase 4: Celery write-behind regression test
├── load_tests/                  # Locust load testing scripts
│   ├── locustfile_surge.py       # Phase 5: Legitimate 500-user flash-sale test
│   └── locustfile_bot.py         # Phase 5: Scalper bot attack test
├── docs/                        # Phase reports and final results
│   ├── phase-1-report.md
│   ├── phase-2-report.md
│   ├── phase-3-report.md
│   ├── phase-4-report.md
│   ├── phase-5-report.md
│   └── final_report.md
├── diagnostic_tools/            # Internal scripts for debugging and DB checks
├── .env.example            # Environment variable template (safe to commit)
├── pyproject.toml          # Project metadata & dependencies
└── README.md
```

---

## Running Locally

### Prerequisites

- **Python 3.11+**
- **PostgreSQL** running locally
- **Redis** (or [Memurai](https://www.memurai.com/) on Windows)
- **uv** package manager ([install guide](https://docs.astral.sh/uv/getting-started/installation/))

### 1. Clone & Install

```bash
git clone https://github.com/<your-username>/surge-shield.git
cd surge-shield
uv sync
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your real credentials:

```env
DATABASE_URL=postgresql://user:password@localhost:5432/surge_shield
REDIS_URL=redis://localhost:6379/0
RATE_LIMIT_MAX_REQUESTS=30
RATE_LIMIT_WINDOW_SECONDS=10
PENALTY_BOX_TTL_SECONDS=900
CELERY_BROKER_URL=redis://localhost:6379/1
```

### 3. Create the Database

```sql
CREATE DATABASE surge_shield;
```

Tables are auto-created on first startup via SQLAlchemy's `Base.metadata.create_all()`.

### 4. Start All Services

You need **three terminals** running simultaneously:

**Terminal 1 — API Server:**
```bash
uv run uvicorn app.main:app --reload
```

**Terminal 2 — Celery Worker:**
```bash
uv run celery -A app.celery_worker.celery_app worker --loglevel=info --pool=solo
```

**Terminal 3 — (Optional) Locust Load Test:**
```bash
uv run locust -f load_tests/locustfile_surge.py --host http://127.0.0.1:8000
```

### 5. Create an Event

Open the Swagger UI at `http://127.0.0.1:8000/docs` or use curl:

```bash
curl -X POST http://127.0.0.1:8000/events \
  -H "Content-Type: application/json" \
  -d '{"name": "Coldplay Live", "sale_start_time": "2026-09-01T10:00:00", "rows": 25, "seats_per_row": 40}'
```

This creates a 1,000-seat event and loads all seats into Redis.

---

## Testing

### Unit / Integration Tests

```bash
# Race condition proof (Phase 2) — 20 concurrent threads fight over 10 seats
uv run python tests/test_concurrency.py

# Rate limiter proof (Phase 3) — fires 12 rapid requests, confirms 429s
uv run python tests/test_rate_limit.py

# Write-behind regression (Phase 4) — confirms Celery persists to Postgres
uv run python tests/test_regression_phase4.py
```

### Load Tests (Phase 5)

**Legitimate Surge — 500 users, flash-sale simulation:**
```bash
uv run locust -f load_tests/locustfile_surge.py --host http://127.0.0.1:8000
# Locust UI → Users: 500, Spawn rate: 100
```

**Bot Attack — 5 scalper bots, zero wait time:**
```bash
uv run locust -f load_tests/locustfile_bot.py --host http://127.0.0.1:8000
# Locust UI → Users: 5, Spawn rate: 5
```

### Post-Test Verification

```bash
# Verify zero double-bookings in Postgres
uv run python diagnostic_tools/verify_phase5.py

# Check which IPs got banned
uv run python diagnostic_tools/check_penalties.py
```

---

## Load Test Results (Phase 5)

| Metric | Result |
|--------|--------|
| Total Requests | 6,302 |
| Peak RPS | 189 |
| Successful Purchases | 993 / 1,000 seats |
| Double Bookings | **0** (verified in Postgres) |
| Server Crashes (`500`) | **0** |
| Bot IPs Banned | 1 (`127.0.0.1` → penalty box) |

> The remaining 7 seats were unsold because the test was manually stopped before Locust exhausted the full seat pool.

For the full breakdown, see [`final_report.md`](./docs/final_report.md).

---

## Development Phases

This project was built incrementally across 5 phases, each solving one layer of the problem:

| Phase | Focus | Key Proof |
|-------|-------|-----------|
| **1** | Event + seat grid, naive `/buy` | Race condition exposed on purpose |
| **2** | Atomic seat locking (Redis Set + Lua) | 20 concurrent requests, 10 seats, zero double-bookings |
| **3** | Rate limiter + penalty box (Redis Lua) | 12 rapid requests → `429` after threshold |
| **4** | Celery write-behind (async Postgres) | Background persistence + rollback on failure |
| **5** | Full load test (Locust, 500 users) | 189 RPS, zero crashes, zero double-bookings, bots banned |

---

## License

This project was built as a learning exercise and engineering portfolio piece.
