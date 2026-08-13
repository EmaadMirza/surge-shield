import asyncio
import httpx

BASE_URL = "http://localhost:8000"

async def main():
    event_id = input("Enter event ID: ")
    seat_number = input("Enter seat number (e.g. B4): ")

    async with httpx.AsyncClient() as client:
        response = await client.post(BASE_URL + "/buy", json={
            "event_id": int(event_id),
            "user_id": "test_single_buyer",
            "seat_numbers": [seat_number]
        })

        print(f"\nStatus: {response.status_code}")
        print(f"Response: {response.json()}")

        if response.status_code == 200:
            print(f"\n✅ Successfully booked seat {seat_number}!")
        elif response.status_code == 409:
            print(f"\n❌ Seat {seat_number} is already taken or unavailable.")
        elif response.status_code == 429:
            print(f"\n🚫 Blocked by rate limiter or in penalty box. try after 15 mins")

asyncio.run(main())