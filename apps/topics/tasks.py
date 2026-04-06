"""Celery tasks for topic management."""

import logging
from datetime import timedelta

from celery import shared_task
from django.db import models
from django.db.models import Count, Q
from django.utils import timezone

from .models import Topic

logger = logging.getLogger(__name__)


@shared_task
def update_trending_scores():
    """Update trending scores for all topics using bulk queries."""
    now = timezone.now()
    day_ago = now - timedelta(hours=24)

    topics = list(
        Topic.objects.annotate(
            recent_count=Count(
                'clusters',
                filter=Q(clusters__article__published_at__gte=day_ago)
            )
        )
    )

    bulk_updates = []
    for topic in topics:
        # Calculate trending score
        if topic.article_count > 0:
            source_diversity = topic.source_count / topic.article_count
        else:
            source_diversity = 0

        # Trending formula: recent articles weighted by diversity
        trending_score = topic.recent_count * (1 + source_diversity)

        # Decay for older topics
        if topic.last_article_at:
            hours_since_update = (now - topic.last_article_at).total_seconds() / 3600
            decay_factor = max(0.1, 1 - (hours_since_update / 72))
            trending_score *= decay_factor

        topic.trending_score = round(trending_score, 2)
        topic.is_trending = trending_score > 2
        bulk_updates.append(topic)

    if bulk_updates:
        Topic.objects.bulk_update(bulk_updates, ['trending_score', 'is_trending'])

    logger.info(f"Updated trending scores for {len(bulk_updates)} topics")
    return f"Updated {len(bulk_updates)} topics"
