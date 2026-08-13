# Surge Shield — Phase 4 Report

**Project:** Anti-Scalper Ticket Gateway (Surge Shield)
**Phase:** 4 — Async Persistence (Celery)
**Stack:** FastAPI, PostgreSQL, SQLAlchemy (sync), Pydantic, Redis (Cloud), redis-py, Celery, Lua, uv, Windows/PowerShell
**Status:** Complete

---

## 1. What Phase 4 Set Out to Do

Solve objective 4: fast responses, no waiting on slow database writes. Up through Phase 3, a successful Redis seat lock was still followed by a *synchronous* write to Postgres before the user got a response — meaning the user sat there waiting on the database even though the sale had already been irreversibly decided the moment Redis's Lua script locked the seat. Nothing about seat-locking (Phase 2) or rate-limiting/penalty-box (Phase 3) logic was to change in this phase — and nothing did.

## 2. What Was Actually Built

- **Celery installed** (`uv add celery`) as the background task queue framework.
- **`app/celery_worker.py`** — the Celery app instance, configured with the broker connection, and pointed at `app/tasks.py` so it knows which task functions exist.
- **`app/tasks.py`** — a standalone file (kept separate from `celery_worker.py` by deliberate choice) containing `save_purchase_task`, the relocated Postgres-write logic, including the Phase 2 rollback safety net.
- **Updated `POST /buy`** in `main.py` — the inline `try/except` Postgres write block was removed entirely. In its place, a single `save_purchase_task.delay(...)` call enqueues the job, and the route returns success immediately afterward — no DB session is opened in this route at all anymore.
- **Two processes now run side by side** during development: `uvicorn` (unchanged) and a separate Celery worker process, started with the Windows-specific `--pool=solo` flag.

## 3. Infrastructure Decision: Broker Database Index (`/1` → `/0`)

The original plan (per the Phase 4 spec) was to point `CELERY_BROKER_URL` at the same Redis Cloud instance already used for seat locks and rate limits, but on a different logical database index (`/1` instead of `/0`) — purely to keep task-queue keys logically separate from `available_seats:*` and `rate_limit:*` keys when browsing Redis manually.

In practice, this failed immediately on worker startup with `DB index is out of range`. Investigation confirmed this isn't a free-tier limitation that a paid plan would lift — it's how Redis Cloud fundamentally works. Redis's own documentation confirms Redis Software/Cloud does not support multiple logical databases via the `SELECT` command; each Redis Cloud "database" is a separate, independently-provisioned instance, not a numbered slot inside one shared instance the way self-hosted Redis's 16 default databases work.

**Fix:** `CELERY_BROKER_URL` was pointed at `/0` — the same database already holding `available_seats:{event_id}`, `rate_limit:{ip}`, and `penalty_box:{ip}` keys. This is safe with no realistic collision risk: Celery's internal key names (`celery`, `_kombu.*`, `unacked`, etc.) share no naming pattern whatsoever with this project's own keys. The `/1` split was never a correctness requirement, only a tidiness preference that this specific hosting setup doesn't support.

## 4. Code Additions

### `app/celery_worker.py`

```python
import os
from dotenv import load_dotenv
from celery import Celery

load_dotenv()

celery_app = Celery(
    "surge_shield",
    broker=os.getenv("CELERY_BROKER_URL"),
    include=["app.tasks"]
)
```

`include=["app.tasks"]` is the key line here — since the task function lives in a separate file rather than inside this one, this tells Celery to import `app/tasks.py` at startup so it recognizes `save_purchase_task` when a job for it arrives. Without it, the worker starts fine but doesn't know the task exists.

### `app/tasks.py`

```python
import logging
from app.celery_worker import celery_app
from app.database import SessionLocal
from app.models import Seat
from app.redis_client import redis_client

logger = logging.getLogger(__name__)

@celery_app.task(name="save_purchase_task")
def save_purchase_task(event_id: int, seat_numbers: list[str], buyer_id: str):
    db = SessionLocal()
    try:
        seats = db.query(Seat).filter(
            Seat.event_id == event_id,
            Seat.seat_number.in_(seat_numbers)
        ).all()

        for seat in seats:
            seat.status = "sold"
            seat.buyer_id = buyer_id

        db.commit()
        logger.info(f"Purchase saved: event {event_id}, seats {seat_numbers}, buyer {buyer_id}")

    except Exception as e:
        db.rollback()
        redis_client.sadd(f"available_seats:{event_id}", *seat_numbers)
        logger.error(f"Failed to save purchase for event {event_id}, seats {seat_numbers}: {e}")

    finally:
        db.close()
```

