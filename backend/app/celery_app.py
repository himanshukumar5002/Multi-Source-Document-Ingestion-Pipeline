"""Celery instance + config. Redis is used as both broker and result backend."""
from celery import Celery

from app import config

celery_app = Celery(
    "pdf_rag",
    broker=config.CELERY_BROKER_URL,
    backend=config.CELERY_RESULT_BACKEND,
    include=["app.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    # Keep task results around long enough to be useful for debugging,
    # without growing Redis unbounded.
    result_expires=3600,
)
