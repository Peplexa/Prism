"""Tests for database models."""

import pytest
from datetime import timedelta
from django.utils import timezone
from django.db import IntegrityError

from apps.articles.models import Source, Article
from apps.topics.models import Topic, ArticleCluster


class TestSourceModel:
    """Tests for the Source model."""

    def test_create_source(self, db):
        """Test creating a basic source."""
        source = Source.objects.create(
            name='Test Source',
            slug='test-source',
            website_url='https://example.com',
            event_registry_uri='example.com',
        )

        assert source.id is not None
        assert source.name == 'Test Source'
        assert source.slug == 'test-source'
        assert source.is_active is True
        assert source.created_at is not None

    def test_source_slug_auto_generation(self, db):
        """Test that slug is auto-generated from name."""
        source = Source.objects.create(
            name='The New York Times',
            website_url='https://nytimes.com',
            event_registry_uri='nytimes.com',
        )

        assert source.slug == 'the-new-york-times'

    def test_source_slug_unique(self, db):
        """Test that slug must be unique."""
        Source.objects.create(
            name='Test Source',
            slug='unique-slug',
            website_url='https://example.com',
            event_registry_uri='example.com',
        )

        with pytest.raises(IntegrityError):
            Source.objects.create(
                name='Another Source',
                slug='unique-slug',
                website_url='https://another.com',
                event_registry_uri='another.com',
            )

    def test_source_str(self, source_npr):
        """Test source string representation."""
        assert str(source_npr) == 'NPR'

    def test_source_active_default(self, db):
        """Test source is active by default."""
        source = Source.objects.create(
            name='Active Source',
            slug='active-source',
            website_url='https://active.com',
            event_registry_uri='active.com',
        )
        assert source.is_active is True


class TestArticleModel:
    """Tests for the Article model."""

    def test_create_article(self, source_npr):
        """Test creating a basic article."""
        article = Article.objects.create(
            source=source_npr,
            title='Test Article Title',
            url='https://npr.org/test-article',
        )

        assert article.id is not None
        assert article.source == source_npr
        assert article.status == Article.ProcessingStatus.PENDING
        assert article.word_count == 0

    def test_article_slug_auto_generation(self, source_npr):
        """Test that slug is auto-generated from title."""
        article = Article.objects.create(
            source=source_npr,
            title='This Is A Test Article Title',
            url='https://npr.org/test-slug',
        )

        assert article.slug == 'this-is-a-test-article-title'

    def test_article_word_count_auto_calculation(self, source_npr):
        """Test that word count is calculated from content."""
        content = 'This is test content. ' * 100  # 400 words
        article = Article.objects.create(
            source=source_npr,
            title='Word Count Test',
            url='https://npr.org/word-count',
            content=content,
        )

        assert article.word_count == 400

    def test_article_url_unique(self, source_npr):
        """Test that article URL must be unique."""
        Article.objects.create(
            source=source_npr,
            title='First Article',
            url='https://npr.org/unique-url',
        )

        with pytest.raises(IntegrityError):
            Article.objects.create(
                source=source_npr,
                title='Second Article',
                url='https://npr.org/unique-url',
            )

    def test_article_str(self, article_npr):
        """Test article string representation."""
        assert 'NPR' in str(article_npr)
        assert 'Test Article' in str(article_npr)

    def test_article_status_transitions(self, article_npr):
        """Test article status can be updated."""
        assert article_npr.status == Article.ProcessingStatus.COMPLETE

        article_npr.status = Article.ProcessingStatus.FAILED
        article_npr.save()
        article_npr.refresh_from_db()

        assert article_npr.status == Article.ProcessingStatus.FAILED

    def test_article_ordering(self, source_npr):
        """Test articles are ordered by published_at descending."""
        now = timezone.now()

        article1 = Article.objects.create(
            source=source_npr,
            title='Older Article',
            url='https://npr.org/older',
            published_at=now - timedelta(days=2),
        )
        article2 = Article.objects.create(
            source=source_npr,
            title='Newer Article',
            url='https://npr.org/newer',
            published_at=now - timedelta(days=1),
        )

        articles = list(Article.objects.all())
        assert articles[0] == article2
        assert articles[1] == article1


