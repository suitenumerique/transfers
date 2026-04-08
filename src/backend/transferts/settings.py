"""Django settings for the Transferts project."""

import logging
import os
import tomllib
from socket import gethostbyname, gethostname

import dj_database_url
import sentry_sdk
from configurations import Configuration, values
from sentry_sdk.integrations.django import DjangoIntegration

from core.utils import JSONValue

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_release():
    """Get the current release of the application."""
    try:
        with open(os.path.join(BASE_DIR, "pyproject.toml"), "rb") as f:
            pyproject_data = tomllib.load(f)
        return pyproject_data["project"]["version"]
    except (FileNotFoundError, KeyError):
        return "NA"


class Base(Configuration):
    """Base configuration for all environments."""

    DEBUG = False
    USE_SWAGGER = False

    API_VERSION = "v1.0"

    # Admin
    ADMIN_URL = values.Value("admin")

    # Upload limits
    DATA_UPLOAD_MAX_MEMORY_SIZE = values.PositiveIntegerValue(
        100 * 1024 * 1024,  # 100 MiB
        environ_name="DATA_UPLOAD_MAX_MEMORY_SIZE",
        environ_prefix=None,
    )

    # Security
    ALLOWED_HOSTS = values.ListValue([])
    SECRET_KEY = values.Value(None)

    USE_X_FORWARDED_FOR = values.BooleanValue(
        default=False, environ_name="USE_X_FORWARDED_FOR", environ_prefix=None
    )

    # Application definition
    ROOT_URLCONF = "transferts.urls"
    WSGI_APPLICATION = "transferts.wsgi.application"

    # Database
    DATABASES = {
        "default": dj_database_url.config()
        if os.environ.get("DATABASE_URL")
        else {
            "ENGINE": values.Value(
                "django.db.backends.postgresql",
                environ_name="DB_ENGINE",
                environ_prefix=None,
            ),
            "NAME": values.Value(
                "transferts", environ_name="DB_NAME", environ_prefix=None
            ),
            "USER": values.Value(
                "dbuser", environ_name="DB_USER", environ_prefix=None
            ),
            "PASSWORD": values.Value(
                "dbpass", environ_name="DB_PASSWORD", environ_prefix=None
            ),
            "HOST": values.Value(
                "localhost", environ_name="DB_HOST", environ_prefix=None
            ),
            "PORT": values.Value(
                5432, environ_name="DB_PORT", environ_prefix=None
            ),
        },
    }
    DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

    DATA_DIR = values.Value(
        "/data", environ_name="DJANGO_DATA_DIR", environ_prefix=None
    )

    # Static files
    STATIC_URL = "/static/"
    STATIC_ROOT = os.path.join(DATA_DIR, "static")
    MEDIA_URL = "/media/"
    MEDIA_ROOT = os.path.join(DATA_DIR, "media")

    SITE_ID = 1

    # S3 Storage
    AWS_S3_DOMAIN_REPLACE = values.Value(
        environ_name="AWS_S3_DOMAIN_REPLACE", environ_prefix=None
    )
    AWS_S3_ENDPOINT_URL = values.Value(
        environ_name="AWS_S3_ENDPOINT_URL", environ_prefix=None
    )
    AWS_S3_ACCESS_KEY_ID = values.Value(
        environ_name="AWS_S3_ACCESS_KEY_ID", environ_prefix=None
    )
    AWS_S3_SECRET_ACCESS_KEY = values.Value(
        environ_name="AWS_S3_SECRET_ACCESS_KEY", environ_prefix=None
    )
    AWS_S3_REGION_NAME = values.Value(
        environ_name="AWS_S3_REGION_NAME", environ_prefix=None
    )
    AWS_S3_SIGNATURE_VERSION = values.Value(
        "s3v4", environ_name="AWS_S3_SIGNATURE_VERSION", environ_prefix=None
    )

    # Transfers bucket
    TRANSFERS_BUCKET_NAME = values.Value(
        "transferts", environ_name="TRANSFERS_BUCKET_NAME", environ_prefix=None
    )

    STORAGES = {
        "default": {
            "BACKEND": "storages.backends.s3.S3Storage",
        },
        "staticfiles": {
            "BACKEND": values.Value(
                "whitenoise.storage.CompressedManifestStaticFilesStorage",
                environ_name="STORAGES_STATICFILES_BACKEND",
            ),
        },
    }

    # Internationalization
    LANGUAGE_CODE = values.Value("fr-fr")
    LANGUAGES = values.SingleNestedTupleValue(
        (
            ("fr-fr", "French"),
            ("en-us", "English"),
        )
    )
    TIME_ZONE = "UTC"
    USE_I18N = False
    USE_TZ = True

    # Templates
    TEMPLATES = [
        {
            "BACKEND": "django.template.backends.django.DjangoTemplates",
            "DIRS": [os.path.join(BASE_DIR, "templates")],
            "OPTIONS": {
                "context_processors": [
                    "django.contrib.auth.context_processors.auth",
                    "django.contrib.messages.context_processors.messages",
                    "django.template.context_processors.csrf",
                    "django.template.context_processors.debug",
                    "django.template.context_processors.media",
                    "django.template.context_processors.request",
                    "django.template.context_processors.tz",
                ],
                "loaders": [
                    "django.template.loaders.filesystem.Loader",
                    "django.template.loaders.app_directories.Loader",
                ],
            },
        },
    ]

    MIDDLEWARE = [
        "django.middleware.security.SecurityMiddleware",
        "whitenoise.middleware.WhiteNoiseMiddleware",
        "django.contrib.sessions.middleware.SessionMiddleware",
        "django.middleware.clickjacking.XFrameOptionsMiddleware",
        "corsheaders.middleware.CorsMiddleware",
        "django.middleware.common.CommonMiddleware",
        "django.middleware.csrf.CsrfViewMiddleware",
        "django.contrib.auth.middleware.AuthenticationMiddleware",
        "django.contrib.messages.middleware.MessageMiddleware",
    ]

    AUTHENTICATION_BACKENDS = [
        "django.contrib.auth.backends.ModelBackend",
        "core.authentication.backends.OIDCAuthenticationBackend",
    ]

    INSTALLED_APPS = [
        "core",
        "drf_spectacular",
        "corsheaders",
        "django_celery_beat",
        "django_celery_results",
        "django_filters",
        "rest_framework",
        "django.contrib.admin",
        "django.contrib.auth",
        "django.contrib.contenttypes",
        "django.contrib.postgres",
        "django.contrib.sessions",
        "django.contrib.sites",
        "django.contrib.messages",
        "django.contrib.staticfiles",
    ]

    # Cache
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    }

    REST_FRAMEWORK = {
        "DEFAULT_AUTHENTICATION_CLASSES": (
            "mozilla_django_oidc.contrib.drf.OIDCAuthentication",
            "rest_framework.authentication.SessionAuthentication",
        ),
        "DEFAULT_PARSER_CLASSES": [
            "rest_framework.parsers.JSONParser",
            "rest_framework.parsers.MultiPartParser",
        ],
        "EXCEPTION_HANDLER": "core.api.exception_handler",
        "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
        "PAGE_SIZE": 20,
        "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.URLPathVersioning",
        "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    }

    SPECTACULAR_SETTINGS = {
        "TITLE": "Transferts API",
        "DESCRIPTION": "API for the Transferts file sharing service.",
        "VERSION": "1.0.0",
        "SERVE_INCLUDE_SCHEMA": False,
        "COMPONENT_SPLIT_REQUEST": True,
    }

    AUTH_USER_MODEL = "core.User"

    # CORS
    CORS_ALLOW_CREDENTIALS = True
    CORS_ALLOW_ALL_ORIGINS = values.BooleanValue(False)
    CORS_ALLOWED_ORIGINS = values.ListValue([])
    CORS_ALLOWED_ORIGIN_REGEXES = values.ListValue([])

    # Sentry
    SENTRY_DSN = values.Value(None, environ_name="SENTRY_DSN", environ_prefix=None)

    # Frontend
    FRONTEND_THEME = values.Value(
        None, environ_name="FRONTEND_THEME", environ_prefix=None
    )

    # Celery
    CELERY_BROKER_URL = values.Value(
        "redis://redis:6379", environ_name="CELERY_BROKER_URL", environ_prefix=None
    )
    CELERY_RESULT_BACKEND = "django-db"
    CELERY_CACHE_BACKEND = "django-cache"
    CELERY_BROKER_TRANSPORT_OPTIONS = values.DictValue({})
    CELERY_RESULT_EXTENDED = True
    CELERY_TASK_RESULT_EXPIRES = 60 * 60 * 24 * 30  # 30 days
    CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"
    CELERY_WORKER_HIJACK_ROOT_LOGGER = False
    CELERY_TASK_DEFAULT_QUEUE = "default"

    # Session
    SESSION_ENGINE = "django.contrib.sessions.backends.cache"
    SESSION_CACHE_ALIAS = "default"
    SESSION_COOKIE_AGE = 60 * 60 * 12

    # Email
    EMAIL_HOST = values.Value(
        "mailcatcher", environ_name="DJANGO_EMAIL_HOST", environ_prefix=None
    )
    EMAIL_PORT = values.PositiveIntegerValue(
        1025, environ_name="DJANGO_EMAIL_PORT", environ_prefix=None
    )
    EMAIL_BRAND_NAME = values.Value(
        "La Suite territoriale",
        environ_name="DJANGO_EMAIL_BRAND_NAME",
        environ_prefix=None,
    )

    # OIDC - Authorization Code Flow
    OIDC_CREATE_USER = values.BooleanValue(
        default=False, environ_name="OIDC_CREATE_USER", environ_prefix=None
    )
    OIDC_RP_SIGN_ALGO = values.Value(
        "RS256", environ_name="OIDC_RP_SIGN_ALGO", environ_prefix=None
    )
    OIDC_RP_CLIENT_ID = values.Value(
        "transferts", environ_name="OIDC_RP_CLIENT_ID", environ_prefix=None
    )
    OIDC_RP_CLIENT_SECRET = values.Value(
        None, environ_name="OIDC_RP_CLIENT_SECRET", environ_prefix=None
    )
    OIDC_OP_JWKS_ENDPOINT = values.Value(
        environ_name="OIDC_OP_JWKS_ENDPOINT", environ_prefix=None
    )
    OIDC_OP_AUTHORIZATION_ENDPOINT = values.Value(
        environ_name="OIDC_OP_AUTHORIZATION_ENDPOINT", environ_prefix=None
    )
    OIDC_OP_TOKEN_ENDPOINT = values.Value(
        None, environ_name="OIDC_OP_TOKEN_ENDPOINT", environ_prefix=None
    )
    OIDC_OP_USER_ENDPOINT = values.Value(
        None, environ_name="OIDC_OP_USER_ENDPOINT", environ_prefix=None
    )
    OIDC_OP_LOGOUT_ENDPOINT = values.Value(
        None, environ_name="OIDC_OP_LOGOUT_ENDPOINT", environ_prefix=None
    )
    OIDC_AUTH_REQUEST_EXTRA_PARAMS = values.DictValue(
        {}, environ_name="OIDC_AUTH_REQUEST_EXTRA_PARAMS", environ_prefix=None
    )
    OIDC_RP_SCOPES = values.Value(
        "openid email", environ_name="OIDC_RP_SCOPES", environ_prefix=None
    )
    OIDC_AUTHENTICATE_CLASS = "lasuite.oidc_login.views.OIDCAuthenticationRequestView"
    OIDC_CALLBACK_CLASS = "lasuite.oidc_login.views.OIDCAuthenticationCallbackView"
    LOGIN_REDIRECT_URL = values.Value(
        None, environ_name="LOGIN_REDIRECT_URL", environ_prefix=None
    )
    LOGIN_REDIRECT_URL_FAILURE = values.Value(
        None, environ_name="LOGIN_REDIRECT_URL_FAILURE", environ_prefix=None
    )
    LOGOUT_REDIRECT_URL = values.Value(
        None, environ_name="LOGOUT_REDIRECT_URL", environ_prefix=None
    )
    OIDC_USE_NONCE = values.BooleanValue(
        default=True, environ_name="OIDC_USE_NONCE", environ_prefix=None
    )
    OIDC_REDIRECT_REQUIRE_HTTPS = values.BooleanValue(
        default=False, environ_name="OIDC_REDIRECT_REQUIRE_HTTPS", environ_prefix=None
    )
    OIDC_REDIRECT_ALLOWED_HOSTS = values.ListValue(
        default=[], environ_name="OIDC_REDIRECT_ALLOWED_HOSTS", environ_prefix=None
    )
    OIDC_STORE_ID_TOKEN = values.BooleanValue(
        default=True, environ_name="OIDC_STORE_ID_TOKEN", environ_prefix=None
    )
    OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION = values.BooleanValue(
        default=True,
        environ_name="OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION",
        environ_prefix=None,
    )
    OIDC_ALLOW_DUPLICATE_EMAILS = values.BooleanValue(
        default=False,
        environ_name="OIDC_ALLOW_DUPLICATE_EMAILS",
        environ_prefix=None,
    )
    OIDC_USERINFO_ESSENTIAL_CLAIMS = values.ListValue(
        default=[], environ_name="OIDC_USERINFO_ESSENTIAL_CLAIMS", environ_prefix=None
    )
    OIDC_USERINFO_FULLNAME_FIELDS = values.ListValue(
        default=["first_name", "last_name"],
        environ_name="OIDC_USERINFO_FULLNAME_FIELDS",
        environ_prefix=None,
    )
    ALLOW_LOGOUT_GET_METHOD = values.BooleanValue(
        default=True, environ_name="ALLOW_LOGOUT_GET_METHOD", environ_prefix=None
    )

    # Logging
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "simple": {
                "format": "{asctime} {name} {levelname} {message}",
                "style": "{",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "simple",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": values.Value(
                "INFO", environ_name="LOGGING_LEVEL_LOGGERS_ROOT", environ_prefix=None
            ),
        },
        "loggers": {
            "core": {
                "handlers": ["console"],
                "level": values.Value(
                    "INFO",
                    environ_name="LOGGING_LEVEL_LOGGERS_APP",
                    environ_prefix=None,
                ),
                "propagate": False,
            },
            "botocore": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
            "urllib3": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
        },
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.USE_X_FORWARDED_FOR:
            self.MIDDLEWARE.insert(0, "core.middlewares.XForwardedForMiddleware")

    @property
    def ENVIRONMENT(self):
        return self.__class__.__name__.lower()

    @property
    def RELEASE(self):
        return get_release()

    @classmethod
    def post_setup(cls):
        super().post_setup()

        if cls.SENTRY_DSN is not None:
            sentry_sdk.init(
                dsn=cls.SENTRY_DSN,
                environment=cls.__name__.lower(),
                release=get_release(),
                integrations=[DjangoIntegration()],
            )
            sentry_sdk.set_tag("application", "backend")

        if (
            cls.OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION
            and cls.OIDC_ALLOW_DUPLICATE_EMAILS
        ):
            raise ValueError(
                "Both OIDC_FALLBACK_TO_EMAIL_FOR_IDENTIFICATION and "
                "OIDC_ALLOW_DUPLICATE_EMAILS cannot be set to True simultaneously."
            )


