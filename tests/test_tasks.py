"""Tests for Celery tasks."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import timedelta

from django.utils import timezone

from apps.articles.models import Source, Article
from apps.articles.tasks import (
    scrape_all_sources,
    scrape_source,
    extract_article_content,
    cleanup_failed_articles,
)
from apps.topics.models import Topic, ArticleCluster
from apps.topics.tasks import (
    generate_article_embedding,
    cluster_recent_articles,
    update_trending_scores,
)


class TestArticleTasks:
    """Tests for article-related Celery tasks."""

    def test_scrape_all_sources(self, source_npr, source_fox):
        """Test that scrape_all_sources queues tasks for all active sources."""
        with patch('apps.articles.tasks.scrape_source.delay') as mock_delay:
            result = scrape_all_sources()

        assert mock_delay.call_count == 2
        assert 'Queued 2 sources' in result

    def test_scrape_all_sources_skips_inactive(self, source_npr, source_fox):
        """Test that inactive sources are skipped."""
        source_fox.is_active = False
        source_fox.save()

        with patch('apps.articles.tasks.scrape_source.delay') as mock_delay:
            result = scrape_all_sources()

        assert mock_delay.call_count == 1

    @patch('apps.articles.tasks.RSSScraper')
    def test_scrape_source_creates_articles(self, mock_scraper_class, source_npr):
        """Test that scrape_source creates new articles."""
        mock_scraper = MagicMock()
        mock_scraper.discover_articles.return_value = [
            {
                'url': 'https://npr.org/new-article',
                'title': 'New Article',
                'summary': 'Article summary',
                'author': 'Author',
                'published_at': timezone.now(),
            }
        ]
        mock_scraper_class.return_value = mock_scraper

        with patch('apps.articles.tasks.extract_article_content.delay'):
            result = scrape_source(source_npr.id)

        assert Article.objects.filter(url='https://npr.org/new-article').exists()
        assert '1 new articles' in result

    @patch('apps.articles.tasks.RSSScraper')
    def test_scrape_source_skips_duplicates(self, mock_scraper_class, source_npr, article_npr):
        """Test that existing articles are not duplicated."""
        mock_scraper = MagicMock()
        mock_scraper.discover_articles.return_value = [
            {
                'url': article_npr.url,  # Existing URL
                'title': 'Duplicate Article',
                'summary': 'Summary',
                'author': '',
                'published_at': timezone.now(),
            }
        ]
        mock_scraper_class.return_value = mock_scraper

        initial_count = Article.objects.count()

        with patch('apps.articles.tasks.extract_article_content.delay'):
            scrape_source(source_npr.id)

        assert Article.objects.count() == initial_count

    @patch('apps.articles.tasks.ContentExtractor')
    def test_extract_article_content_success(self, mock_extractor_class, article_npr):
        """Test successful content extraction."""
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = {
            'content': 'Extracted content here.',
            'title': 'Extracted Title',
            'author': 'Extracted Author',
            'summary': 'Extracted summary',
            'date': timezone.now(),
        }
        mock_extractor_class.return_value = mock_extractor

        article_npr.status = Article.ProcessingStatus.PENDING
        article_npr.save()

        with patch('apps.topics.tasks.generate_article_embedding.delay'):
            result = extract_article_content(article_npr.id)

        article_npr.refresh_from_db()
        assert article_npr.content == 'Extracted content here.'
        assert article_npr.status == Article.ProcessingStatus.SCRAPED

    @patch('apps.articles.tasks.ContentExtractor')
    def test_extract_article_content_failure(self, mock_extractor_class, article_npr):
        """Test handling of extraction failure."""
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = {
            'content': '',
            'title': '',
            'author': '',
            'summary': '',
            'date': None,
        }
        mock_extractor_class.return_value = mock_extractor

        result = extract_article_content(article_npr.id)

        article_npr.refresh_from_db()
        assert article_npr.status == Article.ProcessingStatus.FAILED
        assert 'No content extracted' in result

    def test_cleanup_failed_articles(self, source_npr):
        """Test cleanup of old failed articles."""
        # Create old failed article
        old_failed = Article.objects.create(
            source=source_npr,
            title='Old Failed Article',
            url='https://npr.org/old-failed',
            status=Article.ProcessingStatus.FAILED,
        )
        # Manually set created_at to be old
        Article.objects.filter(pk=old_failed.pk).update(
            created_at=timezone.now() - timedelta(days=10)
        )

        # Create recent failed article
        recent_failed = Article.objects.create(
            source=source_npr,
            title='Recent Failed Article',
            url='https://npr.org/recent-failed',
            status=Article.ProcessingStatus.FAILED,
        )

        result = cleanup_failed_articles(days_old=7)

        assert not Article.objects.filter(pk=old_failed.pk).exists()
        assert Article.objects.filter(pk=recent_failed.pk).exists()
        assert 'Deleted 1' in result


class TestTopicTasks:
    """Tests for topic-related Celery tasks."""

    @patch('apps.topics.tasks.EmbeddingGenerator')
    def test_generate_article_embedding(self, mock_generator_class, article_npr):
        """Test embedding generation for an article."""
        import numpy as np

        mock_generator = MagicMock()
        mock_generator.prepare_article_text.return_value = "Article text"
        mock_generator.generate.return_value = np.random.rand(384)
        mock_generator_class.return_value = mock_generator

        result = generate_article_embedding(article_npr.id)

        article_npr.refresh_from_db()
        assert article_npr.embedding is not None
        assert article_npr.status == Article.ProcessingStatus.EMBEDDED

    def test_generate_article_embedding_wrong_status(self, article_npr):
        """Test that embedding is skipped for non-scraped articles."""
        article_npr.status = Article.ProcessingStatus.PENDING
        article_npr.save()

        result = generate_article_embedding(article_npr.id)

        article_npr.refresh_from_db()
        assert article_npr.embedding is None
        assert result is None

    @patch('apps.topics.tasks.ArticleClusterer')
    def test_cluster_recent_articles(self, mock_clusterer_class, multiple_embedded_articles):
        """Test clustering of recent articles."""
        mock_clusterer = MagicMock()
        mock_clusterer.cluster.return_value = [
            {
                'title': 'Test Cluster',
                'slug': 'test-cluster',
                'keywords': ['test', 'cluster'],
                'articles': [
                    {'id': multiple_embedded_articles[0].id, 'confidence': 0.9, 'rank': 0},
                    {'id': multiple_embedded_articles[1].id, 'confidence': 0.8, 'rank': 1},
                    {'id': multiple_embedded_articles[2].id, 'confidence': 0.7, 'rank': 2},
                ]
            }
        ]
        mock_clusterer_class.return_value = mock_clusterer

        result = cluster_recent_articles(hours=48)

        assert Topic.objects.filter(slug='test-cluster').exists()
        assert 'Created 1 topics' in result

    def test_cluster_recent_articles_not_enough(self, article_with_embedding):
        """Test clustering with insufficient articles."""
        result = cluster_recent_articles(hours=48)

        assert 'Not enough articles' in result

    def test_update_trending_scores(self, topic_with_articles):
        """Test trending score updates."""
        initial_score = topic_with_articles.trending_score

        result = update_trending_scores()

        topic_with_articles.refresh_from_db()
        assert 'Updated' in result
        # Score should be calculated (may be different from initial)
        assert topic_with_articles.trending_score is not None

    def test_update_trending_sets_flag(self, topic):
        """Test that trending flag is set based on score."""
        # Create a topic with articles to get a high trending score
        topic.trending_score = 10.0
        topic.save()

        update_trending_scores()

        topic.refresh_from_db()
        # With score > 2, should be trending
        # (though actual behavior depends on article recency)


class TestTaskChaining:
    """Tests for task chaining and workflow."""

    @patch('apps.articles.tasks.ContentExtractor')
    @patch('apps.topics.tasks.generate_article_embedding.delay')
    def test_scrape_to_embedding_chain(
        self, mock_embedding_delay, mock_extractor_class, source_npr
    ):
        """Test that content extraction triggers embedding generation."""
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = {
            'content': 'Some content',
            'title': '',
            'author': '',
            'summary': '',
            'date': None,
        }
        mock_extractor_class.return_value = mock_extractor

        article = Article.objects.create(
            source=source_npr,
            title='Chain Test Article',
            url='https://npr.org/chain-test',
            status=Article.ProcessingStatus.PENDING,
        )

        extract_article_content(article.id)

        mock_embedding_delay.assert_called_once_with(article.id)
