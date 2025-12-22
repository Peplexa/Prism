"""Pytest fixtures for Prism tests."""

import pytest
from datetime import datetime, timedelta
from django.utils import timezone

from apps.articles.models import Source, Article
from apps.topics.models import Topic, ArticleCluster


@pytest.fixture
def source_npr(db):
    """Create NPR source fixture."""
    return Source.objects.create(
        name='NPR',
        slug='npr',
        website_url='https://www.npr.org',
        discovery_method=Source.DiscoveryMethod.RSS,
        discovery_url='https://feeds.npr.org/1001/rss.xml',
        known_bias=Source.BiasRating.LEFT,
        is_active=True,
    )


@pytest.fixture
def source_fox(db):
    """Create Fox News source fixture."""
    return Source.objects.create(
        name='Fox News',
        slug='fox-news',
        website_url='https://www.foxnews.com',
        discovery_method=Source.DiscoveryMethod.HOMEPAGE,
        discovery_url='https://www.foxnews.com',
        known_bias=Source.BiasRating.RIGHT,
        is_active=True,
    )


@pytest.fixture
def source_reuters(db):
    """Create Reuters source fixture."""
    return Source.objects.create(
        name='Reuters',
        slug='reuters',
        website_url='https://www.reuters.com',
        discovery_method=Source.DiscoveryMethod.SITEMAP,
        discovery_url='https://www.reuters.com/sitemap.xml',
        known_bias=Source.BiasRating.CENTER,
        is_active=True,
    )


@pytest.fixture
def article_npr(db, source_npr):
    """Create an article from NPR."""
    return Article.objects.create(
        source=source_npr,
        title='Test Article from NPR',
        slug='test-article-npr',
        url='https://www.npr.org/2024/01/01/test-article',
        summary='This is a test article summary from NPR.',
        content='This is the full content of the test article from NPR. ' * 50,
        published_at=timezone.now() - timedelta(hours=2),
        status=Article.ProcessingStatus.SCRAPED,
    )


@pytest.fixture
def article_fox(db, source_fox):
    """Create an article from Fox News."""
    return Article.objects.create(
        source=source_fox,
        title='Test Article from Fox News',
        slug='test-article-fox',
        url='https://www.foxnews.com/politics/test-article',
        summary='This is a test article summary from Fox News.',
        content='This is the full content of the test article from Fox News. ' * 50,
        published_at=timezone.now() - timedelta(hours=1),
        status=Article.ProcessingStatus.SCRAPED,
    )


@pytest.fixture
def article_with_embedding(db, source_npr):
    """Create an article with embedding."""
    import numpy as np
    embedding = np.random.rand(384).tolist()  # MiniLM embedding size

    return Article.objects.create(
        source=source_npr,
        title='Article with Embedding',
        slug='article-with-embedding',
        url='https://www.npr.org/2024/01/02/embedded-article',
        summary='This article has an embedding.',
        content='Full content here. ' * 100,
        published_at=timezone.now() - timedelta(hours=1),
        status=Article.ProcessingStatus.EMBEDDED,
        embedding=embedding,
    )


@pytest.fixture
def topic(db):
    """Create a topic fixture."""
    return Topic.objects.create(
        title='Test Topic',
        slug='test-topic',
        description='A test topic for unit tests.',
        keywords=['test', 'topic', 'news'],
        trending_score=5.0,
        is_trending=True,
    )


@pytest.fixture
def topic_with_articles(db, topic, article_npr, article_fox):
    """Create a topic with clustered articles."""
    ArticleCluster.objects.create(
        topic=topic,
        article=article_npr,
        confidence_score=0.95,
        cluster_rank=0,
    )
    ArticleCluster.objects.create(
        topic=topic,
        article=article_fox,
        confidence_score=0.85,
        cluster_rank=1,
    )

    # Update article statuses
    article_npr.status = Article.ProcessingStatus.CLUSTERED
    article_npr.save()
    article_fox.status = Article.ProcessingStatus.CLUSTERED
    article_fox.save()

    # Update topic metrics
    topic.update_metrics()

    return topic


@pytest.fixture
def multiple_embedded_articles(db, source_npr, source_fox, source_reuters):
    """Create multiple articles with embeddings for clustering tests."""
    import numpy as np

    articles = []
    sources = [source_npr, source_fox, source_reuters]

    # Create articles about "election" topic
    for i, source in enumerate(sources):
        embedding = np.random.rand(384).tolist()
        article = Article.objects.create(
            source=source,
            title=f'Election Results Coverage {i+1}',
            slug=f'election-coverage-{i+1}',
            url=f'https://{source.slug}.com/election-{i+1}',
            summary='Coverage of the latest election results.',
            content='Election content here. ' * 100,
            published_at=timezone.now() - timedelta(hours=i),
            status=Article.ProcessingStatus.EMBEDDED,
            embedding=embedding,
        )
        articles.append(article)

    # Create articles about "weather" topic
    for i, source in enumerate(sources):
        embedding = np.random.rand(384).tolist()
        article = Article.objects.create(
            source=source,
            title=f'Weather Forecast Update {i+1}',
            slug=f'weather-forecast-{i+1}',
            url=f'https://{source.slug}.com/weather-{i+1}',
            summary='Latest weather forecast information.',
            content='Weather content here. ' * 100,
            published_at=timezone.now() - timedelta(hours=i),
            status=Article.ProcessingStatus.EMBEDDED,
            embedding=embedding,
        )
        articles.append(article)

    return articles
