import os
from dotenv import load_dotenv
import redis

load_dotenv()

REDIS_URL = os.getenv("REDIS_URL")

redis_client = redis.from_url(REDIS_URL, decode_responses=True)

#LUA script to atomically check and lock seats in Redis
# KEYS[1] = available_seats:{event_id} "key"
# ARGV    = requested seat numbers, e.g. {"A1", "G9"} "values"

LOCK_SEATS_SCRIPT = """
local statuses ={}
local all_available = true

for i,seat in ipairs(ARGV) do
    if redis.call("SISMEMBER", KEYS[1], seat) == 1 then 
        statuses[i] = 1
    else
        statuses[i] = 0
        all_available = false
    end
end

if not all_available then
    return statuses
else
    for i,seat in ipairs(ARGV) do
        redis.call("SREM", KEYS[1], seat)
    end
    return statuses
end
"""

#lua script to implement rate limiting and block bots
RATE_LIMIT_SCRIPT = """
local current = redis.call("INCR", KEYS[1])

if current == 1 then 
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end

if current > tonumber(ARGV[2]) then
    return 0
else
    return 1
end
"""

rate_limit = redis_client.register_script(RATE_LIMIT_SCRIPT)
lock_seats = redis_client.register_script(LOCK_SEATS_SCRIPT)