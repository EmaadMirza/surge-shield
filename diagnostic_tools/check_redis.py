import redis
import sys

def check_event(event_id):
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    key = f"available_seats:{event_id}"
    
    count = r.scard(key)
    print(f"[{key}] -> {count} seats in Redis set")
    
    if count > 0:
        members = list(r.smembers(key))
        if count <= 20:
            print(f"  Members: {sorted(members)}")
        else:
            print(f"  Sample: {sorted(members[:10])} ...")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        check_event(sys.argv[1])
    else:
        print("Usage: uv run python check_redis.py <event_id>")
        print("Example: uv run python check_redis.py 21")
