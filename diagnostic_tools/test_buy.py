import asyncio
import httpx
import uuid

async def test_buy():
    client_id = str(uuid.uuid4())
    async with httpx.AsyncClient() as client:
        # Request a seat we know exists, e.g. A2
        response = await client.post(
            "http://127.0.0.1:8000/buy",
            json={
                "event_id": 20,
                "seat_numbers": ["A2"],
                "user_id": "test_script"
            },
            headers={"X-Test-Client-ID": client_id}
        )
        print(f"Status: {response.status_code}")
        print(f"Body: {response.text}")

        # Request a random seat
        response = await client.post(
            "http://127.0.0.1:8000/buy",
            json={
                "event_id": 20,
                "seat_numbers": ["Z99"],
                "user_id": "test_script"
            },
            headers={"X-Test-Client-ID": client_id}
        )
        print(f"Status Z99: {response.status_code}")
        print(f"Body Z99: {response.text}")

asyncio.run(test_buy())
