"""Celery tasks for topic clustering and management."""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone
from django.db import transaction

from .models import Topic, ArticleCluster
from .clustering import EmbeddingGenerator, ArticleClusterer
from apps.articles.models import Article

logger = logging.getLogger(__name__)


@shared_task(bind=True)
def generate_article_embedding(self, article_id: int):
    """
    Generate embedding for an article.

    Args:
        article_id: ID of the Article to process
    """
    try:
        article = Article.objects.get(id=article_id)
    except Article.DoesNotExist:
        logger.error(f"Article {article_id} not found")
        return

    if article.status != Article.ProcessingStatus.SCRAPED:
        logger.debug(f"Article {article_id} not ready for embedding (status: {article.status})")
        return

    try:
        generator = EmbeddingGenerator()
        text = generator.prepare_article_text(article)

        if not text:
            logger.warning(f"No text to embed for article {article_id}")
            return

        embedding = generator.generate(text)

        article.embedding = embedding.tolist()
        article.status = Article.ProcessingStatus.EMBEDDED
        article.save(update_fields=['embedding', 'status', 'updated_at'])

        logger.debug(f"Generated embedding for article {article_id}")
        return f"Embedded article {article_id}"

    except Exception as e:
        logger.error(f"Error generating embedding for article {article_id}: {e}")
        raise


@shared_task
def cluster_recent_articles(hours: int = 48):
    """
    Run clustering on recently embedded articles.

    Args:
        hours: Include articles from last N hours
    """
    cutoff = timezone.now() - timedelta(hours=hours)

    # Get articles with embeddings that aren't clustered yet
    articles = Article.objects.filter(
        status=Article.ProcessingStatus.EMBEDDED,
        created_at__gte=cutoff,
        embedding__isnull=False,
    )

    article_count = articles.count()
    if article_count < 5:
        logger.info(f"Not enough articles for clustering: {article_count}")
        return f"Not enough articles: {article_count}"

    logger.info(f"Clustering {article_count} articles")

    clusterer = ArticleClusterer()
    clusters = clusterer.cluster(articles)

    created_topics = 0
    updated_topics = 0

    for cluster_data in clusters:
        with transaction.atomic():
            # Try to find existing topic with similar slug
            topic = Topic.objects.filter(slug__startswith=cluster_data['slug'][:50]).first()

            if topic:
                # Update existing topic
                topic.keywords = list(set(topic.keywords + cluster_data['keywords']))[:15]
                topic.save(update_fields=['keywords', 'updated_at'])
                updated_topics += 1
            else:
                # Create new topic
                # Ensure unique slug
                base_slug = cluster_data['slug']
                slug = base_slug
                counter = 1
                while Topic.objects.filter(slug=slug).exists():
                    slug = f"{base_slug}-{counter}"
                    counter += 1

                topic = Topic.objects.create(
                    title=cluster_data['title'],
                    slug=slug,
                    keywords=cluster_data['keywords'],
                )
                created_topics += 1

            # Link articles to topic
            for article_data in cluster_data['articles']:
                article = Article.objects.get(id=article_data['id'])

                ArticleCluster.objects.update_or_create(
                    article=article,
                    defaults={
                        'topic': topic,
                        'confidence_score': article_data['confidence'],
                        'cluster_rank': article_data['rank'],
                    }
                )

                # Update article status
                article.status = Article.ProcessingStatus.CLUSTERED
                article.save(update_fields=['status', 'updated_at'])

            # Update topic metrics
            topic.update_metrics()

    logger.info(f"Clustering complete: {created_topics} new, {updated_topics} updated")
    return f"Created {created_topics} topics, updated {updated_topics}"


@shared_task
def update_trending_scores():
    """Update trending scores for all topics."""
    now = timezone.now()
    day_ago = now - timedelta(hours=24)

    topics = Topic.objects.all()
    updated = 0

    for topic in topics:
        # Count recent articles
        recent_count = topic.clusters.filter(
            article__published_at__gte=day_ago
        ).count()

        # Calculate trending score
        # Factor in: recency, source diversity, article count
        if topic.article_count > 0:
            source_diversity = topic.source_count / topic.article_count
        else:
            source_diversity = 0

        # Trending formula: recent articles weighted by diversity
        trending_score = recent_count * (1 + source_diversity)

        # Decay for older topics
        if topic.last_article_at:
            hours_since_update = (now - topic.last_article_at).total_seconds() / 3600
            decay_factor = max(0.1, 1 - (hours_since_update / 72))  # Decay over 72 hours
            trending_score *= decay_factor

        topic.trending_score = round(trending_score, 2)
        topic.is_trending = trending_score > 2  # Threshold for "trending"
        topic.save(update_fields=['trending_score', 'is_trending', 'updated_at'])
        updated += 1

    logger.info(f"Updated trending scores for {updated} topics")
    return f"Updated {updated} topics"


