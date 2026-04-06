"""End-to-end integration tests for the Prism pipeline."""

import pytest
from unittest.mock import patch, MagicMock
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.articles.models import Source, Article
from apps.topics.models import Topic, ArticleCluster
from apps.analysis.models import ArticleAnalysis
from apps.consensus.models import (
    ConsensusPool, ConsensusNugget, OmissionScore, NuggetJudgment,
)
from apps.summary.models import NeutralSummary


@pytest.fixture
def diverse_sources(db):
    """Create 4 sources with different biases."""
    return [
        Source.objects.create(
            name=name, slug=slug,
            website_url=f'https://www.{uri}',
            event_registry_uri=uri,
            known_bias=bias, is_active=True,
        )
        for name, slug, uri, bias in [
            ('NPR', 'int-npr', 'int-npr.org', 'center_left'),
            ('Reuters', 'int-reuters', 'int-reuters.com', 'center'),
            ('Fox News', 'int-fox', 'int-foxnews.com', 'right'),
            ('BBC News', 'int-bbc', 'int-bbc.co.uk', 'center'),
        ]
    ]


@pytest.fixture
def full_topic(diverse_sources):
    """Create a topic with articles, analysis, pool, scores, and summary."""
    topic = Topic.objects.create(
        title='Major Policy Decision',
        slug='major-policy-decision',
        event_registry_uri='eng-integration-test',
    )

    articles = []
    for i, source in enumerate(diverse_sources):
        article = Article.objects.create(
            source=source,
            title=f'{source.name} covers policy decision',
            url=f'https://{source.event_registry_uri}/policy-{i}',
            content=f'Article text from {source.name}. The president signed a bill. ' * 50,
            status='complete',
            published_at=timezone.now(),
            event_registry_uri=f'er-integ-{i}',
        )
        ArticleCluster.objects.create(
            topic=topic, article=article,
            confidence_score=0.9, cluster_rank=i,
        )
        articles.append(article)

    topic.update_metrics()

    # Analysis
    for article in articles:
        ArticleAnalysis.objects.create(
            article=article,
            status='complete',
            subjectivity_ratio=0.3,
            sentence_count=50,
            subjective_sentence_count=15,
            avg_subjectivity_confidence=0.85,
            leaning_left=0.25,
            leaning_center=0.55,
            leaning_right=0.20,
            framing_chunks_analyzed=5,
            analyzed_at=timezone.now(),
        )

    # Consensus pool
    pool = ConsensusPool.objects.create(
        topic=topic,
        status='complete',
        nugget_count=5,
        vital_nugget_count=2,
        articles_processed=4,
        built_at=timezone.now(),
    )
    for i in range(5):
        ConsensusNugget.objects.create(
            pool=pool,
            nugget_text=f'Consensus fact #{i+1}',
            importance='vital' if i < 2 else 'okay',
            source_count=3 if i < 2 else 1,
            source_names=['NPR', 'Reuters', 'Fox News'] if i < 2 else ['NPR'],
        )

    # Omission scores + nugget judgments
    nuggets = list(pool.nuggets.order_by('id'))
    for article in articles:
        score = OmissionScore.objects.create(
            pool=pool, article=article,
            coverage_score=0.7, omission_rate=0.3,
            vital_omission_rate=0.1,
            support_count=3, partial_support_count=1,
            not_support_count=1, total_nuggets=5,
            vital_support_count=2, vital_partial_support_count=0, vital_total=2,
            scored_at=timezone.now(),
        )
        # Create judgments for each nugget
        for i, nugget in enumerate(nuggets):
            if i < 3:
                label = 'support'
            elif i < 4:
                label = 'partial_support'
            else:
                label = 'not_support'
            NuggetJudgment.objects.create(
                score=score, consensus_nugget=nugget, label=label,
            )

    # Summary
    NeutralSummary.objects.create(
        topic=topic,
        status='complete',
        summary_text='A neutral summary of the policy decision.',
        nuggets_used=5,
        generated_at=timezone.now(),
    )

    return topic


