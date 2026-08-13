import os
from dotenv import load_dotenv
from celery import Celery

load_dotenv()

celery_app = Celery(
    "surge_shield",
    broker=os.getenv("CELERY_BROKER_URL"),
    include=["app.tasks"]
)

