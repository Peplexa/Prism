"""Tests for web views and API endpoints."""

import pytest
from django.urls import reverse
from django.test import Client

from apps.articles.models import Article
from apps.topics.models import Topic


@pytest.fixture
def client():
    """Django test client."""
    return Client()


class TestWebViews:
    """Tests for the web frontend views."""

    def test_home_view(self, client, db):
        """Test home page loads successfully."""
        response = client.get(reverse('web:home'))

        assert response.status_code == 200
        assert b'Prism' in response.content
        assert b'Search' in response.content or b'search' in response.content

    def test_home_view_with_trending(self, client, topic):
        """Test home page shows trending topics."""
        response = client.get(reverse('web:home'))

        assert response.status_code == 200
        assert topic.title.encode() in response.content

    def test_ideas_view(self, client, db):
        """Test ideas page loads successfully."""
        response = client.get(reverse('web:ideas'))

        assert response.status_code == 200

    def test_ideas_view_with_topics(self, client, topic_with_articles):
        """Test ideas page shows topics."""
        response = client.get(reverse('web:ideas'))

        assert response.status_code == 200
        assert topic_with_articles.title.encode() in response.content

    def test_topic_detail_view(self, client, topic_with_articles):
        """Test topic detail page."""
        response = client.get(
            reverse('web:topic-detail', kwargs={'slug': topic_with_articles.slug})
        )

        assert response.status_code == 200
        assert topic_with_articles.title.encode() in response.content
        # Should show article count
        assert b'2' in response.content  # 2 articles in fixture

    def test_topic_detail_404(self, client, db):
        """Test topic detail returns 404 for non-existent topic."""
        response = client.get(
            reverse('web:topic-detail', kwargs={'slug': 'non-existent-topic'})
        )

        assert response.status_code == 404

    def test_article_detail_view(self, client, article_npr):
        """Test article detail page."""
        response = client.get(
            reverse('web:article-detail', kwargs={'pk': article_npr.pk})
        )

        assert response.status_code == 200
        assert article_npr.title.encode() in response.content
        assert article_npr.source.name.encode() in response.content

    def test_article_detail_404(self, client, db):
        """Test article detail returns 404 for non-existent article."""
        response = client.get(
            reverse('web:article-detail', kwargs={'pk': 99999})
        )

        assert response.status_code == 404


class TestHTMXPartials:
    """Tests for HTMX partial views."""

    def test_search_results_empty_query(self, client, db):
        """Test search with empty query returns empty response."""
        response = client.get(reverse('web:htmx-search'), {'q': ''})

        assert response.status_code == 200
        assert response.content == b''

    def test_search_results_short_query(self, client, db):
        """Test search with short query returns empty response."""
        response = client.get(reverse('web:htmx-search'), {'q': 'a'})

        assert response.status_code == 200
        assert response.content == b''

    def test_search_results_finds_topics(self, client, topic):
        """Test search finds matching topics."""
        response = client.get(reverse('web:htmx-search'), {'q': 'Test'})

        assert response.status_code == 200
        assert topic.title.encode() in response.content

    def test_search_results_no_matches(self, client, topic):
        """Test search with no matches."""
        response = client.get(reverse('web:htmx-search'), {'q': 'xyznonexistent'})

        assert response.status_code == 200
        assert b'No topics found' in response.content

    def test_search_detects_url(self, client, db):
        """Test search detects URL input."""
        response = client.get(
            reverse('web:htmx-search'),
            {'q': 'https://example.com/article'}
        )

        assert response.status_code == 200
        assert b'Analyze' in response.content

    def test_topic_list_partial(self, client, topic):
        """Test topic list partial."""
        response = client.get(reverse('web:htmx-topics'))

        assert response.status_code == 200


class TestAPIEndpoints:
    """Tests for REST API endpoints."""

    def test_source_list(self, client, source_npr, source_fox):
        """Test sources API endpoint."""
        response = client.get('/api/v1/articles/sources/')

        assert response.status_code == 200
        data = response.json()
        assert data['count'] == 2
        assert len(data['results']) == 2

    def test_article_list(self, client, article_npr, article_fox):
        """Test articles API endpoint."""
        response = client.get('/api/v1/articles/')

        assert response.status_code == 200
        data = response.json()
        assert data['count'] == 2

    def test_article_list_filter_by_source(self, client, article_npr, article_fox, source_npr):
        """Test filtering articles by source."""
        response = client.get(f'/api/v1/articles/?source={source_npr.id}')

        assert response.status_code == 200
        data = response.json()
        assert data['count'] == 1
        assert data['results'][0]['source'] == source_npr.id

    def test_article_list_filter_by_status(self, client, article_npr, source_npr):
        """Test filtering articles by status."""
        # Create an article with different status
        Article.objects.create(
            source=source_npr,
            title='Pending Article',
            url='https://npr.org/pending',
            status=Article.ProcessingStatus.PENDING,
        )

        response = client.get('/api/v1/articles/?status=scraped')

        assert response.status_code == 200
        data = response.json()
        assert data['count'] == 1

    def test_article_detail(self, client, article_npr):
        """Test article detail API endpoint."""
        response = client.get(f'/api/v1/articles/{article_npr.pk}/')

        assert response.status_code == 200
        data = response.json()
        assert data['title'] == article_npr.title
        assert data['source']['name'] == article_npr.source.name

    def test_topic_list(self, client, topic_with_articles):
        """Test topics API endpoint."""
        response = client.get('/api/v1/topics/')

        assert response.status_code == 200
        data = response.json()
        assert len(data['results']) >= 1

    def test_topic_list_search(self, client, topic_with_articles):
        """Test topic search."""
        response = client.get('/api/v1/topics/?search=Test')

        assert response.status_code == 200
        data = response.json()
        assert len(data['results']) >= 1

    def test_topic_trending(self, client, topic):
        """Test trending topics endpoint."""
        response = client.get('/api/v1/topics/trending/')

        assert response.status_code == 200
        data = response.json()
        # topic fixture has is_trending=True
        assert len(data) >= 1

    def test_topic_detail(self, client, topic_with_articles):
        """Test topic detail API endpoint."""
        response = client.get(f'/api/v1/topics/{topic_with_articles.slug}/')

        assert response.status_code == 200
        data = response.json()
        assert data['title'] == topic_with_articles.title
        assert data['article_count'] == 2
        assert len(data['articles']) == 2

    def test_topic_detail_404(self, client, db):
        """Test topic detail returns 404 for non-existent topic."""
        response = client.get('/api/v1/topics/non-existent-slug/')

        assert response.status_code == 404


class TestPagination:
    """Tests for API pagination."""

    def test_article_pagination(self, client, source_npr):
        """Test article list pagination."""
        # Create 25 articles
        for i in range(25):
            Article.objects.create(
                source=source_npr,
                title=f'Article {i}',
                url=f'https://npr.org/article-{i}',
            )

        response = client.get('/api/v1/articles/')
        data = response.json()

        assert data['count'] == 25
        assert len(data['results']) == 20  # Default page size
        assert data['next'] is not None

    def test_article_pagination_page_2(self, client, source_npr):
        """Test second page of articles."""
        for i in range(25):
            Article.objects.create(
                source=source_npr,
                title=f'Article {i}',
                url=f'https://npr.org/article-{i}',
            )

        response = client.get('/api/v1/articles/?page=2')
        data = response.json()

        assert len(data['results']) == 5  # Remaining articles
        assert data['previous'] is not None
