"""TaskFlow settings. Everything environment-specific comes from env vars so the
same code runs locally (SQLite, eager Celery), in Docker (Postgres, Redis) and on
Render."""
import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    return str(env(name, str(default))).lower() in ("1", "true", "yes", "on")


SECRET_KEY = env("SECRET_KEY", "dev-insecure-change-me")
DEBUG = env_bool("DEBUG", True)
if not DEBUG and SECRET_KEY == "dev-insecure-change-me":
    from django.core.exceptions import ImproperlyConfigured

    raise ImproperlyConfigured("Set a real SECRET_KEY when DEBUG is off (e.g. python -c 'import secrets;print(secrets.token_urlsafe(50))').")
ALLOWED_HOSTS = [h.strip() for h in env("ALLOWED_HOSTS", "*").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o for o in env("CSRF_TRUSTED_ORIGINS", "").split(",") if o]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "apps.accounts",
    "apps.workspaces",
    "apps.projects",
    "apps.audit",
    "apps.webhooks",
    "apps.billing",
    "apps.notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.workspaces.middleware.ResetActorMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
AUTH_USER_MODEL = "accounts.User"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=600
    )
}

if DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    # SQLite has a single writer. WAL + immediate write transactions + a longer busy timeout keep
    # concurrent requests from failing with "database is locked" in local/demo mode (Postgres in prod).
    DATABASES["default"].setdefault("OPTIONS", {}).update(
        {"timeout": 20, "transaction_mode": "IMMEDIATE", "init_command": "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"}
    )

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
     "OPTIONS": {"min_length": 8}},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}
MEDIA_URL = "/media/"
MEDIA_ROOT = Path(env("MEDIA_ROOT", str(BASE_DIR / "media")))
MAX_UPLOAD_BYTES = int(env("MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ---- DRF -------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "EXCEPTION_HANDLER": "config.exception_handler.exception_handler",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": (
        "rest_framework.throttling.ScopedRateThrottle",
    ),
    "DEFAULT_THROTTLE_RATES": {
        "auth": env("AUTH_THROTTLE", "30/min"),
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=int(env("ACCESS_TOKEN_MINUTES", 60))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=7),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "TaskFlow API",
    "DESCRIPTION": "Multi-tenant project management platform. All tenant data lives "
                   "under /api/w/{workspace_slug}/ and is scoped to that workspace.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
}

# ---- CORS ------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    o for o in env("CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o
]
CORS_ALLOW_ALL_ORIGINS = env_bool("CORS_ALLOW_ALL", False)
CORS_ALLOWED_ORIGIN_REGEXES = [r for r in env("CORS_ORIGIN_REGEX", "").split(",") if r]

# ---- Celery ----------------------------------------------------------------
REDIS_URL = env("REDIS_URL", "")
CELERY_BROKER_URL = REDIS_URL or "memory://"
CELERY_RESULT_BACKEND = REDIS_URL or "cache+memory://"
# With no Redis configured (plain local dev, tests, free hosting) tasks run inline.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_EAGER", not REDIS_URL)
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_BEAT_SCHEDULE = {
    "weekly-workspace-reports": {
        "task": "apps.notifications.tasks.send_weekly_reports",
        "schedule": 60 * 60 * 24 * 7,
    },
    "retry-failed-webhooks": {
        "task": "apps.webhooks.tasks.retry_failed_deliveries",
        "schedule": 60 * 5,
    },
}

# ---- Email -----------------------------------------------------------------
EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", "")
EMAIL_PORT = int(env("EMAIL_PORT", 587))
EMAIL_HOST_USER = env("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "TaskFlow <noreply@taskflow.local>")

FRONTEND_URL = env("FRONTEND_URL", "http://localhost:5173")

# ---- Stripe / billing ------------------------------------------------------
# Leave STRIPE_SECRET_KEY empty to run billing in mock mode (no Stripe account needed).
STRIPE_SECRET_KEY = env("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = env("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_PRO = env("STRIPE_PRICE_PRO", "")
STRIPE_PRICE_BUSINESS = env("STRIPE_PRICE_BUSINESS", "")

# Webhook delivery
WEBHOOK_TIMEOUT_SECONDS = int(env("WEBHOOK_TIMEOUT_SECONDS", 5))
WEBHOOK_MAX_ATTEMPTS = int(env("WEBHOOK_MAX_ATTEMPTS", 5))
# Block webhooks pointing at private networks (SSRF). Tests/dev may relax it.
WEBHOOK_ALLOW_PRIVATE = env_bool("WEBHOOK_ALLOW_PRIVATE", DEBUG)

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    # Secure cookies only make sense when served over HTTPS (Render/Vercel always are).
    _https = env_bool("HTTPS", True)
    SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = _https
    SECURE_HSTS_SECONDS = int(env("SECURE_HSTS_SECONDS", 0))  # raise (e.g. 31536000) once HTTPS is confirmed working
