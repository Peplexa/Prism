"""RSS feed scraper."""

import logging
from typing import List
from datetime import datetime

import feedparser
from dateutil import parser as date_parser

from .base import BaseScraper, ArticleData

logger = logging.getLogger(__name__)


class RSSScraper(BaseScraper):
    """Scraper for RSS/Atom feeds."""

    def discover_articles(self) -> List[ArticleData]:
        """Parse RSS feed and extract article metadata."""
        articles = []

        try:
            # Fetch and parse feed
            feed_content = self.fetch_page(self.source.discovery_url)
            if not feed_content:
                logger.error(f"Failed to fetch RSS feed for {self.source.name}")
                return articles

            feed = feedparser.parse(feed_content)

            if feed.bozo and feed.bozo_exception:
                logger.warning(
                    f"RSS parse warning for {self.source.name}: {feed.bozo_exception}"
                )

            # Process entries
            for entry in feed.entries:
                article = self._parse_entry(entry)
                if article and self.is_valid_article_url(article['url']):
                    articles.append(article)

            logger.info(
                f"Discovered {len(articles)} articles from {self.source.name} RSS feed"
            )

        except Exception as e:
            logger.error(f"Error scraping RSS for {self.source.name}: {e}")

        return articles

    def _parse_entry(self, entry) -> ArticleData | None:
        """Parse a single RSS entry into article dict."""
        # Get URL (try multiple fields)
        url = entry.get('link') or entry.get('id')
        if not url:
            return None

        url = self.normalize_url(url)

        # Get title
        title = entry.get('title', '').strip()
        if not title:
            return None

        # Get summary/description
        summary = ''
        if 'summary' in entry:
            summary = entry.summary
        elif 'description' in entry:
            summary = entry.description

        # Clean HTML from summary
        summary = self._strip_html(summary)[:500]

        # Get published date - try parsed time tuple first, then string fields
        published_at = None
        for field in ['published_parsed', 'updated_parsed', 'created_parsed']:
            time_tuple = getattr(entry, field, None)
            if time_tuple:
                try:
                    published_at = datetime(*time_tuple[:6])
                    break
                except (TypeError, ValueError):
                    continue

        if not published_at:
            for field in ['published', 'updated', 'created']:
                date_str = getattr(entry, field, None)
                if date_str:
                    try:
                        published_at = date_parser.parse(date_str)
                        break
                    except (ValueError, TypeError):
                        continue

        # Get author
        author = ''
        if 'author' in entry:
            author = entry.author
        elif 'authors' in entry and entry.authors:
            author = entry.authors[0].get('name', '')

        return ArticleData(
            url=url,
            title=title,
            summary=summary,
            published_at=published_at,
            author=author[:300] if author else '',
        )

    def _strip_html(self, text: str) -> str:
        """Remove HTML tags from text."""
        from bs4 import BeautifulSoup
        if not text:
            return ''
        soup = BeautifulSoup(text, 'lxml')
        return soup.get_text(separator=' ', strip=True)
