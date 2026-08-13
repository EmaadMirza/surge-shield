from app.database import SessionLocal
from app.models import Event, Seat

db = SessionLocal()
event = db.query(Event).filter(Event.id == 20).first()
if event:
    print(f"Event 20: {event.name}, rows={event.rows}, seats_per_row={event.seats_per_row}")
    seats = db.query(Seat).filter(Seat.event_id == 20).limit(5).all()
    print(f"Sample seats in DB: {[s.seat_number for s in seats]}")
    count = db.query(Seat).filter(Seat.event_id == 20, Seat.status == 'available').count()
    print(f"Available seats in DB: {count}")
else:
    print("Event 20 not found in DB")
db.close()