class TestWireDetection:
    """Tests for wire service detection utility."""

    def test_ap_byline_on_non_wire_source(self):
        from apps.articles.utils import is_wire_copy
        assert is_wire_copy("Associated Press", "foxnews.com") is True

    def test_ap_byline_on_ap_source(self):
        from apps.articles.utils import is_wire_copy
        assert is_wire_copy("Associated Press", "apnews.com") is False

    def test_reuters_byline_on_non_wire_source(self):
        from apps.articles.utils import is_wire_copy
        assert is_wire_copy("Reuters", "cnn.com") is True

    def test_reuters_byline_on_reuters_source(self):
        from apps.articles.utils import is_wire_copy
        assert is_wire_copy("Reuters", "reuters.com") is False

    def test_afp_byline(self):
        from apps.articles.utils import is_wire_copy
        assert is_wire_copy("Agence France-Presse", "bbc.com") is True

    def test_normal_author(self):
        from apps.articles.utils import is_wire_copy
        assert is_wire_copy("John Smith", "cnn.com") is False

    def test_empty_author(self):
        from apps.articles.utils import is_wire_copy
        assert is_wire_copy("", "cnn.com") is False

    def test_ap_in_mixed_byline(self):
        from apps.articles.utils import is_wire_copy
        assert is_wire_copy("John Smith, Associated Press", "nytimes.com") is True

    def test_is_wire_content_field_default(self, source_npr):
        """Test that is_wire_content defaults to False."""
        article = Article.objects.create(
            source=source_npr,
            title='Regular Article',
            url='https://npr.org/regular',
        )
        assert article.is_wire_content is False

    def test_is_wire_content_field_set(self, source_fox):
        """Test that is_wire_content can be set to True."""
        article = Article.objects.create(
            source=source_fox,
            title='AP Wire on Fox',
            url='https://foxnews.com/ap-wire',
            author='Associated Press',
            is_wire_content=True,
        )
        article.refresh_from_db()
        assert article.is_wire_content is True


class TestTopicModel:
    """Tests for the Topic model."""

    def test_create_topic(self, db):
        """Test creating a basic topic."""
        topic = Topic.objects.create(
            title='Test Topic',
            slug='test-topic',
        )

        assert topic.id is not None
        assert topic.article_count == 0
        assert topic.source_count == 0
        assert topic.trending_score == 0.0
        assert topic.is_trending is False

    def test_topic_slug_auto_generation(self, db):
        """Test that slug is auto-generated from title."""
        topic = Topic.objects.create(
            title='Breaking News About Elections',
        )

        assert topic.slug == 'breaking-news-about-elections'

    def test_topic_update_metrics(self, topic_with_articles):
        """Test topic metrics are calculated correctly."""
        assert topic_with_articles.article_count == 2
        assert topic_with_articles.source_count == 2
        assert topic_with_articles.first_article_at is not None
        assert topic_with_articles.last_article_at is not None

    def test_topic_str(self, topic):
        """Test topic string representation."""
        assert str(topic) == 'Test Topic'

    def test_topic_keywords_json(self, db):
        """Test keywords are stored as JSON."""
        keywords = ['politics', 'election', '2024']
        topic = Topic.objects.create(
            title='Politics Topic',
            slug='politics-topic',
            keywords=keywords,
        )

        topic.refresh_from_db()
        assert topic.keywords == keywords


class TestArticleClusterModel:
    """Tests for the ArticleCluster model."""

    def test_create_cluster(self, topic, article_npr):
        """Test creating an article cluster."""
        cluster = ArticleCluster.objects.create(
            topic=topic,
            article=article_npr,
            confidence_score=0.95,
            cluster_rank=0,
        )

        assert cluster.id is not None
        assert cluster.topic == topic
        assert cluster.article == article_npr

    def test_cluster_unique_article(self, topic, article_npr):
        """Test that an article can only belong to one cluster."""
        ArticleCluster.objects.create(
            topic=topic,
            article=article_npr,
        )

        # Creating another cluster for the same article should fail
        new_topic = Topic.objects.create(title='Another Topic', slug='another-topic')

        with pytest.raises(IntegrityError):
            ArticleCluster.objects.create(
                topic=new_topic,
                article=article_npr,
            )

    def test_cluster_ordering(self, topic, source_npr):
        """Test clusters are ordered by confidence score descending."""
        article1 = Article.objects.create(
            source=source_npr,
            title='Low Confidence',
            url='https://npr.org/low',
        )
        article2 = Article.objects.create(
            source=source_npr,
            title='High Confidence',
            url='https://npr.org/high',
        )

        ArticleCluster.objects.create(topic=topic, article=article1, confidence_score=0.5)
        ArticleCluster.objects.create(topic=topic, article=article2, confidence_score=0.9)

        clusters = list(topic.clusters.all())
        assert clusters[0].confidence_score == 0.9
        assert clusters[1].confidence_score == 0.5

    def test_cluster_str(self, topic, article_npr):
        """Test cluster string representation."""
        cluster = ArticleCluster.objects.create(
            topic=topic,
            article=article_npr,
        )

        assert 'Test Article' in str(cluster)
        assert 'Test Topic' in str(cluster)
