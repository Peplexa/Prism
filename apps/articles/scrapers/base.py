"""Base scraper interface."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
from datetime import datetime

import requests


from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


@dataclass
class ArticleData:
    """Article metadata from scraping."""
    url: str
    title: str
    summary: str = ''
    published_at: Optional[datetime] = None
    author: str = ''


class BaseScraper(ABC):
    """Abstract base class for all scrapers."""

    USER_AGENT = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )

    def __init__(self, source):
        self.source = source
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic."""
        session = requests.Session()

        # Configure retries
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Set headers
        session.headers.update({
            'User-Agent': self.USER_AGENT,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
        })

        return session

    @abstractmethod
    def discover_articles(self) -> List[ArticleData]:
        """Discover article URLs from the source."""
        pass

    def fetch_page(self, url: str, timeout: int = 30) -> str | None:
        """Fetch a page, returning None on failure."""
        try:
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def normalize_url(self, url: str) -> str:
        """Normalize URL by removing fragments and trailing slashes."""
        from urllib.parse import urlparse, urlunparse

        parsed = urlparse(url)
        # Remove fragment, normalize path
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path.rstrip('/'),
            parsed.params,
            parsed.query,
            ''  # Remove fragment
        ))
        return normalized

    def is_valid_article_url(self, url: str) -> bool:
        """Check if URL looks like an article (not a category, tag, etc.)"""
        # Skip common non-article patterns
        skip_patterns = [
            '/tag/', '/category/', '/author/', '/page/',
            '/search', '/login', '/register', '/contact',
            '/about', '/privacy', '/terms', '/feed',
            '.xml', '.rss', '.json', '.pdf',
        ]
        url_lower = url.lower()
        return not any(pattern in url_lower for pattern in skip_patterns)
