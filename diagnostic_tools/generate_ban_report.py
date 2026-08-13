import redis

def generate_penalty_report():
    r = redis.from_url("redis://localhost:6379/0", decode_responses=True)
    
    penalties = r.keys("penalty_box:*")
    
    with open("banned_ips.txt", "w") as f:
        f.write(f"Total IPs in Penalty Box: {len(penalties)}\n")
        f.write("="*30 + "\n")
        for key in penalties:
            # key looks like 'penalty_box:127.0.0.1'
            ip = key.split(":")[1]
            f.write(f"- {ip}\n")
            
    print(f"Report generated! Found {len(penalties)} banned IPs.")
    print("Check the 'banned_ips.txt' file in your root folder.")

if __name__ == "__main__":
    generate_penalty_report()
