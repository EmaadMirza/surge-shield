import os 
from fastapi import FastAPI, HTTPException , Request , Depends
from app.database import SessionLocal, engine, Base
from app.models import Event, Seat
from app.schemas import EventCreate, EventResponse, BuyRequest, BuyResponse
from app.redis_client import redis_client, lock_seats, rate_limit
from dotenv import load_dotenv
from app.tasks import save_purchase_task

load_dotenv()
app=FastAPI()
Base.metadata.create_all(bind=engine)

RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX_REQUESTS"))
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS"))
PENALTY_TTL = int(os.getenv("PENALTY_BOX_TTL_SECONDS"))


# the actual rate limitng block , to prevent too many requests

def check_rate_limit(request: Request):
    ip = request.headers.get("X-Test-Client-ID") or request.client.host

    penalty_key = f"penalty_box:{ip}"
    if redis_client.exists(penalty_key):
        raise HTTPException(status_code=429, detail="You are temporarily blocked due to excessive requests." \
        " Please try again later.")

    rate_key = f"rate_limit:{ip}"
    result = rate_limit(
        keys=[rate_key],
        args=[RATE_LIMIT_WINDOW, RATE_LIMIT_MAX]
    )

    if result ==0:
        redis_client.set(penalty_key, "1", ex=PENALTY_TTL)
        raise HTTPException(status_code=429, detail="Too many requests. You are temporarily blocked for 15 minutes.")

    
@app.post("/events", response_model=EventResponse)
def create_event(event:EventCreate):
    db=SessionLocal()
    try:
        # Create a new event
        new_event=Event(
            name=event.name,
            sale_start_time=event.sale_start_time,
            rows=event.rows,
            seats_per_row=event.seats_per_row
        )
        db.add(new_event)
        db.commit()
        db.refresh(new_event)
        # Create seats for the event

        seats = []
        seat_numbers = []
        for row_index in range(new_event.rows):
            row_letter = chr(65 + row_index)
            for seat_num in range(1, new_event.seats_per_row + 1):
                seat_number = f"{row_letter}{seat_num}"
                seats.append(Seat(
                    event_id=new_event.id,
                    seat_number=seat_number,
                    status="available"
                ))
                seat_numbers.append(seat_number)
        db.add_all(seats)
        db.commit()


        # Store available seats in Redis
        redis_client.sadd(f"available_seats:{new_event.id}", *seat_numbers)
        return new_event
    finally:
        db.close()

@app.post("/buy", response_model=BuyResponse, dependencies=[Depends(check_rate_limit)])
def buy_seats(order: BuyRequest):
    requested = set(order.seat_numbers)
    if len(requested) != len(order.seat_numbers):
        raise HTTPException(status_code=400, detail="Duplicate seat numbers in request.")

    seat_numbers = list(order.seat_numbers)

    result = lock_seats(
        keys=[f"available_seats:{order.event_id}"],
        args=seat_numbers
    )
    seat_status = dict(zip(seat_numbers, result))

    if any(status == 0 for status in seat_status.values()):
        raise HTTPException(
            status_code=409,
            detail={"message": "One or more seats unavailable", "seats": seat_status}
        )

        # try:
        #     seats = (
        #         db.query(Seat)
        #         .filter(Seat.event_id == order.event_id, Seat.seat_number.in_(seat_numbers))
        #         .all()
        #     )
        #     for seat in seats:
        #         seat.status = "sold"
        #         seat.buyer_id = order.user_id
        #     db.commit()
        # except Exception:
        #     db.rollback()
        #     redis_client.sadd(f"available_seats:{order.event_id}", *seat_numbers)
        #     raise HTTPException(status_code=500, detail="Failed to save purchase, please try again.")

    save_purchase_task.delay(order.event_id, seat_numbers, order.user_id)

    return BuyResponse(message="Seats successfully purchased.", seat_numbers=seat_numbers)

    # finally:
    #     db.close()

@app.get("/event/{event_id}")
def get_event_availability(event_id: int):
    db=SessionLocal()
    try:
        available_seats = ( db.query(Seat).filter(Seat.event_id == event_id,
                                                   Seat.status == "available").count()
        )
        return {"event_id": event_id, "available_seats": available_seats}           

    finally:
        db.close()

@app.get("/seats/{event_id}")
def list_seats(event_id: int):
    
    db = SessionLocal()
    try:
        seats = db.query(Seat).filter(Seat.event_id == event_id).all()
        return [
            {"id": s.id, "seat_number": s.seat_number, "status": s.status, "buyer_id": s.buyer_id}
            for s in seats
        ]
    finally:
        db.close()