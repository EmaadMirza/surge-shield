import redis
r = redis.from_url("redis://localhost:6379/0")  # match your REDIS_URL

for key in r.keys("penalty_box:*"):
    r.delete(key)
    print(f"Cleared {key}")

for key in r.keys("rate_limit:*"):
    r.delete(key)
    print(f"Cleared {key}")