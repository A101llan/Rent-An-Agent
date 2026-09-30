import os

from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("agenthub", broker=redis_url, backend=redis_url)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    beat_schedule={
        "expire-sessions": {
            "task": "app.tasks.expire_sessions",
            "schedule": 60.0,
        },
    },
)

celery_app.autodiscover_tasks(["app"])
