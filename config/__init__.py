# config/__init__.py
try:
    from .celery import app as celery_app  # noqa: F401
except ModuleNotFoundError:
    celery_app = None