@pytest.mark.django_db
class TestFullPipelineIntegration:
    def test_report_renders_all_sections(self, full_topic):
        client = Client()
        response = client.get(f'/topic/{full_topic.slug}/')
        assert response.status_code == 200
        content = response.content.decode()

        assert 'Media Comparison Report' in content
        assert 'Neutral Summary' in content
        assert 'neutral summary of the policy decision' in content
        assert 'Coverage Completeness' in content
        assert 'Tone' in content
        assert 'Framing' in content
        assert 'Fact Coverage Matrix' in content
        assert 'chart.js' in content.lower() or 'Chart' in content

    def test_report_api_returns_all_data(self, full_topic):
        client = Client()
        response = client.get(f'/api/v1/topics/{full_topic.slug}/report/')
        assert response.status_code == 200
        data = response.json()

        assert data['topic']['article_count'] == 4
        assert data['consensus_pool']['status'] == 'complete'
        assert data['neutral_summary'] is not None
        assert len(data['omission_data']) == 4
        assert len(data['tone_data']) == 4
        assert len(data['framing_data']) == 4
        assert data['story_omission']['covering_sources'] == 4

    def test_report_api_includes_weighted_coverage(self, full_topic):
        client = Client()
        response = client.get(f'/api/v1/topics/{full_topic.slug}/report/')
        data = response.json()
        for entry in data['omission_data']:
            assert 'weighted_coverage_pct' in entry

    def test_article_detail_shows_analysis(self, full_topic):
        article = Article.objects.filter(cluster__topic=full_topic).first()
        client = Client()
        response = client.get(reverse('web:article-detail', kwargs={'pk': article.pk}))
        assert response.status_code == 200
        content = response.content.decode()
        assert 'Prism Analysis' in content
        assert 'Tone' in content
        assert 'Framing' in content
        assert 'Coverage Completeness' in content

    def test_article_detail_without_analysis(self, db):
        source = Source.objects.create(
            name='Solo', slug='solo',
            website_url='https://solo.com',
            known_bias='center', is_active=True,
        )
        article = Article.objects.create(
            source=source,
            title='Solo Article',
            url='https://solo.com/art',
            content='Content here.',
            status='complete',
        )
        client = Client()
        response = client.get(reverse('web:article-detail', kwargs={'pk': article.pk}))
        assert response.status_code == 200
        assert 'Prism Analysis' not in response.content.decode()


@pytest.mark.django_db
class TestStoryLevelOmissionIntegration:
    def test_missing_sources_detected(self, diverse_sources):
        topic = Topic.objects.create(
            title='Partial Coverage', slug='partial-coverage',
        )
        # Only first 2 of 4 sources cover this topic
        for source in diverse_sources[:2]:
            article = Article.objects.create(
                source=source,
                title=f'{source.name} article',
                url=f'https://{source.event_registry_uri}/partial',
                content='Content',
                status='complete',
            )
            ArticleCluster.objects.create(topic=topic, article=article)

        topic.update_metrics()
        summary = topic.get_coverage_summary()

        assert summary['covering_sources'] == 2
        # notable_missing excludes CENTER bias, so only Fox News (right) appears
        missing_names = [s['name'] for s in summary['notable_missing']]
        assert 'Fox News' in missing_names


# ============================================================
# Task Chain Triggering Tests
# ============================================================

