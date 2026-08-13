import asyncio
import httpx

BASE_URL = "http://localhost:8000"

async def fire_request(client, i):
    response = await client.post(BASE_URL + "/buy", json={
        "event_id": 4,
        "user_id": f"test_user_{i}",
        "seat_numbers": ["A4"]
    })
    return i, response.status_code

async def main():
    async with httpx.AsyncClient() as client:
        results = []
        for i in range(12):
            result = await fire_request(client, i)
            results.append(result)

        for i, status in results:
            print(f"Request {i}: {status}")

        _, retry_status = await fire_request(client, 99)
        print(f"Retry after block: {retry_status}")

asyncio.run(main())