This task opens its own `SessionLocal()` — it cannot reuse the original request's DB session, since it runs in a completely separate process, after the original request has already finished and returned. The `except` block is the Phase 2 rollback safety net, moved here unchanged in logic: if the Postgres write fails for any reason, the seats are `SADD`'d back into Redis's available set so they aren't stranded as permanently "gone" with no record anywhere. `logger` (Python's built-in `logging` module) is used instead of `print()` specifically because nobody watches a background worker live the way a synchronous request surfaces errors immediately — logging timestamps and labels every message so failures are traceable after the fact.

### Updated `POST /buy` (in `main.py`)

```python
@app.post("/buy", response_model=BuyResponse, dependencies=[Depends(check_rate_limit)])
def buy_seats(order: BuyRequest):
    requested = set(order.seat_numbers)
    if len(requested) != len(order.seat_numbers):
        raise HTTPException(status_code=400, detail="Duplicate seat numbers in request.")

    seat_numbers = list(order.seat_numbers)

    result = lock_seats(
        keys=[f"available_seats:{order.event_id}"],
        args=seat_numbers
    )
    seat_status = dict(zip(seat_numbers, result))

    if any(status == 0 for status in seat_status.values()):
        raise HTTPException(
            status_code=409,
            detail={"message": "One or more seats unavailable", "seats": seat_status}
        )

    save_purchase_task.delay(order.event_id, seat_numbers, order.user_id)

    return BuyResponse(message="Seats successfully purchased.", seat_numbers=seat_numbers)
```

The `db = SessionLocal()` line, the outer `try/finally: db.close()` wrapper, and the inner Postgres-write `try/except` block were all removed — this route no longer touches Postgres at all. `save_purchase_task.delay(...)` publishes the job to the broker queue and returns almost instantly; it does not wait for the task to run. The response returns `seat_numbers` directly (the original request list) rather than re-querying Postgres for what was sold, since by the time execution reaches that line, the `if any(status == 0 ...)` check above guarantees every requested seat was already successfully locked — there is no other path that reaches the final `return`.

## 5. Windows-Specific Gotcha

Celery's default worker pool (`prefork`) relies on Unix process forking, unsupported on Windows. The worker must be started with `--pool=solo`:

```powershell
uv run celery -A app.celery_worker worker --loglevel=info --pool=solo
```

`-A app.celery_worker` points the `celery` CLI at the `celery_app` object built in Step 3. `--pool=solo` runs everything in a single process instead of attempting to fork — slower under heavy concurrent load than `prefork` would be on Linux/Mac, but sufficient for this project's scale.

## 6. Design Decisions

- **`tasks.py` kept separate from `celery_worker.py`**, by deliberate choice, requiring the `include=["app.tasks"]` line to connect the two.
- **Shared broker database (`/0`)** instead of a separate index, forced by Redis Cloud's architecture (see Section 3) — confirmed safe due to non-overlapping key naming.
- **Fault injection over infrastructure disruption** for the rollback test — a temporary forced exception in `tasks.py` was used instead of stopping the local Postgres service, since it exercises the exact same `except` code path with zero risk to the actual database or other running services.
- **Scaled-down regression test (4 requests, not 20)** — Phase 2's original concurrency test would trip Phase 3's rate limiter (10 requests/10 seconds per IP) if rerun unmodified, since all requests originate from one local machine and look like one IP. Rather than temporarily raising the rate limit, the test was shrunk to 4 simultaneous requests (2 users competing for each of 2 seats) — small enough to stay under the threshold while preserving the same proof structure: a known expected win/loss split and a duplicate-seat check.

## 7. Errors Encountered & Fixes

- **`FileNotFoundError` in `uvicorn --reload` during `uv add celery`** — uvicorn's file-watcher scans the entire project directory, including `.venv/site-packages`, looking for changed `.py` files to trigger a reload. Running `uv add celery` in a separate terminal while `uvicorn --reload` was still running caused the watcher to catch a temporary file mid-creation/deletion inside `.venv/Lib/site-packages/tzdata` during the package install, since installers briefly create and remove temp files. Not a bug in the project — two unrelated processes briefly colliding over the same folder. Resolved by restarting the server; going forward, `uvicorn --reload` is stopped before running any `uv add`/install commands.
- **`DB index is out of range` on worker startup** — see Section 3 for full explanation. Fixed by switching `CELERY_BROKER_URL` from `/1` to `/0`.
- **False-alarm `409` during first live test** — caused by testing against the wrong `event_id`, not a bug in Phase 4's changes. Confirmed by checking `GET /available-seats/{event_id}` against the correct event.

## 8. Testing & Proof

### Live manual test (happy path)

A test event (event 6) was created, and seats `A1`, `B1`, `C1` were purchased. The FastAPI terminal returned `200 OK` essentially instantly. Within roughly 0.2 seconds, the Celery worker terminal showed:

```
[2026-08-12 19:34:00,033: INFO/MainProcess] Task save_purchase_task[bf6f875d-3c87-497f-af21-183e6cbf9faa] received
[2026-08-12 19:34:00,224: INFO/MainProcess] Purchase saved: event 6, seats ['A1', 'B1', 'C1'], buyer user1
[2026-08-12 19:34:00,224: INFO/MainProcess] Task save_purchase_task[bf6f875d-3c87-497f-af21-183e6cbf9faa] succeeded in 0.15599999999903957s: None
```

This confirms the full write-behind pattern working end-to-end: the response returned before the worker had even started processing the job, and the job completed successfully a fraction of a second later, fully decoupled from the request/response cycle.

*Note: the "Latency check" (artificially slowing the DB write to prove the response doesn't wait on it) and "Eventual consistency check" (explicitly polling `GET /seats` to watch the transition) from the original Phase 4 spec were not run as dedicated, isolated tests. Both were informally observed during this manual test — the fast response and the confirmed Postgres write — but not proven in isolation the way the rollback and regression tests below were.*

### Rollback / failure test

A line (`raise Exception("Simulated DB failure")`) was temporarily added to `save_purchase_task`, immediately before `db.commit()`, to force the Postgres write to fail on purpose without touching any real infrastructure. After restarting the worker and buying seat `C5` on event 6, the worker logged:

```
[2026-08-12 22:41:05,752: INFO/MainProcess] Task save_purchase_task[dc9f9cf1-9e9b-48bb-9b64-2bf738413bfe] received
[2026-08-12 22:41:06,341: ERROR/MainProcess] Failed to save purchase for event 6, seats ['C5']: Simulated DB failure
[2026-08-12 22:41:06,341: INFO/MainProcess] Task save_purchase_task[dc9f9cf1-9e9b-48bb-9b64-2bf738413bfe] succeeded in 0.5779999999977008s: None
```

The `ERROR` line confirms the `except` block caught the forced exception and ran the rollback logic. `GET /available-seats/6` was checked afterward and showed `C5` back in Redis's available set — the `redis_client.sadd(...)` rollback line working correctly. `GET /seats/6` confirmed the seat still showed `status: "available"` in Postgres — proving no zombie state: the seat was neither lost nor falsely marked sold. Note Celery's own "succeeded" status here refers only to the Python function completing without an *unhandled* exception escaping it — not a judgment on whether the purchase itself saved; the `except` block handling the error gracefully is exactly what "succeeded" is reporting. The forced-exception line was removed afterward and the worker restarted to return to normal behavior.

### Regression test (double-booking still prevented)

Phase 2's original concurrency test (20 simultaneous requests) was scaled down to 4, to avoid tripping Phase 3's rate limiter (10 requests/10 seconds per IP) when run from a single local machine. `test_regression_phase4.py` creates a fresh 1-row × 2-seat event via `POST /events`, then fires 4 simultaneous `POST /buy` requests via `asyncio.gather` — two different users competing for seat `A1`, two different users competing for seat `B1` — and asserts exactly 2 successes, 2 failures, and no duplicate seat among the winners.

The test passed: exactly a 2/2 split, with no seat won by more than one user. This confirms Phase 2's Redis Lua atomic lock — the actual decision-making mechanism for who wins a seat — is completely unaffected by Phase 4's changes, since only what happens *after* a successful lock (background task vs. inline write) changed, not the lock itself.

## 9. What Problem This Phase Solved, and How

The problem: through Phase 3, a user's `/buy` request wasn't actually finished the moment Redis's Lua script locked their seat — it still had to wait for a synchronous Postgres write to complete before getting a response, even though nothing about that write could change who won the seat. That wait bought no correctness, only latency.

The solution: the Postgres write was relocated into a Celery background task. Once the Redis lock succeeds, `POST /buy` enqueues the write as a job and returns success immediately — the write itself happens moments later, in a separate worker process, fully decoupled from the request. This is the write-behind pattern: "locked in Redis" is the moment the sale is decided; "written to Postgres" is simply when it becomes durably recorded — two different moments that no longer block each other. The Phase 2 rollback safety net moved along with the write, so a failed background save still correctly returns the seat to Redis's available pool instead of leaving it stranded. Both the failure path and the double-booking protection were proven under direct test, not just assumed to still work.

## 10. Ready for Phase 5

Phase 4's write-behind layer is confirmed working end-to-end, sitting cleanly on top of Phases 1–3 without altering any of their logic. Before Phase 5 (load testing) begins, the Redis Cloud vs. local Docker/WSL2 trade-off — flagged since Phase 2 — needs to be resolved, since Redis Cloud's network latency could distort load-test results in a way that wouldn't reflect the system's real performance. See the accompanying Phase 5 introduction document.