@pytest.mark.django_db
class TestTaskChainTriggering:
    """Verify that Celery tasks correctly queue downstream tasks."""

    def test_fetch_events_queues_fetch_event_articles(self):
        """fetch_events() should queue fetch_event_articles for each new event."""
        Source.objects.create(
            name='TestSrc', slug='testsrc',
            website_url='https://test.com',
            event_registry_uri='test.com',
            is_active=True,
        )

        mock_events = [
            {'uri': 'eng-event-1', 'title': {'eng': 'Event One'}, 'concepts': []},
            {'uri': 'eng-event-2', 'title': {'eng': 'Event Two'}, 'concepts': []},
        ]

        mock_client = MagicMock()
        mock_client.fetch_recent_events.return_value = mock_events

        with patch('apps.articles.services.EventRegistryClient', return_value=mock_client), \
             patch('apps.articles.tasks.fetch_event_articles') as mock_fetch:
            from apps.articles.tasks import fetch_events
            result = fetch_events()

        assert '2 new events' in result
        assert mock_fetch.delay.call_count == 2

    def test_fetch_events_skips_existing_topics(self):
        """fetch_events() should not queue articles for events already in DB."""
        Topic.objects.create(
            title='Existing', slug='existing',
            event_registry_uri='eng-existing',
        )

        mock_events = [
            {'uri': 'eng-existing', 'title': {'eng': 'Existing'}, 'concepts': []},
        ]

        mock_client = MagicMock()
        mock_client.fetch_recent_events.return_value = mock_events

        with patch('apps.articles.services.EventRegistryClient', return_value=mock_client), \
             patch('apps.articles.tasks.fetch_event_articles') as mock_fetch:
            from apps.articles.tasks import fetch_events
            result = fetch_events()

        assert '0 new events' in result
        mock_fetch.delay.assert_not_called()

    @pytest.mark.django_db(transaction=True)
    def test_fetch_event_articles_triggers_analyze_article(self):
        """fetch_event_articles() should queue analyze_article for each new article."""
        source = Source.objects.create(
            name='NPR', slug='chain-npr',
            website_url='https://npr.org',
            event_registry_uri='npr.org',
            is_active=True,
        )
        topic = Topic.objects.create(
            title='Chain Test', slug='chain-test',
            event_registry_uri='eng-chain-1',
        )

        mock_articles = [{
            'url': 'https://npr.org/chain-article-1',
            'title': 'Test article',
            'body': 'This is the body of the test article. ' * 20,
            'source': {'uri': 'npr.org'},
            'uri': 'er-chain-1',
            'dateTime': '2024-01-01T00:00:00Z',
            'authors': [],
            'sim': 0.9,
        }]

        mock_client = MagicMock()
        mock_client.fetch_event_articles.return_value = mock_articles

        with patch('apps.articles.services.EventRegistryClient', return_value=mock_client), \
             patch('apps.analysis.tasks.analyze_article') as mock_analyze:
            from apps.articles.tasks import fetch_event_articles
            result = fetch_event_articles('eng-chain-1', topic.id)

        assert '1 articles ingested' in result
        mock_analyze.delay.assert_called_once()

    @pytest.mark.django_db(transaction=True)
    def test_fetch_event_articles_sync_calls_directly(self):
        """With sync=True, analysis should run directly (not .delay())."""
        source = Source.objects.create(
            name='NPR', slug='sync-npr',
            website_url='https://npr.org',
            event_registry_uri='npr.org',
            is_active=True,
        )
        topic = Topic.objects.create(
            title='Sync Test', slug='sync-test',
            event_registry_uri='eng-sync-1',
        )

        mock_articles = [{
            'url': 'https://npr.org/sync-article-1',
            'title': 'Test sync',
            'body': 'Body text content. ' * 20,
            'source': {'uri': 'npr.org'},
            'uri': 'er-sync-1',
            'authors': [],
            'sim': 0.9,
        }]

        mock_client = MagicMock()
        mock_client.fetch_event_articles.return_value = mock_articles

        with patch('apps.articles.services.EventRegistryClient', return_value=mock_client), \
             patch('apps.analysis.tasks.analyze_article') as mock_analyze:
            from apps.articles.tasks import fetch_event_articles
            fetch_event_articles('eng-sync-1', topic.id, sync=True)

        # sync=True should call directly, not .delay()
        mock_analyze.assert_called_once()
        mock_analyze.delay.assert_not_called()

    def test_pool_builder_triggers_summary_generation(self, db):
        """PoolBuilder should auto-trigger generate_summary after completion."""
        source = Source.objects.create(
            name='S1', slug='pb-s1',
            website_url='https://s1.com',
            event_registry_uri='s1.com',
            is_active=True,
        )
        topic = Topic.objects.create(
            title='Pool Test', slug='pool-test',
            event_registry_uri='eng-pool-1',
        )
        for i in range(2):
            art = Article.objects.create(
                source=source, title=f'Art {i}',
                url=f'https://s1.com/art-{i}',
                content=f'Article content number {i}. ' * 50,
                status='complete',
            )
            ArticleCluster.objects.create(topic=topic, article=art, cluster_rank=i)
        topic.update_metrics()

        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = [
            {'nugget_text': 'Fact one', 'nugget_type': 'claim'},
            {'nugget_text': 'Fact two', 'nugget_type': 'claim'},
        ]

        mock_dedup = MagicMock()
        mock_dedup.deduplicate.return_value = [
            {'nugget_text': 'Fact one', 'source_names': ['S1'], 'source_count': 2, 'importance': 'vital'},
            {'nugget_text': 'Fact two', 'source_names': ['S1'], 'source_count': 1, 'importance': 'okay'},
        ]

        mock_assigner = MagicMock()
        mock_assign_result = MagicMock()
        mock_assign_result.assignments = [
            MagicMock(fact_index=0, label=MagicMock(value='support')),
            MagicMock(fact_index=1, label=MagicMock(value='not_support')),
        ]
        mock_assigner.assign.return_value = mock_assign_result

        with patch('apps.consensus.services.pool_builder.NuggetExtractor', return_value=mock_extractor), \
             patch('apps.consensus.services.pool_builder.NuggetDeduplicator', return_value=mock_dedup), \
             patch('apps.consensus.services.pool_builder.AutoAssigner', return_value=mock_assigner), \
             patch('apps.summary.tasks.generate_summary') as mock_summary:
            from apps.consensus.services.pool_builder import PoolBuilder
            builder = PoolBuilder(backend='deepseek')
            builder.build(topic.id)

        mock_summary.delay.assert_called_once_with(topic.id)

    def test_build_pools_for_ready_topics_filters_by_source_count(self, db):
        """Only topics with >= min_sources should be queued."""
        sources = []
        for i in range(3):
            sources.append(Source.objects.create(
                name=f'Src{i}', slug=f'ready-src{i}',
                website_url=f'https://src{i}.com',
                event_registry_uri=f'ready-src{i}.com',
                is_active=True,
            ))

        # Topic with 1 source (not ready)
        t1 = Topic.objects.create(title='One Source', slug='one-source')
        a1 = Article.objects.create(source=sources[0], title='A1', url='https://src0.com/a1', content='x', status='complete')
        ArticleCluster.objects.create(topic=t1, article=a1)

        # Topic with 3 sources (ready)
        t3 = Topic.objects.create(title='Three Sources', slug='three-sources')
        for i, src in enumerate(sources):
            art = Article.objects.create(source=src, title=f'T3A{i}', url=f'https://src{i}.com/t3a{i}', content='y', status='complete')
            ArticleCluster.objects.create(topic=t3, article=art)

        with patch('apps.consensus.tasks.build_consensus_pool') as mock_build:
            from apps.consensus.tasks import build_pools_for_ready_topics
            result = build_pools_for_ready_topics(min_sources=3)

        assert 'Queued 1 topics' in result
        mock_build.delay.assert_called_once_with(t3.id)


