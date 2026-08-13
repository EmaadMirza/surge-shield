import redis

r = redis.from_url("redis://localhost:6379/0", decode_responses=True)

penalties = r.keys("penalty_box:*")
print(f"Total IPs in penalty box: {len(penalties)}")

if penalties:
    print(f"Sample banned IPs: {penalties[:5]}")

rate_limits = r.keys("rate_limit:*")
print(f"Total IPs tracking rate limit: {len(rate_limits)}")
