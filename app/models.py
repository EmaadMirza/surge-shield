from sqlalchemy import Column, Integer, String, DateTime, ForeignKey
from app.database import Base

class Event(Base):
    __tablename__ = "events"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sale_start_time = Column(DateTime, nullable=False)
    rows = Column(Integer, nullable=False)
    seats_per_row = Column(Integer, nullable=False)


class Seat(Base):
    __tablename__ = "seats"

    id = Column(Integer, primary_key=True)
    event_id = Column(Integer, ForeignKey("events.id"), nullable=False)
    seat_number = Column(String, nullable=False)
    status = Column(String, nullable=False, default="available")
    buyer_id = Column(String, nullable=True)