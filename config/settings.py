
# =========================
# FILE: config/settings.py
# =========================
import os
from urllib.parse import urlparse

import dj_database_url
from celery.schedules import crontab

from config.env import BASE_DIR, load_project_env


def _split_env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [value.strip() for value in raw.split(",") if value.strip()]


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}

USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

RESULTS_CACHE_TTL_SECONDS = 0  # 0 para desactivar cache totalmente

load_project_env()

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insecure-key")
DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = _split_env_list("DJANGO_ALLOWED_HOSTS") if not DEBUG else ["*"]

TIME_ZONE = os.getenv("DJANGO_TIME_ZONE", "America/Caracas")
USE_TZ = True

DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@ssganador.lat")
SCRAPER_ALERT_EMAILS = [
    value.strip()
    for value in os.getenv("SCRAPER_ALERT_EMAILS", "").split(",")
    if value.strip()
]
SCRAPER_ALERT_USERNAMES = [
    value.strip()
    for value in os.getenv("SCRAPER_ALERT_USERNAMES", "").split(",")
    if value.strip()
]
SCRAPER_ALERT_GROUPS = [
    value.strip()
    for value in os.getenv("SCRAPER_ALERT_GROUPS", "").split(",")
    if value.strip()
]
SCRAPER_ALERT_NOTIFY_COOLDOWN_MINUTES = int(
    os.getenv("SCRAPER_ALERT_NOTIFY_COOLDOWN_MINUTES", "180")
)
SCRAPER_ALERT_PRIMARY_CHANNEL = (os.getenv("SCRAPER_ALERT_PRIMARY_CHANNEL", "telegram").strip().lower() or "telegram")
SCRAPER_TELEGRAM_BOT_TOKEN = os.getenv("SCRAPER_TELEGRAM_BOT_TOKEN", "").strip()
SCRAPER_TELEGRAM_CHAT_IDS = [
    value.strip()
    for value in os.getenv("SCRAPER_TELEGRAM_CHAT_IDS", "").split(",")
    if value.strip()
]
SCRAPER_TELEGRAM_API_BASE_URL = (
    os.getenv("SCRAPER_TELEGRAM_API_BASE_URL", "https://api.telegram.org").strip()
    or "https://api.telegram.org"
)
SCRAPER_TELEGRAM_NOTIFICATIONS_ENABLED = _env_bool(
    "SCRAPER_TELEGRAM_NOTIFICATIONS_ENABLED",
    "0",
)
SCRAPER_ADMIN_BASE_URL = os.getenv("SCRAPER_ADMIN_BASE_URL", "").rstrip("/")
SCRAPER_INCIDENT_VIEWER_GROUPS = [
    value.strip()
    for value in os.getenv("SCRAPER_INCIDENT_VIEWER_GROUPS", "Administradores").split(",")
    if value.strip()
]
SCRAPER_INCIDENT_RESOLVER_GROUPS = [
    value.strip()
    for value in os.getenv("SCRAPER_INCIDENT_RESOLVER_GROUPS", "Administradores").split(",")
    if value.strip()
]
SCRAPER_RESULT_AUTOMATIC_ORIGIN_LABEL = (
    os.getenv("SCRAPER_RESULT_AUTOMATIC_ORIGIN_LABEL", "automatic_valid").strip()
    or "automatic_valid"
)
SCRAPER_RESULT_MANUAL_ORIGIN_LABEL = (
    os.getenv("SCRAPER_RESULT_MANUAL_ORIGIN_LABEL", "manual_contingency").strip()
    or "manual_contingency"
)
SCRAPER_BOOTSTRAP_MAX_AGE_MINUTES = int(os.getenv("SCRAPER_BOOTSTRAP_MAX_AGE_MINUTES", "90"))
SCRAPER_EXECUTION_RETENTION_DAYS = int(os.getenv("SCRAPER_EXECUTION_RETENTION_DAYS", "14"))
ARCHIVE_KEEP_DAYS = int(os.getenv("ARCHIVE_KEEP_DAYS", "7"))
WEEKLY_DEVICE_RATE_USD = os.getenv("WEEKLY_DEVICE_RATE_USD", "3").strip() or "3"
ADMIN_ACTIVITY_TELEGRAM_ENABLED = os.getenv("ADMIN_ACTIVITY_TELEGRAM_ENABLED", "0") == "1"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"] if (BASE_DIR / "static").exists() else []
STATIC_ROOT = BASE_DIR / "staticfiles"