class Build(Base):
    """Settings for building the application (not for running)."""

    SECRET_KEY = values.Value("DummyKey")
    STORAGES = {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
        },
        "staticfiles": {
            "BACKEND": values.Value(
                "whitenoise.storage.CompressedManifestStaticFilesStorage",
                environ_name="STORAGES_STATICFILES_BACKEND",
            ),
        },
    }


class Development(Base):
    """Development environment settings."""

    ALLOWED_HOSTS = ["*"]
    CORS_ALLOW_ALL_ORIGINS = True
    CSRF_TRUSTED_ORIGINS = ["http://localhost:8900", "http://localhost:8901"]
    DEBUG = True

    SESSION_COOKIE_NAME = "transferts_sessionid"

    USE_SWAGGER = True
    SESSION_CACHE_ALIAS = "session"

    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": values.Value(
                "redis://redis:6379",
                environ_name="REDIS_URL",
                environ_prefix=None,
            ),
            "TIMEOUT": values.IntegerValue(
                30,
                environ_name="CACHES_DEFAULT_TIMEOUT",
                environ_prefix=None,
            ),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        },
        "session": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": values.Value(
                "redis://redis:6379",
                environ_name="REDIS_URL",
                environ_prefix=None,
            ),
            "TIMEOUT": values.IntegerValue(
                30,
                environ_name="CACHES_DEFAULT_TIMEOUT",
                environ_prefix=None,
            ),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        },
    }

    def __init__(self):
        super().__init__()
        self.INSTALLED_APPS += ["django_extensions", "drf_spectacular_sidecar"]


