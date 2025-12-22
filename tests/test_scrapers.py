"""Tests for article scrapers."""

import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from apps.articles.scrapers.base import BaseScraper
from apps.articles.scrapers.rss import RSSScraper
from apps.articles.scrapers.sitemap import SitemapScraper
from apps.articles.scrapers.homepage import HomepageScraper
from apps.articles.scrapers.content import ContentExtractor


class TestBaseScraper:
    """Tests for the BaseScraper base class."""

    def test_normalize_url(self, source_npr):
        """Test URL normalization."""
        scraper = RSSScraper(source_npr)

        # Remove trailing slash
        assert scraper.normalize_url('https://example.com/path/') == 'https://example.com/path'

        # Remove fragment
        assert scraper.normalize_url('https://example.com/path#section') == 'https://example.com/path'

        # Handle query strings
        assert scraper.normalize_url('https://example.com/path?q=1') == 'https://example.com/path?q=1'

    def test_is_valid_article_url(self, source_npr):
        """Test article URL validation."""
        scraper = RSSScraper(source_npr)

        # Valid article URLs
        assert scraper.is_valid_article_url('https://example.com/2024/01/article-title')
        assert scraper.is_valid_article_url('https://example.com/news/story-123')

        # Invalid URLs (category pages, etc.)
        assert not scraper.is_valid_article_url('https://example.com/category/politics')
        assert not scraper.is_valid_article_url('https://example.com/tag/election')
        assert not scraper.is_valid_article_url('https://example.com/author/john')
        assert not scraper.is_valid_article_url('https://example.com/feed.xml')
        assert not scraper.is_valid_article_url('https://example.com/search?q=test')

    def test_create_session(self, source_npr):
        """Test session creation with retry logic."""
        scraper = RSSScraper(source_npr)

        assert scraper.session is not None
        assert 'User-Agent' in scraper.session.headers


class TestRSSScraper:
    """Tests for the RSS scraper."""

    @pytest.fixture
    def sample_rss_feed(self):
        """Sample RSS feed content."""
        return '''<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <title>Test Feed</title>
                <item>
                    <title>Test Article 1</title>
                    <link>https://example.com/article-1</link>
                    <description>This is the first test article.</description>
                    <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
                    <author>John Doe</author>
                </item>
                <item>
                    <title>Test Article 2</title>
                    <link>https://example.com/article-2</link>
                    <description><![CDATA[<p>HTML content here</p>]]></description>
                    <pubDate>Tue, 02 Jan 2024 12:00:00 GMT</pubDate>
                </item>
            </channel>
        </rss>'''

    def test_discover_articles(self, source_npr, sample_rss_feed):
        """Test RSS feed parsing."""
        scraper = RSSScraper(source_npr)

        with patch.object(scraper, 'fetch_page', return_value=sample_rss_feed):
            articles = scraper.discover_articles()

        assert len(articles) == 2
        assert articles[0]['title'] == 'Test Article 1'
        assert articles[0]['url'] == 'https://example.com/article-1'
        assert articles[0]['summary'] == 'This is the first test article.'
        assert articles[0]['author'] == 'John Doe'
        assert articles[0]['published_at'] is not None

    def test_strip_html_from_summary(self, source_npr, sample_rss_feed):
        """Test that HTML is stripped from summaries."""
        scraper = RSSScraper(source_npr)

        with patch.object(scraper, 'fetch_page', return_value=sample_rss_feed):
            articles = scraper.discover_articles()

        # Second article has HTML in description
        assert '<p>' not in articles[1]['summary']
        assert 'HTML content here' in articles[1]['summary']

    def test_handles_missing_fields(self, source_npr):
        """Test handling of RSS entries with missing fields."""
        minimal_feed = '''<?xml version="1.0"?>
        <rss version="2.0">
            <channel>
                <item>
                    <title>Minimal Article</title>
                    <link>https://example.com/minimal</link>
                </item>
            </channel>
        </rss>'''

        scraper = RSSScraper(source_npr)

        with patch.object(scraper, 'fetch_page', return_value=minimal_feed):
            articles = scraper.discover_articles()

        assert len(articles) == 1
        assert articles[0]['title'] == 'Minimal Article'
        assert articles[0]['summary'] == ''
        assert articles[0]['author'] == ''
        assert articles[0]['published_at'] is None

    def test_handles_fetch_failure(self, source_npr):
        """Test handling when feed fetch fails."""
        scraper = RSSScraper(source_npr)

        with patch.object(scraper, 'fetch_page', return_value=None):
            articles = scraper.discover_articles()

        assert articles == []


