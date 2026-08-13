import redis

r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
members = r.smembers("available_seats:20")
print("Total members:", len(members))

# Let's count how many start with A
a_seats = [m for m in members if m.startswith('A')]
print("Seats starting with A:", len(a_seats), a_seats)

b_seats = [m for m in members if m.startswith('B')]
print("Seats starting with B:", len(b_seats), b_seats)
