from celery import Celery
import os

celery_app = Celery(
    "project",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/1",
    include=["tasks.process_media_task"]
)

celery_app.autodiscover_tasks(packages=["tasks"])

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    timezone="Europe/Moscow",
)