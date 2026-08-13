import redis

r = redis.from_url("redis://localhost:6379/0", decode_responses=True)

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
res = lock_seats(keys=["available_seats:20"], args=["A3"])
print("Lua lock A3:", res)

# and now check if A3 is still in there
print("SISMEMBER A3 after lock:", r.sismember("available_seats:20", "A3"))
