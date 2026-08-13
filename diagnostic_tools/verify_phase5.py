import sys
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def verify_test(event_id):
    db = SessionLocal()
    try:
        result = db.execute(text(f"SELECT COUNT(*) FROM seats WHERE event_id = {event_id} AND status = 'sold'")).scalar()
        print(f"Total seats marked as 'sold' in PostgreSQL: {result}")
        
        duplicate_check = db.execute(text(f"""
            SELECT seat_number, COUNT(*) 
            FROM seats 
            WHERE event_id = {event_id} AND status = 'sold'
            GROUP BY seat_number 
            HAVING COUNT(*) > 1
        """)).fetchall()
        
        if len(duplicate_check) == 0:
            print("Double Booking Check: PASSED \u2705 (Zero seats were sold twice)")
        else:
            print(f"Double Booking Check: FAILED \u274c (Found {len(duplicate_check)} double-booked seats!)")
            
    finally:
        db.close()

if __name__ == "__main__":
    verify_test(21)
