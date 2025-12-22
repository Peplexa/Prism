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
    # Scrape all sources every hour
    'scrape-all-sources': {
        'task': 'apps.articles.tasks.scrape_all_sources',
        'schedule': crontab(minute=0),  # Every hour at :00
    },

    # Run clustering every 30 minutes
    'cluster-articles': {
        'task': 'apps.topics.tasks.cluster_recent_articles',
        'schedule': crontab(minute='*/30'),
    },

    # Update trending scores every 15 minutes
    'update-trending': {
        'task': 'apps.topics.tasks.update_trending_scores',
        'schedule': crontab(minute='*/15'),
    },

    # Cleanup failed articles daily at 3am
    'cleanup-failed': {
        'task': 'apps.articles.tasks.cleanup_failed_articles',
        'schedule': crontab(hour=3, minute=0),
    },

    # Merge similar topics daily at 4am
    'merge-topics': {
        'task': 'apps.topics.tasks.merge_similar_topics',
        'schedule': crontab(hour=4, minute=0),
    },
}


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
