"""Celery tasks for consensus pool building and omission scoring."""

import logging

from celery import shared_task
from django.conf import settings
from django.db.models import Count

from apps.topics.models import Topic

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def build_consensus_pool(self, topic_id, rebuild=False):
    """
    Build a consensus fact pool for a topic.

    Extracts nuggets from all articles, deduplicates them into
    a consensus pool, and scores each article's omission.

    Args:
        topic_id: Topic ID to build pool for.
        rebuild: If True, delete existing pool and rebuild.
    """
    from .services.pool_builder import PoolBuilder

    try:
        builder = PoolBuilder(backend=settings.LLM_BACKEND)
        pool = builder.build(topic_id, rebuild=rebuild)

        # Auto-generate neutral summary after pool is complete
        if pool.status == 'complete':
            from apps.summary.tasks import generate_summary
            generate_summary.delay(topic_id)

        return (
            f"Pool for topic {topic_id}: "
            f"{pool.nugget_count} nuggets ({pool.vital_nugget_count} vital), "
            f"{pool.articles_processed} articles scored"
        )
    except Topic.DoesNotExist:
        logger.error(f"Topic {topic_id} not found")
        return None
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error(f"Pool build transient error for topic {topic_id}: {e}")
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
    except Exception as e:
        logger.error(f"Pool build failed for topic {topic_id}: {e}")
        return None


@shared_task
def build_pools_for_ready_topics(min_sources=None):
    """
    Find topics ready for consensus pool building and queue them.

    A topic is "ready" if it has articles from at least min_sources
    different news sources and doesn't already have a consensus pool.

    Args:
        min_sources: Minimum distinct sources required (default from settings).
    """
    if min_sources is None:
        min_sources = getattr(settings, 'CONSENSUS_MIN_SOURCES', 3)

    # Find topics with enough distinct sources and no existing pool
    ready_topics = (
        Topic.objects
        .filter(consensus_pool__isnull=True)
        .annotate(
            distinct_sources=Count(
                'clusters__article__source', distinct=True
            )
        )
        .filter(distinct_sources__gte=min_sources)
        .values_list('id', flat=True)
    )

    queued = 0
    for topic_id in ready_topics:
        build_consensus_pool.delay(topic_id)
        queued += 1

    logger.info(f"Queued {queued} topics for consensus pool building")
    return f"Queued {queued} topics"


@shared_task
def rebuild_stale_pools(min_new_articles=3):
    """
    Find topics where new articles have arrived since the pool was built
    and queue a rebuild.

    A pool is "stale" if the topic now has more non-wire articles than
    the pool's articles_processed count by at least min_new_articles.

    Args:
        min_new_articles: Minimum new articles before triggering rebuild.
    """
    from apps.articles.models import Article
    from .models import ConsensusPool

    pools = ConsensusPool.objects.filter(status='complete').select_related('topic')
    queued = 0

    for pool in pools:
        current_count = (
            Article.objects.filter(
                cluster__topic=pool.topic,
                status=Article.ProcessingStatus.COMPLETE,
                is_wire_content=False,
            )
            .exclude(content='')
            .count()
        )
        new_articles = current_count - pool.articles_processed
        if new_articles >= min_new_articles:
            logger.info(
                f"Topic '{pool.topic.title[:40]}' has {new_articles} new articles, "
                f"queuing rebuild"
            )
            build_consensus_pool.delay(pool.topic_id, rebuild=True)
            queued += 1

    logger.info(f"Queued {queued} stale pools for rebuild")
    return f"Queued {queued} stale pool rebuilds"


@shared_task(bind=True, max_retries=2)
def score_article_omission(self, article_id, pool_id):
    """
    Score a single article against an existing consensus pool.

    Used for scoring newly ingested articles against an existing pool.

    Args:
        article_id: Article ID to score.
        pool_id: ConsensusPool ID to score against.
    """
    from apps.articles.models import Article
    from apps.evaluation.services.auto_assigner import AutoAssigner

    from .models import ConsensusPool, ConsensusNugget, OmissionScore, NuggetJudgment
    from .services.pool_builder import _map_label, compute_scores

    try:
        pool = ConsensusPool.objects.get(id=pool_id)
        article = Article.objects.select_related('source').get(id=article_id)
    except (ConsensusPool.DoesNotExist, Article.DoesNotExist) as e:
        logger.error(f"Score article: {e}")
        return None

    if not article.content:
        return "No content"

    consensus_nuggets = list(pool.nuggets.order_by('id'))
    if not consensus_nuggets:
        return "Empty pool"

    consensus_texts = [cn.nugget_text for cn in consensus_nuggets]
    vital_indices = {
        i for i, cn in enumerate(consensus_nuggets)
        if cn.importance == ConsensusNugget.Importance.VITAL
    }

    assigner = AutoAssigner(backend=settings.LLM_BACKEND)

    try:
        result = assigner.assign(
            extracted_nuggets=[article.content],
            ground_truth_facts=consensus_texts,
            context=pool.topic.title,
        )
    except (ConnectionError, TimeoutError, OSError) as e:
        logger.error(f"Assignment transient error for article {article_id}: {e}")
        raise self.retry(exc=e, countdown=120)
    except Exception as e:
        logger.error(f"Assignment failed for article {article_id}: {e}")
        return None

    # Create or update score
    omission_score, _ = OmissionScore.objects.update_or_create(
        pool=pool, article=article,
        defaults={'error_message': ''},
    )

    from django.utils import timezone
    omission_score.scored_at = timezone.now()

    # Process assignments
    judgments = []
    support = partial = not_support = 0
    vital_support = vital_partial = 0

    for assignment in result.assignments:
        cn = consensus_nuggets[assignment.fact_index]
        label = _map_label(assignment.label)

        judgments.append(NuggetJudgment(
            score=omission_score,
            consensus_nugget=cn,
            label=label,
        ))

        if label == NuggetJudgment.Label.SUPPORT:
            support += 1
            if assignment.fact_index in vital_indices:
                vital_support += 1
        elif label == NuggetJudgment.Label.PARTIAL_SUPPORT:
            partial += 1
            if assignment.fact_index in vital_indices:
                vital_partial += 1
        else:
            not_support += 1

    omission_score.judgments.all().delete()
    NuggetJudgment.objects.bulk_create(judgments)

    total = len(consensus_texts)
    vital_total = len(vital_indices)

    omission_score.support_count = support
    omission_score.partial_support_count = partial
    omission_score.not_support_count = not_support
    omission_score.total_nuggets = total
    omission_score.vital_support_count = vital_support
    omission_score.vital_partial_support_count = vital_partial
    omission_score.vital_total = vital_total

    scores = compute_scores(
        support, partial, not_support, total,
        vital_support, vital_partial, vital_total,
    )
    omission_score.coverage_score = scores['coverage_score']
    omission_score.omission_rate = scores['omission_rate']
    omission_score.vital_omission_rate = scores['vital_omission_rate']

    omission_score.save()

    return (
        f"Scored {article.source.name}: "
        f"coverage={omission_score.coverage_score:.0%}"
    )