class TestSitemapScraper:
    """Tests for the Sitemap scraper."""

    @pytest.fixture
    def sample_sitemap(self):
        """Sample sitemap XML content with recent dates."""
        from datetime import datetime, timedelta
        # Use dates within the max_age_days window
        date1 = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%dT12:00:00Z')
        date2 = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%dT12:00:00Z')
        return f'''<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url>
                <loc>https://example.com/news/article-1</loc>
                <lastmod>{date1}</lastmod>
            </url>
            <url>
                <loc>https://example.com/news/article-2</loc>
                <lastmod>{date2}</lastmod>
            </url>
        </urlset>'''

    @pytest.fixture
    def sample_sitemap_index(self):
        """Sample sitemap index XML."""
        return '''<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap>
                <loc>https://example.com/sitemap-news.xml</loc>
                <lastmod>2024-01-02T12:00:00Z</lastmod>
            </sitemap>
        </sitemapindex>'''

    def test_discover_articles(self, source_reuters, sample_sitemap):
        """Test sitemap parsing."""
        scraper = SitemapScraper(source_reuters, max_age_days=30)

        with patch.object(scraper, 'fetch_page', return_value=sample_sitemap):
            articles = scraper.discover_articles()

        assert len(articles) == 2
        assert articles[0]['url'] == 'https://example.com/news/article-1'
        assert articles[0]['published_at'] is not None

    def test_filters_old_articles(self, source_reuters):
        """Test that old articles are filtered out."""
        old_sitemap = '''<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url>
                <loc>https://example.com/old-article</loc>
                <lastmod>2020-01-01T12:00:00Z</lastmod>
            </url>
        </urlset>'''

        scraper = SitemapScraper(source_reuters, max_age_days=7)

        with patch.object(scraper, 'fetch_page', return_value=old_sitemap):
            articles = scraper.discover_articles()

        assert len(articles) == 0


class TestHomepageScraper:
    """Tests for the Homepage scraper."""

    @pytest.fixture
    def sample_homepage(self):
        """Sample homepage HTML."""
        return '''
        <html>
        <body>
            <article>
                <h2><a href="/news/article-1">First Article Title</a></h2>
                <p class="summary">Summary of the first article.</p>
            </article>
            <article>
                <h2><a href="/news/article-2">Second Article Title</a></h2>
                <p class="summary">Summary of the second article.</p>
            </article>
            <nav>
                <a href="/category/politics">Politics</a>
            </nav>
        </body>
        </html>'''

    def test_discover_articles(self, source_fox, sample_homepage):
        """Test homepage scraping."""
        scraper = HomepageScraper(source_fox)

        with patch.object(scraper, 'fetch_page', return_value=sample_homepage):
            articles = scraper.discover_articles()

        # Should find 2 article links, skip category link
        assert len(articles) == 2
        assert 'article-1' in articles[0]['url']
        assert articles[0]['title'] == 'First Article Title'

    def test_filters_external_links(self, source_fox):
        """Test that external links are filtered out."""
        html_with_external = '''
        <html>
        <body>
            <article>
                <a href="https://external-site.com/article">External Article</a>
            </article>
            <article>
                <a href="/news/internal-article">Internal Article</a>
            </article>
        </body>
        </html>'''

        scraper = HomepageScraper(source_fox)

        with patch.object(scraper, 'fetch_page', return_value=html_with_external):
            articles = scraper.discover_articles()

        # Should only find the internal link
        assert len(articles) == 1
        assert 'internal-article' in articles[0]['url']

    def test_uses_custom_selector(self, source_fox, sample_homepage):
        """Test that custom CSS selector is used when provided."""
        source_fox.article_link_selector = 'article h2 a'
        source_fox.save()

        scraper = HomepageScraper(source_fox)

        with patch.object(scraper, 'fetch_page', return_value=sample_homepage):
            articles = scraper.discover_articles()

        assert len(articles) == 2


class TestContentExtractor:
    """Tests for the content extractor."""

    def test_extract_content(self):
        """Test content extraction from URL."""
        extractor = ContentExtractor()

        sample_html = '''
        <html>
        <head><title>Test Article</title></head>
        <body>
            <article>
                <h1>Test Article Title</h1>
                <p>This is the main content of the article.</p>
                <p>It has multiple paragraphs with important information.</p>
            </article>
        </body>
        </html>'''

        with patch('trafilatura.fetch_url', return_value=sample_html):
            with patch('trafilatura.extract', return_value='This is the main content.'):
                with patch('trafilatura.extract_metadata') as mock_meta:
                    mock_meta.return_value = Mock(
                        title='Test Article Title',
                        author='Test Author',
                        description='Test description',
                        date='2024-01-01',
                    )
                    result = extractor.extract('https://example.com/article')

        assert result['content'] == 'This is the main content.'
        assert result['title'] == 'Test Article Title'
        assert result['author'] == 'Test Author'

    def test_generate_summary(self):
        """Test summary generation from content."""
        extractor = ContentExtractor()

        content = "This is the first sentence. This is the second sentence. This is the third sentence that is much longer and contains more information about the topic."

        summary = extractor._generate_summary(content, max_length=100)

        assert len(summary) <= 100
        assert summary.endswith('.')

    def test_handles_empty_content(self):
        """Test handling of empty content."""
        extractor = ContentExtractor()

        with patch('trafilatura.fetch_url', return_value=None):
            result = extractor.extract('https://example.com/404')

        assert result['content'] == ''
        assert result['title'] == ''