DEVICE_BYPASS_CODES = os.getenv("DEVICE_BYPASS_CODES", "")


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_extensions",
    "rest_framework",
    "channels",
    "corsheaders",
    "core.apps.CoreConfig",
    "django_prometheus",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_prometheus.middleware.PrometheusBeforeMiddleware",
    "django_prometheus.middleware.PrometheusAfterMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR/'db.sqlite3'}",
        conn_max_age=60,
    )
}
if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    DATABASES["default"].setdefault("OPTIONS", {})
    DATABASES["default"]["OPTIONS"]["timeout"] = 20

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
}

CORS_ALLOWED_ORIGINS = _split_env_list(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:3000,http://localhost:5173,http://localhost:8080,http://127.0.0.1:8080",
)
CORS_ALLOW_ALL_ORIGINS = not bool(CORS_ALLOWED_ORIGINS)

CSRF_TRUSTED_ORIGINS = _split_env_list(
    "CSRF_TRUSTED_ORIGINS",
    default="http://localhost:8000,http://127.0.0.1:8000,http://localhost:8080,http://127.0.0.1:8080",
)
CSRF_COOKIE_SECURE = _env_bool("CSRF_COOKIE_SECURE", "1" if not DEBUG else "0")
SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE", "1" if not DEBUG else "0")

ASGI_APPLICATION = "config.asgi.application"

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
redis = urlparse(REDIS_URL)

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {"hosts": [(redis.hostname, redis.port)]},
    }
}

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

CELERY_TIMEZONE = os.getenv("CELERY_TIMEZONE", TIME_ZONE)
CELERY_ENABLE_UTC = os.getenv("CELERY_ENABLE_UTC", "0") == "1"
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://127.0.0.1:6379/2")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://127.0.0.1:6379/3")

CELERY_BEAT_SCHEDULE = {
    "scrape_triples_every_3_minutes": {
        "task": "core.tasks.scrape_triples",
        "schedule": crontab(minute="*/3", hour="8-22"),
    },
    "scrape_tuazar_triples_every_3_minutes": {
        "task": "core.tasks.scrape_tuazar_triples",
        "schedule": crontab(minute="*/3", hour="8-22"),
    },
    "scrape_animalitos_every_3_minutes": {
        "task": "core.tasks.scrape_animalitos",
        "schedule": crontab(minute="*/3", hour="8-22"),
    },
    "scrape_condor_animalitos_every_minute": {
        "task": "core.tasks.scrape_condor_animalitos",
        "schedule": crontab(minute="*", hour="9-22"),
    },
    "scrape_triple_tachira_every_minute": {
        "task": "core.tasks.scrape_triple_tachira",
        "schedule": crontab(minute="*", hour="13-22"),
    },
    "archive_daily": {
        "task": "core.tasks.archive_daily",
        "schedule": crontab(minute=10, hour=0),
    },
    "notify_scraper_alerts": {
        "task": "core.tasks.notify_scraper_alerts",
        "schedule": crontab(minute="*/15"),
    },
    "scrape_cruz_daily_content": {
        "task": "core.tasks.scrape_cruz_daily_content",
        "schedule": crontab(minute=0, hour=6),
    },
    "purge_scraper_executions": {
        "task": "core.tasks.purge_scraper_executions",
        "schedule": crontab(minute=20, hour=3),
    },
}
