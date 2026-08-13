import redis

r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
print("SISMEMBER A2:", r.sismember("available_seats:20", "A2"))
print("SISMEMBER A1:", r.sismember("available_seats:20", "A1"))

# Also test the Lua script directly!
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

lock_seats = r.register_script(LOCK_SEATS_SCRIPT)
res = lock_seats(keys=["available_seats:20"], args=["A2"])
print("Lua script lock A2:", res)
