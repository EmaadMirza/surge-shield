# Surge Shield — Phase 1 Report

**Project:** Anti-Scalper Ticket Gateway (Surge Shield)
**Phase:** 1 — Foundation
**Stack:** FastAPI, PostgreSQL, SQLAlchemy (sync), Pydantic, uv, Windows/PowerShell
**Status:** Complete

---

## 1. What Phase 1 Set Out to Do

Build the foundation layer only — no Redis, no Celery, no rate limiting, no seat locking. A working but intentionally naive event + seat booking flow, with the classic double-booking race condition left unfixed on purpose, to be solved in Phase 2.

## 2. What Was Actually Built

Phase 1 went beyond the original spec's hardcoded single-event approach and instead implemented:

- **`POST /event`** — creates an event dynamically (name, sale start time, row count, seats per row) and auto-generates the full seat grid for it.
- **`POST /buy`** — books specific named seats (e.g. `"A1"`, `"G9"`) for a `user_id`, capped at 5 seats per request. Rejects duplicate seat numbers in one request. Returns a `409` if any requested seat is unavailable.
- **`GET /event/{event_id}`** — returns count of currently available seats.
- **`GET /seats/{event_id}`** — returns full seat list with status and buyer for a given event.

## 3. Data Model

- **`Event`**: `id`, `name`, `sale_start_time`, `rows`, `seats_per_row`
- **`Seat`**: `id`, `event_id` (FK → Event), `seat_number` (e.g. `A1`, `B3`), `status` (`available`/`sold`), `buyer_id`

Seat naming: row letters `A`–`Z` (capped at 26 rows) × seat numbers `1..seats_per_row`, generated via `chr(65 + row_index)`.

## 4. Project Structure

```
surge-shield/
├── .env
├── pyproject.toml
├── app/
│   ├── main.py        # FastAPI app + all routes
│   ├── database.py     # engine, SessionLocal, Base
│   ├── models.py        # Event, Seat SQLAlchemy models
│   ├── schemas.py       # Pydantic request/response schemas
│   └── seed.py          # creates tables (Base.metadata.create_all)
```

## 5. Known, Intentional Limitation

`POST /buy` has a race condition between reading seat availability and committing the sold status — two near-simultaneous requests for the same seat can both pass the availability check before either commits. **This is left unfixed on purpose.** Phase 2 solves it via Redis-based atomic locking.

Also not yet handled (deliberately out of scope for Phase 1): no auth/login, no payment, no duplicate-event prevention, no per-user cross-request seat cap (5-seat cap is per single request only).

---

## 6. Errors Encountered & Fixes

- **`psql`/`createdb` not recognized in PowerShell** — PostgreSQL installer didn't add its `bin` folder to Windows PATH. Fixed by manually adding `C:\Program Files\PostgreSQL\<version>\bin` to the system PATH.
- **`createdb` password authentication failed** — simple typing mistake entering the postgres password. Fixed by retyping carefully.
- **`could not translate host name "123@localhost"`** — postgres password (`Mirza@123`) contained an `@`, which broke `DATABASE_URL` parsing since `@` is a reserved separator character in connection URLs. Fixed by URL-encoding it as `%40` in `.env` (`Mirza%40123`).
- **`DetachedInstanceError` on `POST /event` response** — SQLAlchemy expires objects after `commit()` by default; the second `commit()` (for seats) expired the `Event` object, and by the time FastAPI tried to read it for the response, the session was already closed. Fixed by adding `expire_on_commit=False` to `sessionmaker(...)` in `database.py`.
- **Seat numbers showing as `@1` with status `available3`** — typo when hand-typing the seat generation loop (off-by-one in `chr()`, extra character in `"available"`). Fixed by correcting the code, then resetting the database (`dropdb` + `createdb` + reseed) since already-created rows don't retroactively update when code changes.

---

## 7. Ready for Phase 2

Phase 1 core loop is confirmed working end-to-end: create event → generate seat grid → book specific seats → see status update. Next phase introduces Redis to close the race condition via atomic seat locking.