class DevelopmentMinimal(Development):
    """Development with minimal dependencies (no Redis/Celery)."""

    CELERY_TASK_ALWAYS_EAGER = True
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
        "session": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    }


class Test(Base):
    """Test environment settings."""

    PASSWORD_HASHERS = [
        "django.contrib.auth.hashers.MD5PasswordHasher",
    ]
    USE_SWAGGER = True
    CELERY_TASK_ALWAYS_EAGER = values.BooleanValue(True)
    AWS_S3_DOMAIN_REPLACE = None

    def __init__(self):
        super().__init__()
        self.INSTALLED_APPS += ["drf_spectacular_sidecar"]


class ContinuousIntegration(Test):
    """CI environment settings."""


class Production(Base):
    """Production environment settings."""

    ALLOWED_HOSTS = [
        *values.ListValue([], environ_name="ALLOWED_HOSTS"),
        gethostbyname(gethostname()),
    ]
    CSRF_TRUSTED_ORIGINS = values.ListValue([])
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_HSTS_SECONDS = 60
    SECURE_HSTS_PRELOAD = True
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_SSL_REDIRECT = True
    SECURE_REDIRECT_EXEMPT = [
        "^__lbheartbeat__",
        "^__heartbeat__",
    ]
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_SECURE = True
    SECURE_REFERRER_POLICY = "same-origin"

    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": values.Value(
                "redis://redis:6379",
                environ_name="REDIS_URL",
                environ_prefix=None,
            ),
            "TIMEOUT": values.IntegerValue(
                30,
                environ_name="CACHES_DEFAULT_TIMEOUT",
                environ_prefix=None,
            ),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        },
    }


class Staging(Production):
    """Staging environment settings."""


class PreProduction(Production):
    """Pre-production environment settings."""