# ============================================================
# Report Edge Cases
# ============================================================

@pytest.mark.django_db
class TestReportEdgeCases:
    """Test report view/API with partial or missing data."""

    def _make_topic_with_articles(self, db_fixture_needed=True):
        """Helper: create a topic with 2 articles (no analysis, no pool)."""
        source = Source.objects.create(
            name='EdgeSrc', slug='edge-src',
            website_url='https://edge.com',
            event_registry_uri='edge.com',
            is_active=True,
        )
        topic = Topic.objects.create(
            title='Edge Case Topic', slug='edge-case-topic',
            event_registry_uri='eng-edge-1',
        )
        for i in range(2):
            art = Article.objects.create(
                source=source, title=f'Edge Art {i}',
                url=f'https://edge.com/art-{i}',
                content='Some content here.',
                status='complete', published_at=timezone.now(),
            )
            ArticleCluster.objects.create(topic=topic, article=art, cluster_rank=i)
        topic.update_metrics()
        return topic

    def test_report_no_consensus_pool(self, db):
        """Report renders gracefully when no consensus pool exists."""
        topic = self._make_topic_with_articles()
        client = Client()
        response = client.get(f'/topic/{topic.slug}/')
        assert response.status_code == 200

    def test_report_pool_in_progress(self, db):
        """Report handles pool in EXTRACTING status."""
        topic = self._make_topic_with_articles()
        ConsensusPool.objects.create(
            topic=topic, status='extracting',
        )
        client = Client()
        response = client.get(f'/topic/{topic.slug}/')
        assert response.status_code == 200

    def test_report_no_analysis(self, db):
        """Report works when articles have no analysis."""
        topic = self._make_topic_with_articles()
        pool = ConsensusPool.objects.create(
            topic=topic, status='complete',
            nugget_count=2, vital_nugget_count=1,
            articles_processed=2, built_at=timezone.now(),
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='Test fact',
            importance='vital', source_count=2,
            source_names=['EdgeSrc'],
        )
        client = Client()
        response = client.get(f'/topic/{topic.slug}/')
        assert response.status_code == 200

    def test_report_no_summary(self, db):
        """Report renders without neutral summary."""
        topic = self._make_topic_with_articles()
        ConsensusPool.objects.create(
            topic=topic, status='complete',
            nugget_count=1, vital_nugget_count=0,
            articles_processed=2, built_at=timezone.now(),
        )
        client = Client()
        response = client.get(f'/topic/{topic.slug}/')
        assert response.status_code == 200

    def test_report_empty_topic(self, db):
        """Report renders for topic with 0 articles."""
        topic = Topic.objects.create(
            title='Empty Topic', slug='empty-topic',
        )
        client = Client()
        response = client.get(f'/topic/{topic.slug}/')
        assert response.status_code == 200

    def test_report_api_no_pool(self, db):
        """Report API returns null for missing consensus/summary."""
        topic = self._make_topic_with_articles()
        client = Client()
        response = client.get(f'/api/v1/topics/{topic.slug}/report/')
        assert response.status_code == 200
        data = response.json()
        assert data['consensus_pool'] is None
        assert data['neutral_summary'] is None
        assert data['omission_data'] == []
        assert data['tone_data'] == []
        assert data['framing_data'] == []

    def test_report_api_pool_in_progress(self, db):
        """Report API returns pool status when in progress."""
        topic = self._make_topic_with_articles()
        ConsensusPool.objects.create(
            topic=topic, status='extracting',
        )
        client = Client()
        response = client.get(f'/api/v1/topics/{topic.slug}/report/')
        data = response.json()
        assert data['consensus_pool']['status'] == 'extracting'
        assert data['omission_data'] == []


