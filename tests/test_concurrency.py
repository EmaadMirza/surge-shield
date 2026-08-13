import asyncio
import httpx

BASE_URL = "http://127.0.0.1:8000"

async def create_test_event(client):
    resp = await client.post("/events", json={
        "name": "Concurrency Test Event",
        "sale_start_time": "2026-08-10T17:30:00Z",
        "rows": 2,
        "seats_per_row": 5
    })
    return resp.json()["id"]

async def attempt_buy(client, event_id, seat, user_id):
    resp = await client.post("/buy", json={
        "event_id": event_id,
        "user_id": user_id,
        "seat_numbers": [seat]
    })
    return user_id, seat, resp.status_code

async def main():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        event_id = await create_test_event(client)
        print(f"Created test event {event_id}")

        seats = [f"{chr(65+r)}{n}" for r in range(2) for n in range(1, 6)]

        tasks = []
        for i, seat in enumerate(seats):
            tasks.append(attempt_buy(client, event_id, seat, f"user_{i}_a"))
            tasks.append(attempt_buy(client, event_id, seat, f"user_{i}_b"))

        results = await asyncio.gather(*tasks)

        successes = [r for r in results if r[2] == 200]
        failures = [r for r in results if r[2] == 409]

        print(f"Successes: {len(successes)}  Failures: {len(failures)}")
        assert len(successes) == 10, f"Expected 10 successes, got {len(successes)}"
        assert len(failures) == 10, f"Expected 10 failures, got {len(failures)}"

        seats_won = [r[1] for r in successes]
        assert len(seats_won) == len(set(seats_won)), "DOUBLE BOOKING DETECTED!"

        print("PASSED: exactly 10/10 split, no seat sold twice.")

if __name__ == "__main__":
    asyncio.run(main())


#verdict: What this proves, bottom line: even when 20 requests hit your server at the exact same moment,
#  all competing over the same 10 seats, your system handed out exactly the right number of seats,
#  to exactly the right number of people, with zero duplicates. That's the race condition — the one Phase 1 
# deliberately left broken — now demonstrably closed. This is the actual, hard proof that Redis's atomic locking
#  is doing its job, not just a "looks fine" from clicking around manually.

#result: Created test event 5
# Successes: 10  Failures: 10
# PASSED: exactly 10/10 split, no seat sold twice.