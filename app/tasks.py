import logging
from app.celery_worker import celery_app
from app.database import SessionLocal
from app.models import Seat
from app.redis_client import redis_client

logger = logging.getLogger(__name__)

@celery_app.task(name="save_purchase_task")
def save_purchase_task(event_id: int, seat_numbers: list[str], buyer_id: int):
    db = SessionLocal()
    try:
        seats = (
            db.query(Seat)
            .filter(Seat.event_id == event_id, Seat.seat_number.in_(seat_numbers))
            .all()
        )
        for seat in seats:
            seat.status = "sold"
            seat.buyer_id = buyer_id
    
        db.commit()

        logger.info(f"Purchase saved: event {event_id}, seats {seat_numbers}, buyer {buyer_id}")
# this block is when there is a postgress side fallback happens so that the redis allotted seat wont go to ruin and the users money be 
# taken yet no seat be given , so for that this is the line it allocates the seat back to redis and throws the error .
    except Exception as e:
        db.rollback()
        redis_client.sadd(f"available_seats:{event_id}", *seat_numbers)
        logger.error(f"Failed to save purchase for event {event_id}, seats {seat_numbers}: {e}")

    finally:
        db.close()