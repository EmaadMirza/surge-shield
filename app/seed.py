from app.database import engine, Base
from app.models import Event, Seat

def seed():
    Base.metadata.create_all(bind=engine)
    print("Tables created (or already exist). Use POST /event to create an event.")

if __name__ == "__main__":
    seed()