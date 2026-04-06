"""
Base Django settings for Prism project.
"""

import os
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Environment variables
env = environ.Env(
    DEBUG=(bool, False),
)

# Read .env file if it exists
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = env('SECRET_KEY')

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Third party
    'rest_framework',
    'corsheaders',
    'django_filters',
    'django_htmx',
    'django_celery_beat',
    'django_celery_results',
    'drf_spectacular',

    # Project apps - Production Pipeline
    'apps.core',
    'apps.articles',
    'apps.topics',
    'apps.web',
    'apps.analysis',
    'apps.consensus',
    'apps.summary',

    # Project apps - Validation & Analysis
    'apps.datasets',
    'apps.extraction',
    'apps.evaluation',
    'apps.experiments',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'django_htmx.middleware.HtmxMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Internationalization
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Django REST Framework
REST_FRAMEWORK = {
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 20,
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
        'rest_framework.filters.SearchFilter',
        'rest_framework.filters.OrderingFilter',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '1000/hour',
    },
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
}

# API Documentation
SPECTACULAR_SETTINGS = {
    'TITLE': 'Prism API',
    'DESCRIPTION': 'News bias analysis API — omission, tone, and framing metrics',
    'VERSION': '1.0.0',
}

# Cache Configuration
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': env('REDIS_URL', default='redis://localhost:6379/0'),
        'KEY_PREFIX': 'prism',
        'TIMEOUT': 300,
    }
}

# Celery Configuration
CELERY_BROKER_URL = env('REDIS_URL', default='redis://localhost:6379/0')
CELERY_RESULT_BACKEND = 'django-db'
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'
CELERY_TASK_TIME_LIMIT = 600          # Hard kill after 10 minutes
CELERY_TASK_SOFT_TIME_LIMIT = 480     # Graceful shutdown after 8 minutes
CELERY_RESULT_EXPIRES = 86400         # Clean up task results after 24 hours

# Event Registry Configuration
EVENT_REGISTRY_API_KEY = env('NEWSAPI_AI_KEY', default='')
EVENT_REGISTRY_MIN_ARTICLES = env.int('EVENT_REGISTRY_MIN_ARTICLES', default=5)
EVENT_REGISTRY_FETCH_HOURS = env.int('EVENT_REGISTRY_FETCH_HOURS', default=24)
EVENT_REGISTRY_LANG = env('EVENT_REGISTRY_LANG', default='eng')

# LLM Configuration
LLM_BACKEND = env('LLM_BACKEND', default='deepseek')  # 'ollama' or 'deepseek'

# Ollama (local inference)
OLLAMA_BASE_URL = env('OLLAMA_BASE_URL', default='http://localhost:11434')
OLLAMA_MODEL = env('OLLAMA_MODEL', default='llama3.2')
OLLAMA_TIMEOUT = env.int('OLLAMA_TIMEOUT', default=120)

# DeepSeek API (cloud)
DEEPSEEK_API_KEY = env('DEEPSEEK_API_KEY', default='')
DEEPSEEK_MODEL = env('DEEPSEEK_MODEL', default='deepseek-chat')
DEEPSEEK_BASE_URL = env('DEEPSEEK_BASE_URL', default='https://api.deepseek.com')

# Semantic Evaluation Configuration
SEMANTIC_MODEL = env('SEMANTIC_MODEL', default='all-MiniLM-L6-v2')
DEFAULT_SIMILARITY_THRESHOLD = env.float('DEFAULT_SIMILARITY_THRESHOLD', default=0.8)

# Analysis Classifiers
TONE_MODEL = env('TONE_MODEL', default='GroNLP/mdebertav3-subjectivity-english')
TONE_CONFIDENCE_THRESHOLD = env.float('TONE_CONFIDENCE_THRESHOLD', default=0.55)
FRAMING_MODEL = env('FRAMING_MODEL', default='matous-volf/political-leaning-politics')
FRAMING_TOKENIZER = env('FRAMING_TOKENIZER', default='launch/POLITICS')

# Consensus Pool Configuration
CONSENSUS_MIN_SOURCES = env.int('CONSENSUS_MIN_SOURCES', default=3)
CONSENSUS_SIMILARITY_THRESHOLD = env.float('CONSENSUS_SIMILARITY_THRESHOLD', default=0.85)
CONSENSUS_VITAL_THRESHOLD = env.int('CONSENSUS_VITAL_THRESHOLD', default=3)
CONSENSUS_PARTIAL_WEIGHT = env.float('CONSENSUS_PARTIAL_WEIGHT', default=0.5)
CONSENSUS_VITAL_WEIGHT = env.float('CONSENSUS_VITAL_WEIGHT', default=2.0)

# Post-processing (merge + tiering)
CONSENSUS_POST_PROCESSING_ENABLED = env.bool('CONSENSUS_POST_PROCESSING_ENABLED', default=True)
CONSENSUS_MERGE_BATCH_SIZE = env.int('CONSENSUS_MERGE_BATCH_SIZE', default=30)
CONSENSUS_TIER1_TARGET = env.int('CONSENSUS_TIER1_TARGET', default=5)
CONSENSUS_TIER2_TARGET = env.int('CONSENSUS_TIER2_TARGET', default=15)

# Dataset Paths
ROTOWIRE_DATA_PATH = BASE_DIR / 'data' / 'rotowire'
BILLSUM_CACHE_DIR = BASE_DIR / 'data' / 'billsum'
