"""Tests for topic clustering."""

import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from apps.topics.clustering.embeddings import EmbeddingGenerator
from apps.topics.clustering.clusterer import ArticleClusterer
from apps.articles.models import Article


class TestEmbeddingGenerator:
    """Tests for the embedding generator."""

    @pytest.fixture
    def mock_model(self):
        """Mock sentence transformer model."""
        model = MagicMock()
        model.get_sentence_embedding_dimension.return_value = 384
        model.encode.return_value = np.random.rand(384)
        return model

    def test_generate_embedding(self, mock_model):
        """Test generating a single embedding."""
        with patch('apps.topics.clustering.embeddings.get_model', return_value=mock_model):
            generator = EmbeddingGenerator()
            embedding = generator.generate("Test text for embedding")

        assert embedding.shape == (384,)
        mock_model.encode.assert_called_once()

    def test_generate_empty_text(self, mock_model):
        """Test handling empty text."""
        with patch('apps.topics.clustering.embeddings.get_model', return_value=mock_model):
            generator = EmbeddingGenerator()
            embedding = generator.generate("")

        assert embedding.shape == (384,)
        assert np.all(embedding == 0)

    def test_generate_batch(self, mock_model):
        """Test generating embeddings for multiple texts."""
        mock_model.encode.return_value = np.random.rand(3, 384)

        with patch('apps.topics.clustering.embeddings.get_model', return_value=mock_model):
            generator = EmbeddingGenerator()
            embeddings = generator.generate_batch(["Text 1", "Text 2", "Text 3"])

        assert embeddings.shape == (3, 384)

    def test_prepare_article_text(self, mock_model, article_npr):
        """Test preparing article text for embedding."""
        with patch('apps.topics.clustering.embeddings.get_model', return_value=mock_model):
            generator = EmbeddingGenerator()
            text = generator.prepare_article_text(article_npr)

        assert article_npr.title in text
        assert article_npr.summary in text

    def test_prepare_article_text_no_summary(self, mock_model, source_npr):
        """Test preparing article text when no summary available."""
        article = Article.objects.create(
            source=source_npr,
            title='No Summary Article',
            url='https://npr.org/no-summary',
            content='This is the full content without a summary. ' * 20,
        )

        with patch('apps.topics.clustering.embeddings.get_model', return_value=mock_model):
            generator = EmbeddingGenerator()
            text = generator.prepare_article_text(article)

        assert article.title in text
        assert 'full content' in text


class TestArticleClusterer:
    """Tests for the article clusterer."""

    def test_cluster_not_enough_articles(self, db):
        """Test clustering with insufficient articles."""
        clusterer = ArticleClusterer(min_cluster_size=3)
        clusters = clusterer.cluster([])

        assert clusters == []

    def test_cluster_articles_without_embeddings(self, article_npr, article_fox):
        """Test that articles without embeddings are filtered."""
        # These articles don't have embeddings
        clusterer = ArticleClusterer(min_cluster_size=2)
        clusters = clusterer.cluster([article_npr, article_fox])

        assert clusters == []

    def test_cluster_with_embeddings(self, multiple_embedded_articles):
        """Test clustering articles with embeddings."""
        clusterer = ArticleClusterer(min_cluster_size=2, min_samples=1)
        clusters = clusterer.cluster(multiple_embedded_articles)

        # Should find some clusters (exact number depends on random embeddings)
        # At minimum, we verify the output format is correct
        for cluster in clusters:
            assert 'title' in cluster
            assert 'slug' in cluster
            assert 'keywords' in cluster
            assert 'articles' in cluster
            assert isinstance(cluster['keywords'], list)
            assert isinstance(cluster['articles'], list)

            for article_data in cluster['articles']:
                assert 'id' in article_data
                assert 'confidence' in article_data
                assert 'rank' in article_data

    def test_extract_keywords(self):
        """Test keyword extraction from titles."""
        clusterer = ArticleClusterer()

        titles = [
            "President announces new economic policy",
            "Economic policy changes affect markets",
            "New policy impacts economy",
        ]

        keywords = clusterer._extract_keywords(titles)

        assert len(keywords) > 0
        assert isinstance(keywords, list)
        # Common words should appear
        assert any('policy' in kw.lower() or 'economic' in kw.lower() for kw in keywords)

    def test_extract_keywords_empty(self):
        """Test keyword extraction with empty titles."""
        clusterer = ArticleClusterer()
        keywords = clusterer._extract_keywords([])

        assert keywords == []

    def test_generate_title(self):
        """Test topic title generation."""
        clusterer = ArticleClusterer()

        keywords = ['election', 'results', 'vote']
        titles = [
            "Election results show close race",
            "Vote count continues in key states",
            "Election 2024: Latest Updates",
        ]

        title = clusterer._generate_title(keywords, titles)

        assert len(title) > 0
        assert len(title) <= 100

    def test_cluster_output_format(self, multiple_embedded_articles):
        """Test that cluster output has correct format."""
        # Use smaller cluster size for test
        clusterer = ArticleClusterer(min_cluster_size=2, min_samples=1)

        # Make embeddings more similar within groups for predictable clustering
        for i, article in enumerate(multiple_embedded_articles[:3]):
            article.embedding = [0.1 + (i * 0.01)] * 384
            article.save()

        for i, article in enumerate(multiple_embedded_articles[3:]):
            article.embedding = [0.9 + (i * 0.01)] * 384
            article.save()

        clusters = clusterer.cluster(multiple_embedded_articles)

        for cluster in clusters:
            # Check slug is valid
            assert cluster['slug']
            assert ' ' not in cluster['slug']

            # Check articles list
            for article_data in cluster['articles']:
                assert 0 <= article_data['confidence'] <= 1
                assert article_data['rank'] >= 0


class TestClusteringIntegration:
    """Integration tests for the full clustering pipeline."""

    @pytest.mark.django_db(transaction=True)
    def test_full_clustering_pipeline(self, source_npr, source_fox):
        """Test the complete clustering workflow."""
        # Create articles with real-ish embeddings
        np.random.seed(42)  # For reproducibility

        # Group 1: Politics articles (similar embeddings)
        politics_base = np.random.rand(384)
        for i in range(4):
            Article.objects.create(
                source=source_npr if i % 2 == 0 else source_fox,
                title=f'Political News Story {i+1}',
                url=f'https://example.com/politics-{i+1}',
                content='Political content here.',
                status=Article.ProcessingStatus.EMBEDDED,
                embedding=(politics_base + np.random.rand(384) * 0.1).tolist(),
            )

        # Group 2: Sports articles (different embeddings)
        sports_base = np.random.rand(384)
        for i in range(4):
            Article.objects.create(
                source=source_npr if i % 2 == 0 else source_fox,
                title=f'Sports Game Update {i+1}',
                url=f'https://example.com/sports-{i+1}',
                content='Sports content here.',
                status=Article.ProcessingStatus.EMBEDDED,
                embedding=(sports_base + np.random.rand(384) * 0.1).tolist(),
            )

        articles = Article.objects.filter(status=Article.ProcessingStatus.EMBEDDED)
        clusterer = ArticleClusterer(min_cluster_size=3, min_samples=2)
        clusters = clusterer.cluster(articles)

        # Should find at least 1 cluster (might be 2 if embeddings separate well)
        assert len(clusters) >= 1

        # Each cluster should have multiple articles
        for cluster in clusters:
            assert len(cluster['articles']) >= 3
