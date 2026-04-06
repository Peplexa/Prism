"""Celery tasks for neutral summary generation."""

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=1)
def generate_summary(self, topic_id, regenerate=False):
    """Generate a neutral summary for a topic with a completed consensus pool."""
    from .services.summarizer import NeutralSummarizer
    from apps.topics.models import Topic

    try:
        Topic.objects.get(id=topic_id)
    except Topic.DoesNotExist:
        logger.error(f"Topic {topic_id} not found")
        return None

    try:
        summarizer = NeutralSummarizer(backend=settings.LLM_BACKEND)
        summary = summarizer.generate(topic_id, regenerate=regenerate)
        return f"Summary for topic {topic_id}: {summary.status}"
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error(f"Summary generation transient error for topic {topic_id}: {e}")
        raise self.retry(exc=e, countdown=120)
    except Exception as e:
        logger.error(f"Summary generation failed for topic {topic_id}: {e}")
        return None


@shared_task
def generate_missing_summaries(limit=50):
    """Generate summaries for topics with completed pools but no summary."""
    from apps.consensus.models import ConsensusPool

    topic_ids = list(
        ConsensusPool.objects.filter(
            status=ConsensusPool.Status.COMPLETE,
            topic__neutral_summary__isnull=True,
        ).values_list('topic_id', flat=True)[:limit]
    )

    for topic_id in topic_ids:
        generate_summary.delay(topic_id)

    logger.info(f"Queued {len(topic_ids)} summaries for generation")
    return f"Queued {len(topic_ids)} summaries"
