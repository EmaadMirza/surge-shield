# Surge Shield — Phase 2 Report

**Project:** Anti-Scalper Ticket Gateway (Surge Shield)
**Phase:** 2 — Seat Locking (Redis)
**Stack:** FastAPI, PostgreSQL, SQLAlchemy (sync), Pydantic, Redis (Cloud), redis-py, Lua, uv, Windows/PowerShell
**Status:** Complete

---

## 1. What Phase 2 Set Out to Do

Close the race condition left unfixed in Phase 1 — where two near-simultaneous `POST /buy` requests could both read the same seat as available before either committed its "sold" status, allowing a seat to be double-booked. The goal was narrow and specific: fix double-booking using Redis, and nothing else. No rate limiting, no penalty box, no Celery — those are later phases.

## 2. Infrastructure Decision: Redis Cloud Instead of Local Docker

The original plan called for running Redis locally via Docker Desktop, requiring WSL2 as its backend on Windows. WSL2 installation failed with a persistent "system cannot find the path specified" error. Standard fixes were attempted in order — updating WSL, manually enabling the required Windows features (`Microsoft-Windows-Subsystem-Linux` and `VirtualMachinePlatform`) via DISM, and a full system restart. The error persisted after all of these, pointing to a deeper, Windows-level issue rather than a simple missing-feature problem.

Rather than sink further time into a low-level Windows fix, the decision was made to use **Redis Cloud's free tier** — a hosted Redis instance — for Phases 2 through 4. This unblocked development immediately with no functional downside for these phases, since none of them depend on raw local speed. The one deliberate exception: **Phase 5 (load testing)** will need this revisited, since Redis Cloud's network latency could distort load-test results in a way that wouldn't reflect the system's actual performance. That trade-off is flagged for Mirza to decide on before Phase 5 begins — Docker/WSL should be revisited and fixed at that point, once there's no deadline pressure.

The connection is configured entirely through one environment variable:

```
REDIS_URL=redis://default:<password>@<redis-cloud-endpoint>
```

`redis-py`'s `redis.from_url(...)` parses this single string into host, port, username, and password automatically — no separate connection arguments needed.

## 3. What Was Actually Built

- **Redis Set per event** — `available_seats:{event_id}`, holding the seat numbers not yet sold for that event.
- **Seeding on event creation** — `POST /events` now, immediately after committing the generated seat grid to Postgres, adds every seat number into that event's Redis Set in a single batched call:

  ```python
  redis_client.sadd(f"available_seats:{new_event.id}", *seat_numbers)
  ```

- **Atomic multi-seat lock script (Lua)** — a script that checks every requested seat's availability, and only removes them from the Redis Set if *all* requested seats are available. If even one is unavailable, nothing is removed and the whole batch fails together — an intentional all-or-nothing design (see Section 5). The full script is shown in Section 4.
- **Per-seat status feedback** — rather than a plain success/fail signal, the lock script reports the outcome for *each individual requested seat*, so a failed request tells the caller exactly which seat(s) were the problem, not just that "something" failed.
- **Updated `POST /buy` flow** — Redis is now checked *before* Postgres is touched at all:

  ```python
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
  ```

  Only once Redis confirms a successful atomic lock does the code proceed to update Postgres, marking those seats sold. If the Redis lock fails, a `409` is returned immediately with the per-seat breakdown, and nothing is written to Postgres or altered in Redis.

- **Rollback safety net** — if the Redis lock succeeds but the subsequent Postgres write fails for any reason (e.g. a dropped connection), the locked seats are added back into the Redis Set, undoing the lock so they don't get permanently stuck as unavailable with no record of a sale anywhere:

  ```python
  except Exception:
      db.rollback()
      redis_client.sadd(f"available_seats:{order.event_id}", *seat_numbers)
      raise HTTPException(status_code=500, detail="Failed to save purchase, please try again.")
  ```

- **New endpoint — `GET /available-seats/{event_id}`** — reads directly from the Redis Set to show a live, real-time view of what's currently bookable, ahead of committing to a purchase:

  ```python
  @app.get("/available-seats/{event_id}")
  def get_available_seats(event_id: int):
      return redis_client.smembers(f"available_seats:{event_id}")
  ```

  This sits alongside the existing `GET /seats/{event_id}` (Postgres), which remains the detailed, authoritative record including buyer information.

## 4. How Redis and Lua Actually Solve the Problem

Redis by itself is single-threaded — it only ever processes one command at a time, in strict order. That fact alone protects a *single* command from ever colliding with itself. But checking "is this seat available" and then acting on "remove this seat" are naturally two separate steps. If those two steps are sent to Redis as two separate commands from the application code, a gap exists between them — and in that gap, a second, competing request can slip in, see the same seat reported as available, and also attempt to claim it. That's the same shape of bug Phase 1 had in Postgres, just relocated one layer down into Redis.

Lua scripting closes that gap. A Lua script isn't sent to Redis as separate commands — it's handed over as one indivisible unit of work. Redis runs the entire script from start to finish for one request before it will even begin looking at the next one. So for any given seat, whichever request's script reaches Redis first runs its full check-and-lock sequence completely, with no possibility of another request's check landing in the middle of it. The seat's fate — available or taken — is fully resolved before any other request can even start evaluating it.

