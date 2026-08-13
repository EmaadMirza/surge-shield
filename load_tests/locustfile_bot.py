import random
from locust import HttpUser, task, between

class ScalperBot(HttpUser):
    # A real human waits 1-5 seconds between clicks.
    # This bot waits 0 seconds (as fast as possible).
    wait_time = between(0.0, 0.0)

    @task
    def spam_buy(self):
        # The bot blindly hammers the most valuable front-row seats
        row = random.choice(["A", "B"])
        seat_num = random.randint(1, 10)
        seat_number = f"{row}{seat_num}"

        self.client.post(
            "/buy",
            json={
                "event_id": 21,
                "seat_numbers": [seat_number],
                "user_id": "scalper_bot_account"
            },
            # Notice we are NOT sending the X-Test-Client-ID header here.
            # This forces the FastAPI server to read the raw IP (127.0.0.1) 
            # for all bot requests, instantly triggering the rate limiter.
            name="/buy (Bot Attack)"
        )
