"""Tests for web views and API endpoints."""

import pytest
from django.urls import reverse
from django.test import Client
from django.utils import timezone

from apps.articles.models import Article, Source
from apps.topics.models import Topic, ArticleCluster
from apps.consensus.models import (
    ConsensusPool, ConsensusNugget, OmissionScore, NuggetJudgment,
)


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
        assert data['results'][0]['source']['id'] == source_npr.id

    def test_article_list_filter_by_status(self, client, article_npr, source_npr):
        """Test filtering articles by status."""
        # Create an article with different status
        Article.objects.create(
            source=source_npr,
            title='Pending Article',
            url='https://npr.org/pending',
            status=Article.ProcessingStatus.PENDING,
        )

        response = client.get('/api/v1/articles/?status=complete')

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


class TestTopicReportView:
    """Tests for the Media Comparison Report view."""

    def test_report_view_renders(self, client, topic_with_articles):
        """Report page should render for a topic with articles."""
        url = f'/topic/{topic_with_articles.slug}/'
        response = client.get(url)
        assert response.status_code == 200
        assert 'Media Comparison Report' in response.content.decode()

    def test_report_view_404_for_missing_topic(self, client, db):
        """Report page should 404 for non-existent slug."""
        response = client.get('/topic/nonexistent-slug/')
        assert response.status_code == 404

    def test_report_view_shows_source_coverage(self, client, topic_with_articles):
        """Report page should show source coverage section with covering sources."""
        # Need a complete pool for the full report to render
        ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
            nugget_count=5, vital_nugget_count=2,
            built_at=timezone.now(),
        )
        response = client.get(f'/topic/{topic_with_articles.slug}/')
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Source Coverage' in content
        # NPR and Fox News are covering sources
        assert 'NPR' in content
        assert 'Fox News' in content

    def test_report_view_has_source_summary_and_matrix(
        self, client, topic_with_articles, article_npr, article_fox,
    ):
        """Report with complete pool should have source_summary and matrix_sources in context."""
        from apps.analysis.models import ArticleAnalysis

        pool = ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
            nugget_count=2, vital_nugget_count=1,
            articles_processed=2, built_at=timezone.now(),
        )
        nugget = ConsensusNugget.objects.create(
            pool=pool, nugget_text='Key fact', importance='vital',
            source_count=2, source_names=['NPR', 'Fox News'],
        )
        # Create omission scores
        score_npr = OmissionScore.objects.create(
            pool=pool, article=article_npr,
            coverage_score=0.8, omission_rate=0.2,
            support_count=1, total_nuggets=1,
            scored_at=timezone.now(),
        )
        score_fox = OmissionScore.objects.create(
            pool=pool, article=article_fox,
            coverage_score=0.5, omission_rate=0.5,
            support_count=0, not_support_count=1, total_nuggets=1,
            scored_at=timezone.now(),
        )
        # Create judgments
        NuggetJudgment.objects.create(
            score=score_npr, consensus_nugget=nugget, label='support',
        )
        NuggetJudgment.objects.create(
            score=score_fox, consensus_nugget=nugget, label='not_support',
        )
        # Create analysis so tone/framing appear in summary table
        for article in [article_npr, article_fox]:
            ArticleAnalysis.objects.create(
                article=article, status='complete',
                subjectivity_ratio=0.2, sentence_count=10,
                subjective_sentence_count=2, avg_subjectivity_confidence=0.8,
                leaning_left=0.3, leaning_center=0.5, leaning_right=0.2,
                framing_chunks_analyzed=2, analyzed_at=timezone.now(),
            )

        response = client.get(f'/topic/{topic_with_articles.slug}/')
        assert response.status_code == 200
        content = response.content.decode()

        # Source Analysis Overview table present
        assert 'Source Analysis Overview' in content
        assert 'source-summary-table' in content

        # Fact Coverage Matrix present
        assert 'Fact Coverage Matrix' in content
        assert 'fact-matrix' in content

        # Context data populated
        assert response.context['source_summary'] is not None
        assert len(response.context['source_summary']) == 2
        assert len(response.context['matrix_sources']) == 2
        assert len(response.context['matrix_rows']) >= 1


