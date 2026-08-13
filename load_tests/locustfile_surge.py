import random
import uuid
from locust import HttpUser, task, between

class SurgeBuyer(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self):
        self.client_id = str(uuid.uuid4())
        self.user_id = f"loadtest_{self.client_id[:8]}"

    @task
    def buy_seat(self):
        if random.random() < 0.2:
            row = random.choice(["A", "B", "C"])
            seat_num = random.randint(1, 5)
        else:
            row = chr(65 + random.randint(0, 24))
            seat_num = random.randint(1, 40)

        seat_number = f"{row}{seat_num}"

        self.client.post(
            "/buy",
            json={
                "event_id": 21,
                "seat_numbers": [seat_number],
                "user_id": self.user_id
            },
            headers={"X-Test-Client-ID": self.client_id},
            name="/buy"
        )