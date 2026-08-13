# Surge Shield — Phase 3 Report

**Project:** Anti-Scalper Ticket Gateway (Surge Shield)
**Phase:** 3 — Traffic Control (Rate Limiting + Penalty Box)
**Stack:** FastAPI, PostgreSQL, SQLAlchemy (sync), Pydantic, Redis (Cloud), redis-py, Lua, uv, Windows/PowerShell
**Status:** Complete

---

## 1. What Phase 3 Set Out to Do

Solve objective 3: block bots and scalpers. Sit a traffic-control layer in front of the seat-locking logic built in Phase 2, so abusive traffic gets rejected before it ever touches Redis's seat set or Postgres. Nothing about seat locking itself was to change in this phase — and nothing did.

## 2. What Was Actually Built

- **A second Lua script (`rate_limit_lua`)** — registered in `redis_client.py` alongside the existing seat-lock script from Phase 2. It atomically increments a per-IP request counter, sets the counter's expiry only on the first request of a fresh window, and reports back whether the client is now over the allowed threshold.
- **A penalty box** — a Redis key (`penalty_box:{ip}`) written with a time-to-live whenever a client crosses the threshold. Redis deletes it automatically once the TTL runs out.
- **A gatekeeper dependency (`check_rate_limit`)** — a FastAPI dependency wired only onto `POST /buy` via `dependencies=[Depends(check_rate_limit)]`. It checks the penalty box first, and only runs the rate-limit script if the client isn't already flagged.
- **Config values in `.env`** instead of hardcoded numbers:
  ```
  RATE_LIMIT_MAX_REQUESTS=10
  RATE_LIMIT_WINDOW_SECONDS=10
  PENALTY_BOX_TTL_SECONDS=900
  ```
  10 requests per 10-second window before flagging, 15-minute penalty box duration.

## 3. The Rate-Limit Lua Script

Registered once at startup in `redis_client.py`, alongside the existing seat-lock script from Phase 2:

```lua
local current = redis.call("INCR", KEYS[1])

if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[2])
end

if current > tonumber(ARGV[1]) then
    return 0
else
    return 1
end
```

`KEYS[1]` is the requesting client's counter key, `rate_limit:{ip}`, passed in from Python's `keys=[...]` argument. `ARGV[1]` and `ARGV[2]` are the configured max requests and window size in seconds, passed in via `args=[...]`.

`INCR` bumps the counter and returns the new value in one step — if the key didn't exist yet, Redis creates it and increments to `1`. The `if current == 1` check sets the expiry only on the very first request of a fresh window; without that guard, every subsequent request would push the expiry further out and the window would never actually reset. The final check compares the new count against the configured max (converted with `tonumber()`, since everything arriving through `ARGV` is text) and returns `0` for "over limit" or `1` for "within limit."

Wrapping all three of these actions — increment, conditional expiry, threshold check — inside one Lua script is what makes them atomic. Redis runs the whole script as a single uninterruptible unit, so two near-simultaneous requests from the same client can't both read the count as "still fine" and both slip through before either one updates it.

## 4. Design Decisions

- **Scope: `/buy` only, not global middleware.** The only route doing expensive, exploitable work (seat locking, Postgres writes) is `/buy`. Applying this globally would've added complexity with no real benefit at this stage, since no other route is a meaningful target yet.
- **Fixed window counter, not sliding window log.** A fixed window has a known edge case — a client could burst right at the boundary between two windows and briefly exceed the "true" intended rate. A sliding window (storing individual timestamps) avoids that, but adds real complexity for a benefit that doesn't matter at this project's scale. Fixed window was the deliberate, correct-for-this-project choice.
- **Plain `429`, not a fake `200` success.** The spec allows for optionally returning a fake success to waste a bot's time without revealing it was caught. This was considered and explicitly turned down — a fake success requires maintaining a believable, consistent lie (fake seat data, consistency across other endpoints like `GET /seats`), which adds real ongoing complexity for very little benefit at this scale, and it also makes debugging your own system harder, since `200` would no longer reliably mean "this actually worked." A plain `429` keeps the system honest and simple, matching the spec's own note that this is perfectly sufficient.
- **Penalty box checked before the rate limiter, every time.** This ordering is the actual point of the phase, not an incidental detail. A penalty-box check is a single cheap `EXISTS` call. Once a client is known to be bad, there's no reason to keep spending effort re-running the rate-limit script against them on every subsequent request — the cheap check filters them out first, protecting the more expensive logic behind it.

## 5. Errors Encountered & Fixes

