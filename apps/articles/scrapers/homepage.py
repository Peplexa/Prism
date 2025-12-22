"""Homepage scraper for sites without RSS/sitemap."""

import logging
from typing import List
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import BaseScraper, ArticleData

logger = logging.getLogger(__name__)


class HomepageScraper(BaseScraper):
    """Scraper that extracts article links from homepage."""

    # Default selectors to try if none specified
    DEFAULT_SELECTORS = [
        'article a[href]',
        '.post a[href]',
        '.story a[href]',
        '.article-link',
        '.headline a[href]',
        'h2 a[href]',
        'h3 a[href]',
        '.card a[href]',
        '.news-item a[href]',
    ]

    def discover_articles(self) -> List[ArticleData]:
        """Scrape homepage for article links."""
        articles = []
        seen_urls = set()

        try:
            # Fetch homepage
            page_content = self.fetch_page(self.source.discovery_url)
            if not page_content:
                logger.error(f"Failed to fetch homepage for {self.source.name}")
                return articles

            soup = BeautifulSoup(page_content, 'lxml')

            # Determine which selector to use
            selectors = self._get_selectors()

            for selector in selectors:
                links = soup.select(selector)
                for link in links:
                    article = self._parse_link(link, soup)
                    if article and article.url not in seen_urls:
                        if self.is_valid_article_url(article.url):
                            articles.append(article)
                            seen_urls.add(article.url)

            logger.info(
                f"Discovered {len(articles)} articles from {self.source.name} homepage"
            )

        except Exception as e:
            logger.error(f"Error scraping homepage for {self.source.name}: {e}")

        return articles

    def _get_selectors(self) -> List[str]:
        """Get CSS selectors to use for this source."""
        if self.source.article_link_selector:
            return [self.source.article_link_selector]
        return self.DEFAULT_SELECTORS

    def _parse_link(self, link_elem, soup) -> ArticleData | None:
        """Parse an anchor element into ArticleData."""
        href = link_elem.get('href')
        if not href:
            return None

        url = urljoin(self.source.discovery_url, href)
        url = self.normalize_url(url)

        source_domain = urlparse(self.source.website_url).netloc
        url_domain = urlparse(url).netloc
        if source_domain not in url_domain and url_domain not in source_domain:
            return None

        title = self._extract_title(link_elem)
        if not title or len(title) < 10:
            return None

        summary = self._extract_summary(link_elem)
        return ArticleData(url=url, title=title, summary=summary)

    def _extract_title(self, link_elem) -> str:
        """Extract article title from link or its context."""
        # Try link text first
        title = link_elem.get_text(strip=True)
        if title and len(title) > 10:
            return title[:500]

        # Try title attribute
        title = link_elem.get('title', '')
        if title and len(title) > 10:
            return title[:500]

        # Look for heading in parent
        parent = link_elem.parent
        for _ in range(3):  # Check up to 3 levels up
            if parent is None:
                break
            heading = parent.find(['h1', 'h2', 'h3', 'h4'])
            if heading:
                title = heading.get_text(strip=True)
                if title and len(title) > 10:
                    return title[:500]
            parent = parent.parent

        return ''

    def _extract_summary(self, link_elem) -> str:
        """Try to extract a summary from nearby elements."""
        # Look for paragraph near the link
        parent = link_elem.parent
        for _ in range(3):
            if parent is None:
                break

            # Look for description/summary elements
            for selector in ['.summary', '.description', '.excerpt', 'p']:
                elem = parent.find(selector)
                if elem and elem != link_elem:
                    text = elem.get_text(strip=True)
                    if text and len(text) > 20:
                        return text[:500]

            parent = parent.parent

        return ''

    def is_valid_article_url(self, url: str) -> bool:
        """Additional homepage-specific URL validation."""
        if not super().is_valid_article_url(url):
            return False

        # Homepage links often include homepage itself
        parsed = urlparse(url)
        if parsed.path in ['', '/', '/index.html', '/index.php']:
            return False

        # Skip very short paths (likely section pages)
        path_parts = [p for p in parsed.path.split('/') if p]
        if len(path_parts) < 2:
            return False

        return True
