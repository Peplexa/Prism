import os
from celery import Celery
from celery.schedules import crontab

# Set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')

app = Celery('prism')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django apps.
app.autodiscover_tasks()

# Celery Beat schedule
app.conf.beat_schedule = {
    # Poll Event Registry for new events every 5 minutes
    'fetch-events': {
        'task': 'apps.articles.tasks.fetch_events',
        'schedule': crontab(minute='*/5'),
    },

    # Update trending scores every 15 minutes
    'update-trending': {
        'task': 'apps.topics.tasks.update_trending_scores',
        'schedule': crontab(minute='*/15'),
    },

    # Cleanup old topics daily at 3am
    'cleanup-old-topics': {
        'task': 'apps.articles.tasks.cleanup_old_topics',
        'schedule': crontab(hour=3, minute=0),
    },

    # Backfill analysis for unanalyzed articles every hour
    'analyze-unanalyzed-articles': {
        'task': 'apps.analysis.tasks.analyze_unanalyzed_articles',
        'schedule': crontab(minute=30),
    },

    # Build consensus pools for topics with enough sources (every 30 min)
    'build-consensus-pools': {
        'task': 'apps.consensus.tasks.build_pools_for_ready_topics',
        'schedule': crontab(minute='*/30'),
    },

    # Generate neutral summaries for topics with completed pools (hourly at :15)
    'generate-missing-summaries': {
        'task': 'apps.summary.tasks.generate_missing_summaries',
        'schedule': crontab(minute=15),
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