This is also why the lock script deliberately checks *all* requested seats before removing *any* of them, rather than checking-and-removing one seat at a time within the same script. If a batch request for several seats partially succeeded before discovering a later seat was unavailable, there would be no clean way to safely undo the seats already removed mid-script. Checking everything first, and only then acting, keeps the operation genuinely all-or-nothing — the batch either fully succeeds or changes nothing at all.

The full script, registered once at startup via `redis_client.register_script(...)`:

```lua
local statuses = {}
local all_available = true

for i, seat in ipairs(ARGV) do
    if redis.call("SISMEMBER", KEYS[1], seat) == 1 then
        statuses[i] = 1
    else
        statuses[i] = 0
        all_available = false
    end
end

if not all_available then
    return statuses
else
    for i, seat in ipairs(ARGV) do
        redis.call("SREM", KEYS[1], seat)
    end
    return statuses
end
```

`KEYS[1]` is the one Redis key the script touches — `available_seats:{event_id}` — passed in from Python's `keys=[...]` argument. `ARGV` is the list of requested seat numbers, passed in via `args=`. The first loop checks every seat and records a `1` or `0` per seat without stopping early, so the full picture is known even if something fails partway through. Only if every seat passed does the second loop actually run, removing each one. The `statuses` table is returned either way, giving the caller a per-seat result regardless of overall success or failure.

## 5. Design Decision: All-or-Nothing, Not Partial Fulfillment

A deliberate choice was made that a multi-seat request either succeeds completely or fails completely — there is no partial outcome where a user gets some of their requested seats but not others. This was chosen because Surge Shield's named-seat selection model implies group intent (e.g. wanting to sit together), where receiving only some of the requested seats could be a worse outcome than receiving none — the user would be left with a booking that doesn't accomplish what they actually wanted, discovered only after the fact. Partial fulfillment remains a valid alternative design for a different kind of booking system (one where users simply want "any N seats" with no togetherness requirement), but was consciously not the fit here.

A failed request still returns full transparency on *why* it failed, rather than a generic error — the caller sees exactly which seats were available and which weren't:

```json
{
  "detail": {
    "message": "One or more seats unavailable",
    "seats": {"A1": 0, "G9": 1, "C4": 1}
  }
}
```

Here, `0` means that seat was already taken and blocked the whole batch; `1` means it was available but not locked, since the batch failed together.

## 6. Testing & Proof

A concurrency test was built to prove the fix, not just assume it. The test creates a small test event, then fires many simultaneous, overlapping `POST /buy` requests at once — specifically, every seat in the test event is targeted by exactly two different competing users at the same moment, so the correct outcome is known in advance: exactly one winner and one loser per seat, with zero duplicates.

Running the test confirmed exactly the expected split, with no seat won by more than one user. This is the concrete evidence that the atomic locking mechanism holds under real concurrent pressure, not just under one-at-a-time manual testing — manual testing alone could never actually recreate a genuine race condition, since it always leaves a natural gap between actions.

The core of the proof, once all 20 simultaneous requests had completed:

```python
successes = [r for r in results if r[2] == 200]
failures = [r for r in results if r[2] == 409]

assert len(successes) == 10, f"Expected 10 successes, got {len(successes)}"
assert len(failures) == 10, f"Expected 10 failures, got {len(failures)}"

seats_won = [r[1] for r in successes]
assert len(seats_won) == len(set(seats_won)), "DOUBLE BOOKING DETECTED!"
```

The first two assertions confirm the split was exactly 10 winners and 10 losers, matching the known-correct outcome. The third is the actual double-booking detector: converting the list of won seats into a `set` removes any duplicates, so if a seat had been sold to two different users, the set's length would be shorter than the list's — and the assertion would fail loudly. It didn't; all 10 winning seats were unique.

Actual output from the run:

```
Created test event 5
Successes: 10  Failures: 10
PASSED: exactly 10/10 split, no seat sold twice.
```

## 7. What Problem This Phase Solved, and How

The problem: Phase 1 could sell the same seat to two different people if their requests happened to arrive close enough together, because checking whether a seat was free and marking it sold were two separate actions with a gap between them, in a database that couldn't guarantee both requests wouldn't fall through that gap at once.

The solution: seat availability was moved into Redis, tracked as a set of currently-available seat names per event. Instead of checking and claiming a seat as two separate steps, both actions were combined into a single Lua script that Redis runs as one uninterruptible operation. Because Redis only ever runs one thing at a time and a script can never be interrupted partway through, there is no longer any gap for a second, competing request to slip through — whichever request's script reaches Redis first fully resolves that seat's fate before any other request is even considered. Postgres was not removed from the picture; it still holds the permanent, official record of every sale — but it no longer decides who gets a seat. That decision now belongs entirely to Redis's atomic check-and-lock step, with Postgres simply recording the outcome afterward. The result, proven under simulated concurrent load rather than just assumed, is that no seat can be sold to more than one person, no matter how many people try for it at the exact same moment.