@shared_task
def merge_similar_topics(
    embedding_threshold: float = 0.60,
    keyword_boost: float = 0.15,
    time_window_hours: int = 72,
):
    """
    Find and merge topics that are too similar.

    Uses multiple signals:
    - Embedding similarity (cosine similarity of article embeddings)
    - Keyword overlap (shared important words in titles)
    - Time proximity (articles published within same time window)

    Args:
        embedding_threshold: Base cosine similarity threshold
        keyword_boost: Bonus added for significant keyword overlap
        time_window_hours: Hours within which topics are considered contemporaneous
    """
    from sklearn.metrics.pairwise import cosine_similarity
    import numpy as np
    import re

    topics = list(Topic.objects.filter(article_count__gte=1))

    if len(topics) < 2:
        return "Not enough topics to compare"

    # Build topic data: embeddings, keywords, time range
    topic_data = []
    for topic in topics:
        articles = list(Article.objects.filter(
            cluster__topic=topic,
            embedding__isnull=False
        )[:15])

        embeddings = [a.embedding for a in articles if a.embedding]
        if not embeddings:
            continue

        avg_embedding = np.mean(embeddings, axis=0)

        # Extract key entities from title (capitalized words, names)
        title_words = set(
            word.lower() for word in re.findall(r'\b[A-Z][a-z]+\b', topic.title)
            if len(word) > 2
        )
        # Add keywords
        title_words.update(kw.lower() for kw in topic.keywords[:5])

        # Get time range
        pub_dates = [a.published_at for a in articles if a.published_at]
        min_date = min(pub_dates) if pub_dates else None
        max_date = max(pub_dates) if pub_dates else None

        topic_data.append({
            'topic': topic,
            'embedding': avg_embedding,
            'keywords': title_words,
            'min_date': min_date,
            'max_date': max_date,
        })

    if len(topic_data) < 2:
        return "Not enough topics with embeddings"

    # Calculate embedding similarity matrix
    embeddings_matrix = np.array([d['embedding'] for d in topic_data])
    embedding_sims = cosine_similarity(embeddings_matrix)

    # Find pairs to merge
    merged = 0
    merged_ids = set()

    for i in range(len(topic_data)):
        if topic_data[i]['topic'].id in merged_ids:
            continue

        for j in range(i + 1, len(topic_data)):
            if topic_data[j]['topic'].id in merged_ids:
                continue

            # Calculate combined similarity score
            base_sim = embedding_sims[i, j]

            # Keyword overlap bonus
            kw_i = topic_data[i]['keywords']
            kw_j = topic_data[j]['keywords']
            if kw_i and kw_j:
                overlap = len(kw_i & kw_j)
                union = len(kw_i | kw_j)
                jaccard = overlap / union if union > 0 else 0
                # Significant overlap if Jaccard > 0.2 (sharing key names/terms)
                if jaccard > 0.2:
                    base_sim += keyword_boost
                    logger.debug(f"Keyword boost: {kw_i & kw_j}")

            # Time proximity check
            time_compatible = True
            if topic_data[i]['min_date'] and topic_data[j]['min_date']:
                # Check if time ranges overlap or are close
                from datetime import timedelta
                window = timedelta(hours=time_window_hours)
                if topic_data[i]['max_date'] and topic_data[j]['min_date']:
                    if topic_data[j]['min_date'] - topic_data[i]['max_date'] > window:
                        time_compatible = False
                if topic_data[j]['max_date'] and topic_data[i]['min_date']:
                    if topic_data[i]['min_date'] - topic_data[j]['max_date'] > window:
                        time_compatible = False

            # Decide whether to merge
            should_merge = base_sim >= embedding_threshold and time_compatible

            if should_merge:
                # Merge smaller into larger
                topic_a = topic_data[i]['topic']
                topic_b = topic_data[j]['topic']
                if topic_a.article_count < topic_b.article_count:
                    topic_a, topic_b = topic_b, topic_a

                # Move articles from topic_b to topic_a
                ArticleCluster.objects.filter(topic=topic_b).update(topic=topic_a)

                # Combine keywords
                combined_keywords = list(set(topic_a.keywords + topic_b.keywords))[:15]
                topic_a.keywords = combined_keywords
                topic_a.save()
                topic_a.update_metrics()

                # Delete the merged topic
                logger.info(f"Merged '{topic_b.title}' into '{topic_a.title}' (sim={base_sim:.3f})")
                topic_b.delete()
                merged_ids.add(topic_b.id)
                merged += 1

    return f"Merged {merged} similar topics"
