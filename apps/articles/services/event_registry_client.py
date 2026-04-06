"""Event Registry API client for fetching news events and articles."""

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone
from eventregistry import (
    EventRegistry,
    QueryEventsIter,
    QueryEventArticlesIter,
    ReturnInfo,
    ArticleInfoFlags,
    EventInfoFlags,
    SourceInfoFlags,
)

logger = logging.getLogger(__name__)


class EventRegistryClient:
    """Thin wrapper around the Event Registry SDK."""

    def __init__(self):
        self.er = EventRegistry(apiKey=settings.EVENT_REGISTRY_API_KEY)

    def fetch_recent_events(self, hours=None, min_articles=None, max_items=50):
        """
        Fetch recent events from Event Registry.

        Args:
            hours: How many hours back to look (default from settings).
            min_articles: Minimum articles per event (default from settings).
            max_items: Maximum number of events to return.

        Returns:
            List of event dicts from Event Registry.
        """
        if hours is None:
            hours = settings.EVENT_REGISTRY_FETCH_HOURS
        if min_articles is None:
            min_articles = settings.EVENT_REGISTRY_MIN_ARTICLES

        date_end = datetime.now()
        date_start = date_end - timedelta(hours=hours)

        lang = settings.EVENT_REGISTRY_LANG

        q = QueryEventsIter(
            dateStart=date_start.strftime('%Y-%m-%d'),
            dateEnd=date_end.strftime('%Y-%m-%d'),
            minArticlesInEvent=min_articles,
            lang=lang,
        )

        events = []
        for event in q.execQuery(
            self.er,
            sortBy="date",
            sortByAsc=False,
            maxItems=max_items,
            returnInfo=ReturnInfo(
                eventInfo=EventInfoFlags(
                    title=True,
                    summary=True,
                    articleCounts=True,
                    concepts=True,
                    categories=True,
                    location=True,
                    date=True,
                ),
            ),
        ):
            events.append(event)

        logger.info(f"Fetched {len(events)} events from Event Registry")
        return events

    def fetch_event_articles(self, event_uri, source_uris=None):
        """
        Fetch articles for a specific event.

        Args:
            event_uri: The Event Registry event URI.
            source_uris: Optional list of source URIs to filter by.

        Returns:
            List of article dicts from Event Registry.
        """
        lang = settings.EVENT_REGISTRY_LANG

        kwargs = {
            "lang": lang,
        }
        if source_uris:
            kwargs["sourceUri"] = source_uris

        q = QueryEventArticlesIter(event_uri, **kwargs)

        articles = []
        for article in q.execQuery(
            self.er,
            sortBy="date",
            returnInfo=ReturnInfo(
                articleInfo=ArticleInfoFlags(
                    bodyLen=-1,
                    title=True,
                    body=True,
                    url=True,
                    eventUri=True,
                    authors=True,
                    concepts=False,
                    categories=False,
                    image=True,
                    sentiment=True,
                    storyUri=False,
                ),
                sourceInfo=SourceInfoFlags(
                    title=True,
                    description=False,
                    location=False,
                    ranking=False,
                ),
            ),
        ):
            articles.append(article)

        logger.info(
            f"Fetched {len(articles)} articles for event {event_uri}"
        )
        return articles

    def get_source_uri(self, name):
        """Resolve a source name to its Event Registry URI."""
        return self.er.getNewsSourceUri(name)
