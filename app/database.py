import os 
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine =create_engine(DATABASE_URL)

# Create a session factory , and also to avoid it getting commited twice making the database fallback gives an 500 internal server error
SessionLocal =  sessionmaker(autocommit=False, autoflush=False,expire_on_commit=False, bind=engine)

Base=declarative_base()