# ============================================================================
# Story-Level Omission (Topic model methods)
# ============================================================================

class TestStoryLevelOmission:
    """Tests for story-level omission: which sources ignored an event."""

    def test_get_covering_sources(self, topic_with_articles, source_npr, source_fox):
        """Covering sources = sources with articles for this topic."""
        covering = topic_with_articles.get_covering_sources()
        names = set(covering.values_list('name', flat=True))
        assert names == {'NPR', 'Fox News'}

    def test_get_missing_sources(self, topic_with_articles, source_reuters):
        """Missing sources = active sources that have NO article for this topic."""
        missing = topic_with_articles.get_missing_sources()
        names = set(missing.values_list('name', flat=True))
        assert 'Reuters' in names
        assert 'NPR' not in names
        assert 'Fox News' not in names

    def test_get_missing_sources_excludes_inactive(self, topic_with_articles, db):
        """Inactive sources should not appear in missing list."""
        Source.objects.create(
            name='Defunct News', slug='defunct-news',
            website_url='https://defunct.com', is_active=False,
        )
        missing = topic_with_articles.get_missing_sources()
        names = set(missing.values_list('name', flat=True))
        assert 'Defunct News' not in names

    def test_get_coverage_summary(self, topic_with_articles, source_reuters):
        """Coverage summary dict has correct counts."""
        summary = topic_with_articles.get_coverage_summary()
        assert summary['covering_sources'] == 2
        assert len(summary['covering_source_details']) == 2
        # Reuters is center bias, excluded from notable_missing
        # (notable_missing excludes CENTER bias sources)

    def test_coverage_summary_no_active_sources(self, topic, db):
        """Coverage summary with no articles returns zero covering."""
        Source.objects.all().delete()
        summary = topic.get_coverage_summary()
        assert summary['covering_sources'] == 0
        assert summary['notable_missing'] == []


# ============================================================================
# Report API Endpoint
# ============================================================================

class TestTopicReportAPI:
    """Tests for /api/v1/topics/<slug>/report/ endpoint."""

    def test_report_api_basic(self, client, topic_with_articles):
        """Report API returns topic info and story omission."""
        url = f'/api/v1/topics/{topic_with_articles.slug}/report/'
        response = client.get(url)
        assert response.status_code == 200
        data = response.json()
        assert data['topic']['title'] == topic_with_articles.title
        assert data['topic']['article_count'] == 2
        assert data['story_omission'] is not None
        assert 'covering_sources' in data['story_omission']

    def test_report_api_404(self, client, db):
        """Report API returns 404 for non-existent slug."""
        response = client.get('/api/v1/topics/no-such-topic/report/')
        assert response.status_code == 404

    def test_report_api_no_pool(self, client, topic_with_articles):
        """Report API returns null consensus pool when none exists."""
        url = f'/api/v1/topics/{topic_with_articles.slug}/report/'
        data = client.get(url).json()
        assert data['consensus_pool'] is None
        assert data['omission_data'] == []
        assert data['tone_data'] == []
        assert data['framing_data'] == []

    def test_report_api_with_complete_pool(self, client, topic_with_articles, article_npr, article_fox):
        """Report API returns omission data when pool is complete."""
        pool = ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
            nugget_count=5, vital_nugget_count=2,
            articles_processed=2, built_at=timezone.now(),
        )
        OmissionScore.objects.create(
            pool=pool, article=article_npr,
            omission_rate=0.2, coverage_score=0.8,
            vital_omission_rate=0.1, scored_at=timezone.now(),
        )
        OmissionScore.objects.create(
            pool=pool, article=article_fox,
            omission_rate=0.5, coverage_score=0.5,
            vital_omission_rate=0.4, scored_at=timezone.now(),
        )
        url = f'/api/v1/topics/{topic_with_articles.slug}/report/'
        data = client.get(url).json()
        assert data['consensus_pool']['status'] == 'complete'
        assert len(data['omission_data']) == 2

    def test_report_api_includes_neutral_summary(self, client, topic_with_articles):
        """Report API includes neutral summary when available."""
        from apps.summary.models import NeutralSummary
        NeutralSummary.objects.create(
            topic=topic_with_articles,
            status='complete',
            summary_text='A neutral summary of events.',
            nuggets_used=5,
            generated_at=timezone.now(),
        )
        url = f'/api/v1/topics/{topic_with_articles.slug}/report/'
        data = client.get(url).json()
        assert data['neutral_summary'] == 'A neutral summary of events.'