# ============================================================
# API Data Completeness
# ============================================================

@pytest.mark.django_db
class TestAPIDataCompleteness:
    """Verify API serializers include all expected fields."""

    def test_article_detail_api_includes_analysis(self, db):
        """Article detail API includes tone/framing analysis fields."""
        source = Source.objects.create(
            name='APISrc', slug='api-src',
            website_url='https://api.com',
            event_registry_uri='api.com',
            is_active=True,
        )
        article = Article.objects.create(
            source=source, title='API Test Article',
            url='https://api.com/test',
            content='Content for API test.',
            status='complete',
        )
        ArticleAnalysis.objects.create(
            article=article, status='complete',
            subjectivity_ratio=0.12,
            sentence_count=10,
            subjective_sentence_count=1,
            avg_subjectivity_confidence=0.85,
            leaning_left=0.3, leaning_center=0.5, leaning_right=0.2,
            framing_chunks_analyzed=2,
            analyzed_at=timezone.now(),
        )

        client = Client()
        response = client.get(f'/api/v1/articles/{article.id}/')
        assert response.status_code == 200
        data = response.json()

        assert 'analysis' in data
        assert data['analysis']['subjectivity_ratio'] == 0.12
        assert data['analysis']['tone_label'] == 'Mostly Objective'
        assert data['analysis']['dominant_leaning'] == 'center'
        assert data['analysis']['leaning_left'] == 0.3

    def test_topic_detail_api_includes_coverage_summary(self, diverse_sources):
        """Topic detail API includes coverage_summary with missing sources."""
        topic = Topic.objects.create(
            title='Coverage API Test', slug='coverage-api-test',
        )
        # Only one source covers it
        art = Article.objects.create(
            source=diverse_sources[0],
            title='Single source', url='https://int-npr.org/cov',
            content='x', status='complete',
        )
        ArticleCluster.objects.create(topic=topic, article=art)
        topic.update_metrics()

        client = Client()
        response = client.get(f'/api/v1/topics/{topic.slug}/')
        assert response.status_code == 200
        data = response.json()

        assert 'coverage_summary' in data
        assert data['coverage_summary']['covering_sources'] == 1
        # notable_missing excludes CENTER bias; Fox (right) shows, BBC and Reuters (center) don't
        assert len(data['coverage_summary']['notable_missing']) >= 1

    def test_nuggets_api_filters_by_importance(self, full_topic):
        """Nuggets API filters by importance query param."""
        client = Client()
        response = client.get(f'/api/v1/topics/{full_topic.slug}/nuggets/?importance=vital')
        assert response.status_code == 200
        data = response.json()
        assert all(n['importance'] == 'vital' for n in data['nuggets'])
        assert len(data['nuggets']) == 2

    def test_nuggets_api_returns_all_without_filter(self, full_topic):
        """Nuggets API returns all nuggets without importance filter."""
        client = Client()
        response = client.get(f'/api/v1/topics/{full_topic.slug}/nuggets/')
        assert response.status_code == 200
        data = response.json()
        assert len(data['nuggets']) == 5
        assert data['pool_status'] == 'complete'

    def test_omission_api_detail_includes_judgments(self, full_topic):
        """Omission API with detail=true includes per-nugget judgments."""
        # full_topic fixture already creates judgments for all scores
        client = Client()
        response = client.get(f'/api/v1/topics/{full_topic.slug}/omission/?detail=true')
        assert response.status_code == 200
        data = response.json()
        assert data['pool_status'] == 'complete'
        assert len(data['scores']) == 4
        # Every score should have judgments (5 nuggets each)
        for s in data['scores']:
            assert len(s.get('judgments', [])) == 5

    def test_omission_api_without_detail_excludes_judgments(self, full_topic):
        """Omission API without detail excludes judgments field."""
        client = Client()
        response = client.get(f'/api/v1/topics/{full_topic.slug}/omission/')
        assert response.status_code == 200
        data = response.json()
        for score in data['scores']:
            assert 'judgments' not in score


