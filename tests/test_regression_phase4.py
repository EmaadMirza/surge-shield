import asyncio
import httpx

BASE_URL = "http://127.0.0.1:8000"

async def create_test_event():
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{BASE_URL}/events", json={
            "name": "Phase 4 Regression Test",
            "sale_start_time": "2026-08-12T00:00:00",
            "rows": 2,
            "seats_per_row": 2
        })
        return response.json()["id"]

async def buy_seat(client, event_id, seat_number, user_id):
    response = await client.post(f"{BASE_URL}/buy", json={
        "event_id": event_id,
        "seat_numbers": [seat_number],
        "user_id": user_id
    })
    return user_id, seat_number, response.status_code

async def main():
    event_id = await create_test_event()
    print(f"Created test event {event_id}")

    async with httpx.AsyncClient() as client:
        tasks = [
            buy_seat(client, event_id, "A1", "userA1"),
            buy_seat(client, event_id, "A1", "userA2"),
            buy_seat(client, event_id, "B1", "userB1"),
            buy_seat(client, event_id, "B1", "userB2"),
        ]
        results = await asyncio.gather(*tasks)

    for user_id, seat_number, status in results:
        print(f"{user_id} -> {seat_number}: {status}")

    successes = [r for r in results if r[2] == 200]
    failures = [r for r in results if r[2] == 409]

    assert len(successes) == 2, f"Expected 2 successes, got {len(successes)}"
    assert len(failures) == 2, f"Expected 2 failures, got {len(failures)}"

    seats_won = [r[1] for r in successes]
    assert len(seats_won) == len(set(seats_won)), "DOUBLE BOOKING DETECTED!"

    print("PASSED: exactly 2/2 split, no seat sold twice.")

if __name__ == "__main__":
    asyncio.run(main())