# ============================================================================
# Nuggets API Endpoint
# ============================================================================

class TestTopicNuggetsAPI:
    """Tests for /api/v1/topics/<slug>/nuggets/ endpoint."""

    def test_nuggets_api_no_pool(self, client, topic_with_articles):
        """Nuggets API returns empty list when no pool exists."""
        url = f'/api/v1/topics/{topic_with_articles.slug}/nuggets/'
        data = client.get(url).json()
        assert data['nuggets'] == []
        assert data['pool_status'] is None

    def test_nuggets_api_with_nuggets(self, client, topic_with_articles):
        """Nuggets API returns list of consensus nuggets."""
        pool = ConsensusPool.objects.create(
            topic=topic_with_articles,
            status='complete', nugget_count=3,
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='Fact A', importance='vital',
            source_count=3, source_names=['NPR', 'Fox', 'Reuters'],
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='Fact B', importance='okay',
            source_count=1, source_names=['NPR'],
        )
        url = f'/api/v1/topics/{topic_with_articles.slug}/nuggets/'
        data = client.get(url).json()
        assert len(data['nuggets']) == 2
        assert data['pool_status'] == 'complete'

    def test_nuggets_api_importance_filter(self, client, topic_with_articles):
        """Nuggets API filters by importance parameter."""
        pool = ConsensusPool.objects.create(
            topic=topic_with_articles, status='complete',
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='Vital', importance='vital', source_count=3,
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='Okay', importance='okay', source_count=1,
        )
        url = f'/api/v1/topics/{topic_with_articles.slug}/nuggets/?importance=vital'
        data = client.get(url).json()
        assert len(data['nuggets']) == 1
        assert data['nuggets'][0]['importance'] == 'vital'


# ============================================================================
# Omission API Endpoint
# ============================================================================

class TestTopicOmissionAPI:
    """Tests for /api/v1/topics/<slug>/omission/ endpoint."""

    def test_omission_api_no_pool(self, client, topic_with_articles):
        """Omission API returns empty list when no pool exists."""
        url = f'/api/v1/topics/{topic_with_articles.slug}/omission/'
        data = client.get(url).json()
        assert data['scores'] == []

    def test_omission_api_with_scores(self, client, topic_with_articles, article_npr):
        """Omission API returns per-source omission scores."""
        pool = ConsensusPool.objects.create(
            topic=topic_with_articles, status='complete',
        )
        OmissionScore.objects.create(
            pool=pool, article=article_npr,
            omission_rate=0.3, coverage_score=0.7,
            scored_at=timezone.now(),
        )
        url = f'/api/v1/topics/{topic_with_articles.slug}/omission/'
        data = client.get(url).json()
        assert len(data['scores']) == 1
        assert data['scores'][0]['source_name'] == 'NPR'
        assert data['scores'][0]['coverage_score'] == 0.7

    def test_omission_api_detail_mode(self, client, topic_with_articles, article_npr):
        """Omission API detail=true includes per-nugget judgments."""
        pool = ConsensusPool.objects.create(
            topic=topic_with_articles, status='complete',
        )
        nugget = ConsensusNugget.objects.create(
            pool=pool, nugget_text='Key fact', importance='vital', source_count=2,
        )
        score = OmissionScore.objects.create(
            pool=pool, article=article_npr,
            coverage_score=0.5, scored_at=timezone.now(),
        )
        NuggetJudgment.objects.create(
            score=score, consensus_nugget=nugget, label='support',
        )
        url = f'/api/v1/topics/{topic_with_articles.slug}/omission/?detail=true'
        data = client.get(url).json()
        assert len(data['scores']) == 1
        assert 'judgments' in data['scores'][0]
        assert len(data['scores'][0]['judgments']) == 1
        assert data['scores'][0]['judgments'][0]['label'] == 'support'
