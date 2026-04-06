"""Tests for Celery tasks."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import timedelta

from django.utils import timezone

from apps.articles.models import Source, Article
from apps.articles.tasks import (
    fetch_events,
    fetch_event_articles,
    cleanup_old_topics,
    _get_or_create_topic,
)
from apps.topics.models import Topic, ArticleCluster
from apps.topics.tasks import update_trending_scores


SAMPLE_EVENT = {
    "uri": "eng-123456",
    "title": {"eng": "Major Event Happened"},
    "summary": {"eng": "Summary of the major event."},
    "eventDate": "2024-01-15",
    "concepts": [
        {"label": {"eng": "Politics"}, "type": "wiki"},
        {"label": {"eng": "United States"}, "type": "loc"},
    ],
}

SAMPLE_ARTICLE = {
    "uri": "article-789",
    "url": "https://www.npr.org/2024/01/15/major-event",
    "title": "NPR Coverage of Major Event",
    "body": "Full article body text here. " * 50,
    "dateTime": "2024-01-15T14:30:00Z",
    "sentiment": 0.15,
    "sim": 0.92,
    "source": {
        "uri": "npr.org",
        "title": "NPR",
    },
    "authors": [
        {"name": "John Reporter"},
    ],
}


class TestGetOrCreateTopic:
    """Tests for the _get_or_create_topic helper."""

    def test_creates_topic(self, db):
        """Test that a new topic is created from event data."""
        topic, created = _get_or_create_topic(SAMPLE_EVENT)

        assert topic is not None
        assert created is True
        assert topic.title == "Major Event Happened"
        assert topic.event_registry_uri == "eng-123456"
        assert "Politics" in topic.keywords
        assert "United States" in topic.keywords

    def test_returns_existing_event(self, db):
        """Test that duplicate events return existing topic."""
        _get_or_create_topic(SAMPLE_EVENT)
        topic, created = _get_or_create_topic(SAMPLE_EVENT)

        assert topic is not None
        assert created is False
        assert Topic.objects.filter(event_registry_uri="eng-123456").count() == 1

    def test_skips_event_without_uri(self, db):
        """Test that events without URI are skipped."""
        topic, created = _get_or_create_topic({"title": {"eng": "No URI"}})
        assert topic is None

    def test_skips_event_without_title(self, db):
        """Test that events without title are skipped."""
        topic, created = _get_or_create_topic({"uri": "eng-999", "title": {}})
        assert topic is None

    def test_generates_unique_slugs(self, db):
        """Test that duplicate titles get unique slugs."""
        event1 = {**SAMPLE_EVENT, "uri": "eng-1"}
        event2 = {**SAMPLE_EVENT, "uri": "eng-2"}

        topic1, _ = _get_or_create_topic(event1)
        topic2, _ = _get_or_create_topic(event2)

        assert topic1.slug != topic2.slug


class TestFetchEvents:
    """Tests for the fetch_events task."""

    @patch('apps.articles.services.EventRegistryClient')
    def test_fetch_events_queues_article_fetching(self, mock_client_class, db):
        """Test that fetch_events queues article fetching with event data."""
        mock_client = MagicMock()
        mock_client.fetch_recent_events.return_value = [SAMPLE_EVENT]
        mock_client_class.return_value = mock_client

        with patch('apps.articles.tasks.fetch_event_articles.delay') as mock_delay:
            result = fetch_events()

        assert '1 new events' in result
        # Topic is NOT created yet — deferred to fetch_event_articles
        assert not Topic.objects.filter(event_registry_uri="eng-123456").exists()
        mock_delay.assert_called_once_with("eng-123456", None, False, SAMPLE_EVENT)

    @patch('apps.articles.services.EventRegistryClient')
    def test_fetch_events_skips_existing(self, mock_client_class, db):
        """Test that existing events are skipped."""
        Topic.objects.create(
            title="Existing",
            slug="existing",
            event_registry_uri="eng-123456",
        )

        mock_client = MagicMock()
        mock_client.fetch_recent_events.return_value = [SAMPLE_EVENT]
        mock_client_class.return_value = mock_client

        with patch('apps.articles.tasks.fetch_event_articles.delay') as mock_delay:
            result = fetch_events()

        assert '0 new events' in result
        mock_delay.assert_not_called()


class TestFetchEventArticles:
    """Tests for the fetch_event_articles task."""

    @patch('apps.analysis.tasks.analyze_article')
    @patch('apps.articles.services.EventRegistryClient')
    def test_ingests_articles_from_tracked_sources(
        self, mock_client_class, mock_analyze, source_npr, topic
    ):
        """Test that articles from tracked sources are ingested."""
        mock_client = MagicMock()
        mock_client.fetch_event_articles.return_value = [SAMPLE_ARTICLE]
        mock_client_class.return_value = mock_client

        result = fetch_event_articles(topic.event_registry_uri, topic.id)

        assert '1 articles ingested' in result
        article = Article.objects.get(url=SAMPLE_ARTICLE["url"])
        assert article.source == source_npr
        assert article.sentiment == 0.15
        assert article.status == Article.ProcessingStatus.COMPLETE
        assert article.event_registry_uri == "article-789"
        assert ArticleCluster.objects.filter(
            topic=topic, article=article
        ).exists()

    @patch('apps.analysis.tasks.analyze_article')
    @patch('apps.articles.services.EventRegistryClient')
    def test_auto_creates_unknown_sources(
        self, mock_client_class, mock_analyze, source_npr, topic
    ):
        """Test that articles from unknown sources auto-create the source."""
        unknown_article = {
            **SAMPLE_ARTICLE,
            "uri": "article-999",
            "url": "https://unknown.com/article",
            "source": {"uri": "unknown.com", "title": "Unknown"},
        }

        mock_client = MagicMock()
        mock_client.fetch_event_articles.return_value = [unknown_article]
        mock_client_class.return_value = mock_client

        result = fetch_event_articles(topic.event_registry_uri, topic.id)

        assert '1 articles ingested' in result
        assert Source.objects.filter(event_registry_uri='unknown.com').exists()

    @patch('apps.articles.services.EventRegistryClient')
    def test_skips_duplicate_urls(
        self, mock_client_class, source_npr, article_npr, topic
    ):
        """Test that articles with existing URLs are skipped."""
        duplicate_article = {
            **SAMPLE_ARTICLE,
            "url": article_npr.url,
        }

        mock_client = MagicMock()
        mock_client.fetch_event_articles.return_value = [duplicate_article]
        mock_client_class.return_value = mock_client

        initial_count = Article.objects.count()
        fetch_event_articles(topic.event_registry_uri, topic.id)

        assert Article.objects.count() == initial_count

    @patch('apps.analysis.tasks.analyze_article')
    @patch('apps.articles.services.EventRegistryClient')
    def test_updates_topic_metrics(
        self, mock_client_class, mock_analyze, source_npr, source_fox, topic
    ):
        """Test that topic metrics are updated after article ingestion."""
        fox_article = {
            **SAMPLE_ARTICLE,
            "uri": "article-fox",
            "url": "https://foxnews.com/event-article",
            "source": {"uri": "foxnews.com", "title": "Fox News"},
        }

        mock_client = MagicMock()
        mock_client.fetch_event_articles.return_value = [
            SAMPLE_ARTICLE, fox_article
        ]
        mock_client_class.return_value = mock_client

        fetch_event_articles(topic.event_registry_uri, topic.id)

        topic.refresh_from_db()
        assert topic.article_count == 2
        assert topic.source_count == 2

    def test_handles_missing_topic(self, db):
        """Test handling of non-existent topic ID."""
        result = fetch_event_articles("eng-999", 99999)
        assert result is None


class TestCleanupOldTopics:
    """Tests for the cleanup_old_topics task."""

    def test_cleanup_old_topics(self, db):
        """Test that old topics are deleted."""
        old_topic = Topic.objects.create(
            title='Old Topic',
            slug='old-topic',
            event_registry_uri='eng-old',
        )
        Topic.objects.filter(pk=old_topic.pk).update(
            created_at=timezone.now() - timedelta(days=60),
        )

        recent_topic = Topic.objects.create(
            title='Recent Topic',
            slug='recent-topic',
            event_registry_uri='eng-recent',
            last_article_at=timezone.now(),
        )

        result = cleanup_old_topics(days_old=30)

        assert 'Deleted 1' in result
        assert not Topic.objects.filter(pk=old_topic.pk).exists()
        assert Topic.objects.filter(pk=recent_topic.pk).exists()


class TestTrendingScores:
    """Tests for trending score updates."""

    def test_update_trending_scores(self, topic_with_articles):
        """Test trending score updates."""
        result = update_trending_scores()

        topic_with_articles.refresh_from_db()
        assert 'Updated' in result
        assert topic_with_articles.trending_score is not None

    def test_trending_flag(self, topic):
        """Test that trending flag is set based on score."""
        topic.trending_score = 10.0
        topic.save()

        update_trending_scores()

        topic.refresh_from_db()
        # Score recalculated based on actual articles
        assert topic.trending_score is not None
