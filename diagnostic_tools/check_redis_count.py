import redis

r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
members = r.smembers("available_seats:20")
print("Total members left in Redis:", len(members))
