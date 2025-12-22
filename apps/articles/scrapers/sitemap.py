"""Sitemap XML scraper."""

import logging
from typing import List
from datetime import datetime, timedelta
from xml.etree import ElementTree

from dateutil import parser as date_parser

from .base import BaseScraper, ArticleData

logger = logging.getLogger(__name__)


class SitemapScraper(BaseScraper):
    """Scraper for sitemap.xml files."""

    # XML namespaces commonly used in sitemaps
    NAMESPACES = {
        'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
        'news': 'http://www.google.com/schemas/sitemap-news/0.9',
    }

    def __init__(self, source, max_age_days: int = 7):
        super().__init__(source)
        self.max_age_days = max_age_days
        self.cutoff_date = datetime.now() - timedelta(days=max_age_days)

    def discover_articles(self) -> List[ArticleData]:
        """Parse sitemap and extract recent article URLs."""
        articles = []

        try:
            # Fetch sitemap
            sitemap_content = self.fetch_page(self.source.discovery_url)
            if not sitemap_content:
                logger.error(f"Failed to fetch sitemap for {self.source.name}")
                return articles

            # Parse XML
            root = ElementTree.fromstring(sitemap_content)

            # Check if this is a sitemap index (contains other sitemaps)
            if self._is_sitemap_index(root):
                articles = self._parse_sitemap_index(root)
            else:
                articles = self._parse_sitemap(root)

            logger.info(
                f"Discovered {len(articles)} articles from {self.source.name} sitemap"
            )

        except ElementTree.ParseError as e:
            logger.error(f"XML parse error for {self.source.name}: {e}")
        except Exception as e:
            logger.error(f"Error scraping sitemap for {self.source.name}: {e}")

        return articles

    def _is_sitemap_index(self, root) -> bool:
        """Check if root element is a sitemap index."""
        return 'sitemapindex' in root.tag.lower()

    def _parse_sitemap_index(self, root) -> List[ArticleData]:
        """Parse sitemap index and fetch child sitemaps."""
        articles = []

        # Find all sitemap URLs
        for sitemap in root.findall('.//sm:sitemap', self.NAMESPACES):
            loc = sitemap.find('sm:loc', self.NAMESPACES)
            if loc is not None and loc.text:
                # Only fetch news sitemaps or recent sitemaps
                sitemap_url = loc.text
                if self._should_fetch_sitemap(sitemap_url, sitemap):
                    child_articles = self._fetch_child_sitemap(sitemap_url)
                    articles.extend(child_articles)

        return articles

    def _should_fetch_sitemap(self, url: str, sitemap_elem) -> bool:
        """Determine if we should fetch this sitemap based on URL and lastmod."""
        # Prefer news sitemaps
        if 'news' in url.lower():
            return True

        # Check lastmod date
        lastmod = sitemap_elem.find('sm:lastmod', self.NAMESPACES)
        if lastmod is not None and lastmod.text:
            try:
                mod_date = date_parser.parse(lastmod.text)
                if mod_date.replace(tzinfo=None) < self.cutoff_date:
                    return False
            except (ValueError, TypeError):
                pass

        return True

    def _fetch_child_sitemap(self, url: str) -> List[ArticleData]:
        """Fetch and parse a child sitemap."""
        content = self.fetch_page(url)
        if not content:
            return []

        try:
            root = ElementTree.fromstring(content)
            return self._parse_sitemap(root)
        except ElementTree.ParseError:
            return []

    def _parse_sitemap(self, root) -> List[ArticleData]:
        """Parse a sitemap and extract article URLs."""
        articles = []

        for url_elem in root.findall('.//sm:url', self.NAMESPACES):
            article = self._parse_url_element(url_elem)
            if article and self.is_valid_article_url(article.url):
                if article.published_at:
                    pub_date = article.published_at
                    if hasattr(pub_date, 'replace'):
                        pub_date = pub_date.replace(tzinfo=None)
                    if pub_date < self.cutoff_date:
                        continue
                articles.append(article)

        return articles

    def _parse_url_element(self, url_elem) -> ArticleData | None:
        """Parse a single URL element from sitemap."""
        loc = url_elem.find('sm:loc', self.NAMESPACES)
        if loc is None or not loc.text:
            return None

        url = self.normalize_url(loc.text)

        published_at = None
        lastmod = url_elem.find('sm:lastmod', self.NAMESPACES)
        if lastmod is not None and lastmod.text:
            try:
                published_at = date_parser.parse(lastmod.text)
            except (ValueError, TypeError):
                pass

        title = ''
        news_elem = url_elem.find('.//news:news', self.NAMESPACES)
        if news_elem is not None:
            title_elem = news_elem.find('news:title', self.NAMESPACES)
            if title_elem is not None:
                title = title_elem.text or ''

            pub_date_elem = news_elem.find('news:publication_date', self.NAMESPACES)
            if pub_date_elem is not None and pub_date_elem.text:
                try:
                    published_at = date_parser.parse(pub_date_elem.text)
                except (ValueError, TypeError):
                    pass

        return ArticleData(url=url, title=title, published_at=published_at)
