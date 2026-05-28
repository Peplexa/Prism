"""Pytest fixtures for Prism tests."""

import pytest
from datetime import timedelta
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
        event_registry_uri='npr.org',

        is_active=True,
    )


@pytest.fixture
def source_fox(db):
    """Create Fox News source fixture."""
    return Source.objects.create(
        name='Fox News',
        slug='fox-news',
        website_url='https://www.foxnews.com',
        event_registry_uri='foxnews.com',

        is_active=True,
    )


@pytest.fixture
def source_reuters(db):
    """Create Reuters source fixture."""
    return Source.objects.create(
        name='Reuters',
        slug='reuters',
        website_url='https://www.reuters.com',
        event_registry_uri='reuters.com',

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
        status=Article.ProcessingStatus.COMPLETE,
        event_registry_uri='er-article-1',
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
        status=Article.ProcessingStatus.COMPLETE,
        event_registry_uri='er-article-2',
    )


@pytest.fixture
def topic(db):
    """Create a topic fixture."""
    return Topic.objects.create(
        title='Test Topic',
        slug='test-topic',
        description='A test topic for unit tests.',
        keywords=['test', 'topic', 'news'],
        event_registry_uri='eng-test-event-1',
        article_count=1,
        source_count=1,
        trending_score=5.0,
        is_trending=True,
    )


@pytest.fixture
def article_reuters(db, source_reuters):
    """Create an article from Reuters."""
    return Article.objects.create(
        source=source_reuters,
        title='Test Article from Reuters',
        slug='test-article-reuters',
        url='https://www.reuters.com/world/test-article',
        summary='This is a test article summary from Reuters.',
        content='This is the full content of the test article from Reuters. ' * 50,
        published_at=timezone.now() - timedelta(hours=1, minutes=30),
        status=Article.ProcessingStatus.COMPLETE,
        event_registry_uri='er-article-3',
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

    # Update topic metrics
    topic.update_metrics()

    return topic


@pytest.fixture
def topic_with_3_articles(db, topic, article_npr, article_fox, article_reuters):
    """Create a topic with 3 articles from different sources."""
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
    ArticleCluster.objects.create(
        topic=topic,
        article=article_reuters,
        confidence_score=0.90,
        cluster_rank=2,
    )

    topic.update_metrics()

    return topic