- **Forgot `load_dotenv()`** — the gatekeeper function's config lines (`os.getenv("RATE_LIMIT_MAX_REQUESTS")`, etc.) would have returned `None` if `.env` was never actually loaded into the environment, crashing immediately on `int(None)`. Caught before it caused a runtime failure, by confirming `from dotenv import load_dotenv` and `load_dotenv()` were already present at the top of `main.py` from Phase 1.

## 6. Testing & Proof

Two separate tests were run.

**Sequential rate-limit test (`test_rate_limit.py`):** fired 12 requests in a row, one after another, all targeting the same seat from the same local IP. Result:

```
Requests 0–9:  409 (rate limiter passed all 10 through to seat-locking logic;
               409s themselves were due to seat A1 already being sold from
               earlier test runs, not a rate-limiting failure)
Requests 10–11: 429 (crossed the 10-request threshold, correctly blocked)
Retry after block: 429 (confirms the block persists on the very next request,
               not just the one that crossed the line)
```

This proved: the counter correctly allows traffic under the threshold through, correctly blocks traffic over it, and — critically — that a client stays blocked immediately afterward via the penalty box, rather than being re-evaluated fresh on every request.

**Single-seat interactive test (`test_single_buy.py`):** an interactive script prompting for an event ID and seat number, used to confirm the rate limiter doesn't interfere with a legitimate, isolated buy. Tried once against an already-sold seat (correctly returned "seat unavailable"), then again against a genuinely free seat (event 4, seat B4), which returned a full success with the seat confirmed booked — proving the entire path (penalty box check → rate limiter → Redis seat lock → Postgres write) still works end-to-end exactly as it did before this phase's changes, once a client isn't flagged.

**TTL expiry, confirmed for real:** rather than only simulating the 15-minute penalty box expiry by manually deleting the key, the full 15 minutes was actually waited out once. After the wait, a new request from the same IP was let through normally, confirming Redis's automatic key expiry behaves as expected with no manual cleanup required.

## 7. What Problem This Phase Solved, and How

The problem: up through Phase 2, `/buy` had no concept of "too many requests." A real human can only click "buy" so many times in a few seconds, but a bot or script has no such limit — it could hit the endpoint hundreds of times per second, and every single one of those attempts would cost real work: a Redis lookup, potentially a Postgres write, all real infrastructure being spent on traffic that was never a legitimate attempt to begin with. Seat locking from Phase 2 would still correctly prevent double-booking even under that kind of abuse, but it would do so while absorbing an enormous, unnecessary amount of load — which works against a different one of the project's core goals: not crashing under pressure.

The solution was to add a filter in front of the seat-booking logic, not inside it. Every request to `/buy` now passes through two checks before it's allowed to reach Redis's seat lock or Postgres at all. First, a cheap check: is this client already known to be abusive? If they've already crossed the limit recently, they're rejected instantly, with almost no cost paid to figure that out. Second, for clients not already flagged: how many requests have they made recently? If a client crosses ten requests within a ten-second window, they're flagged and locked out for fifteen minutes going forward, and this specific request is rejected too. If they're under that threshold, nothing changes for them at all — they pass through to the exact same booking logic that existed before this phase.

The reason both of these checks needed to happen as a single atomic step inside Redis, rather than as ordinary back-and-forth Python logic, is the same underlying reason Phase 2 needed a Lua script for seat locking: checking a value and then acting on it are two separate moments in time, and if two requests from the same abusive client arrive close enough together, they could both check the count, both see it as "still fine," and both slip through before either one updates it. Bundling the check, the update, and the decision into one Lua script closes that gap entirely — Redis runs the whole thing as one uninterruptible unit, so there's no moment in between for a second request to sneak through unnoticed.

The result, proven through actual sequential testing rather than just assumed: legitimate traffic under the limit is completely unaffected, traffic that crosses the limit is rejected immediately, and once a client is flagged, every subsequent request from them is rejected instantly and cheaply for the full fifteen-minute window — without ever touching the more expensive seat-locking or database logic underneath. Bots and scalpers hammering the endpoint no longer cost the system anything close to what a legitimate request costs; they get filtered out at the door.

## 8. Ready for Phase 4

Phase 3's traffic-control layer is confirmed working end-to-end and sits cleanly in front of Phase 2's untouched seat-locking logic. Next phase introduces Celery for write-behind persistence: once a seat lock succeeds, FastAPI will respond immediately instead of waiting on the synchronous Postgres write, with a background worker handling that write afterward.