# ============================================================
# Summary Evaluator Unit Tests
# ============================================================

@pytest.mark.django_db
class TestSummaryEvaluator:
    """Unit tests for the SummaryEvaluator service."""

    def test_evaluate_parses_valid_json(self):
        """Evaluator correctly parses a well-formed LLM response."""
        from apps.summary.services.evaluator import SummaryEvaluator

        mock_response = '{"factuality": 5, "neutrality": 4, "coherence": 5, "completeness": 4, "explanations": {"factuality": "Good", "neutrality": "Minor issue", "coherence": "Great", "completeness": "Mostly complete"}}'

        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response

        evaluator = SummaryEvaluator()
        with patch('apps.summary.services.evaluator.get_llm_client', return_value=mock_client):
            score = evaluator.evaluate(
                summary_text='Test summary.',
                nuggets_text='- Fact one\n- Fact two',
                topic_title='Test Topic',
            )

        assert score.factuality == 5
        assert score.neutrality == 4
        assert score.coherence == 5
        assert score.completeness == 4
        assert score.average == 4.5
        assert score.rating == 'Excellent'

    def test_evaluate_handles_json_wrapped_in_text(self):
        """Evaluator extracts JSON even when wrapped in extra text."""
        from apps.summary.services.evaluator import SummaryEvaluator

        mock_response = 'Here is my evaluation:\n{"factuality": 3, "neutrality": 3, "coherence": 3, "completeness": 3, "explanations": {}}\nDone.'

        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response

        evaluator = SummaryEvaluator()
        with patch('apps.summary.services.evaluator.get_llm_client', return_value=mock_client):
            score = evaluator.evaluate('s', 'n', 't')

        assert score.factuality == 3
        assert score.rating == 'Fair'

    def test_evaluate_handles_malformed_response(self):
        """Evaluator falls back to defaults on unparseable response."""
        from apps.summary.services.evaluator import SummaryEvaluator

        mock_client = MagicMock()
        mock_client.generate.return_value = 'This is not valid JSON at all.'

        evaluator = SummaryEvaluator()
        with patch('apps.summary.services.evaluator.get_llm_client', return_value=mock_client):
            score = evaluator.evaluate('s', 'n', 't')

        # Falls back to 3 for all criteria
        assert score.factuality == 3
        assert score.neutrality == 3
        assert score.rating == 'Fair'

    def test_rating_thresholds(self):
        """Verify Excellent/Good/Fair/Poor thresholds."""
        from apps.summary.services.evaluator import EvaluationScore

        excellent = EvaluationScore(5, 5, 4, 5, {})
        assert excellent.rating == 'Excellent'
        assert excellent.average == 4.75

        good = EvaluationScore(4, 4, 3, 4, {})
        assert good.rating == 'Good'
        assert good.average == 3.75

        fair = EvaluationScore(3, 3, 2, 3, {})
        assert fair.rating == 'Fair'
        assert fair.average == 2.75

        poor = EvaluationScore(1, 2, 2, 1, {})
        assert poor.rating == 'Poor'
        assert poor.average == 1.5

    def test_clamp_scores_to_valid_range(self):
        """Scores outside 1-5 get clamped."""
        from apps.summary.services.evaluator import SummaryEvaluator

        evaluator = SummaryEvaluator()
        score = evaluator._build_score({
            'factuality': 10,
            'neutrality': -1,
            'coherence': 0,
            'completeness': 'invalid',
        })

        assert score.factuality == 5    # clamped from 10
        assert score.neutrality == 1    # clamped from -1
        assert score.coherence == 1     # clamped from 0
        assert score.completeness == 3  # default for invalid

    def test_handles_deepseek_thinking_tags(self):
        """Evaluator strips <think>...</think> tags from DeepSeek R1 responses."""
        from apps.summary.services.evaluator import SummaryEvaluator

        mock_response = '<think>Let me evaluate this carefully...</think>{"factuality": 5, "neutrality": 5, "coherence": 4, "completeness": 5, "explanations": {}}'

        mock_client = MagicMock()
        mock_client.generate.return_value = mock_response

        evaluator = SummaryEvaluator()
        with patch('apps.summary.services.evaluator.get_llm_client', return_value=mock_client):
            score = evaluator.evaluate('s', 'n', 't')

        assert score.factuality == 5
        assert score.neutrality == 5
