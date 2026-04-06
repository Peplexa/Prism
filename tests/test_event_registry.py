"""Tests for the Event Registry client."""

import pytest
from unittest.mock import patch, MagicMock

from apps.articles.services.event_registry_client import EventRegistryClient


class TestEventRegistryClient:
    """Tests for EventRegistryClient wrapper."""

    @patch('apps.articles.services.event_registry_client.EventRegistry')
    def test_client_initializes(self, mock_er_class, settings):
        """Test that client initializes with API key from settings."""
        settings.EVENT_REGISTRY_API_KEY = 'test-key'
        client = EventRegistryClient()
        mock_er_class.assert_called_once_with(apiKey='test-key')

    @patch('apps.articles.services.event_registry_client.QueryEventsIter')
    @patch('apps.articles.services.event_registry_client.EventRegistry')
    def test_fetch_recent_events(self, mock_er_class, mock_query_class, settings):
        """Test fetching recent events."""
        settings.EVENT_REGISTRY_API_KEY = 'test-key'
        settings.EVENT_REGISTRY_FETCH_HOURS = 24
        settings.EVENT_REGISTRY_MIN_ARTICLES = 5
        settings.EVENT_REGISTRY_LANG = 'eng'

        mock_query = MagicMock()
        mock_query.execQuery.return_value = iter([
            {"uri": "eng-1", "title": {"eng": "Event 1"}},
            {"uri": "eng-2", "title": {"eng": "Event 2"}},
        ])
        mock_query_class.return_value = mock_query

        client = EventRegistryClient()
        events = client.fetch_recent_events()

        assert len(events) == 2
        assert events[0]["uri"] == "eng-1"

    @patch('apps.articles.services.event_registry_client.QueryEventArticlesIter')
    @patch('apps.articles.services.event_registry_client.EventRegistry')
    def test_fetch_event_articles(self, mock_er_class, mock_query_class, settings):
        """Test fetching articles for an event."""
        settings.EVENT_REGISTRY_API_KEY = 'test-key'
        settings.EVENT_REGISTRY_LANG = 'eng'

        mock_query = MagicMock()
        mock_query.execQuery.return_value = iter([
            {"uri": "art-1", "url": "https://example.com/1", "title": "Article 1"},
        ])
        mock_query_class.return_value = mock_query

        client = EventRegistryClient()
        articles = client.fetch_event_articles("eng-123")

        assert len(articles) == 1
        assert articles[0]["uri"] == "art-1"

    @patch('apps.articles.services.event_registry_client.QueryEventArticlesIter')
    @patch('apps.articles.services.event_registry_client.EventRegistry')
    def test_fetch_event_articles_with_source_filter(
        self, mock_er_class, mock_query_class, settings
    ):
        """Test filtering articles by source URIs."""
        settings.EVENT_REGISTRY_API_KEY = 'test-key'
        settings.EVENT_REGISTRY_LANG = 'eng'

        mock_query = MagicMock()
        mock_query.execQuery.return_value = iter([])
        mock_query_class.return_value = mock_query

        client = EventRegistryClient()
        client.fetch_event_articles(
            "eng-123", source_uris=["npr.org", "foxnews.com"]
        )

        # Verify source filter was passed
        call_kwargs = mock_query_class.call_args
        assert "sourceUri" in call_kwargs.kwargs

    @patch('apps.articles.services.event_registry_client.EventRegistry')
    def test_get_source_uri(self, mock_er_class, settings):
        """Test resolving source name to URI."""
        settings.EVENT_REGISTRY_API_KEY = 'test-key'
        mock_er = MagicMock()
        mock_er.getNewsSourceUri.return_value = "npr.org"
        mock_er_class.return_value = mock_er

        client = EventRegistryClient()
        uri = client.get_source_uri("NPR")

        assert uri == "npr.org"
        mock_er.getNewsSourceUri.assert_called_once_with("NPR")
