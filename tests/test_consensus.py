"""Tests for consensus fact pool and omission scoring."""

import pytest
from unittest.mock import patch, MagicMock
from django.utils import timezone

from apps.consensus.models import (
    ConsensusPool,
    ConsensusNugget,
    RawNugget,
    OmissionScore,
    NuggetJudgment,
)

# Pre-import subpackage modules so @patch decorators can resolve dotted paths
import apps.consensus.services.pool_builder  # noqa: F401
import apps.consensus.services.deduplicator  # noqa: F401


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestConsensusPoolModel:
    """Tests for the ConsensusPool model."""

    def test_create_pool(self, topic):
        pool = ConsensusPool.objects.create(
            topic=topic,
            status=ConsensusPool.Status.COMPLETE,
            nugget_count=10,
            vital_nugget_count=3,
            articles_processed=5,
            built_at=timezone.now(),
        )
        assert pool.id is not None
        assert pool.topic == topic
        assert pool.nugget_count == 10

    def test_str_representation(self, topic):
        pool = ConsensusPool.objects.create(topic=topic)
        assert 'Test Topic' in str(pool)
        assert 'pending' in str(pool)

    def test_one_to_one_constraint(self, topic):
        ConsensusPool.objects.create(topic=topic)
        with pytest.raises(Exception):
            ConsensusPool.objects.create(topic=topic)

    def test_status_choices(self, topic):
        pool = ConsensusPool.objects.create(topic=topic)
        for status in ConsensusPool.Status:
            pool.status = status
            pool.save()
            pool.refresh_from_db()
            assert pool.status == status


class TestConsensusNuggetModel:
    """Tests for the ConsensusNugget model."""

    def test_create_nugget(self, topic):
        pool = ConsensusPool.objects.create(topic=topic)
        nugget = ConsensusNugget.objects.create(
            pool=pool,
            nugget_text='The president signed the bill on Monday',
            importance=ConsensusNugget.Importance.VITAL,
            source_count=4,
            source_names=['NPR', 'Reuters', 'Fox News', 'AP News'],
        )
        assert nugget.id is not None
        assert nugget.source_count == 4
        assert 'NPR' in nugget.source_names

    def test_str_representation(self, topic):
        pool = ConsensusPool.objects.create(topic=topic)
        nugget = ConsensusNugget.objects.create(
            pool=pool,
            nugget_text='A short fact',
            importance=ConsensusNugget.Importance.OKAY,
            source_count=1,
        )
        assert 'okay' in str(nugget)
        assert '1 sources' in str(nugget)

    def test_importance_vital(self, topic):
        pool = ConsensusPool.objects.create(topic=topic)
        nugget = ConsensusNugget.objects.create(
            pool=pool,
            nugget_text='Widely reported fact',
            importance=ConsensusNugget.Importance.VITAL,
            source_count=5,
        )
        assert nugget.importance == 'vital'

    def test_ordering_by_source_count(self, topic):
        pool = ConsensusPool.objects.create(topic=topic)
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='Rare fact', source_count=1,
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='Common fact', source_count=5,
        )
        nuggets = list(pool.nuggets.all())
        assert nuggets[0].source_count == 5


class TestRawNuggetModel:
    """Tests for the RawNugget model."""

    def test_create_raw_nugget(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        raw = RawNugget.objects.create(
            pool=pool,
            article=article_npr,
            nugget_text='NPR reported this fact',
            nugget_type='claim',
        )
        assert raw.id is not None
        assert raw.consensus_nugget is None  # not yet linked

    def test_link_to_consensus(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        cn = ConsensusNugget.objects.create(
            pool=pool, nugget_text='Shared fact', source_count=2,
        )
        raw = RawNugget.objects.create(
            pool=pool,
            article=article_npr,
            nugget_text='NPR version of shared fact',
            consensus_nugget=cn,
        )
        assert raw.consensus_nugget == cn
        assert cn.raw_nuggets.count() == 1


class TestOmissionScoreModel:
    """Tests for the OmissionScore model."""

    def test_create_score(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        score = OmissionScore.objects.create(
            pool=pool,
            article=article_npr,
            omission_rate=0.30,
            vital_omission_rate=0.10,
            coverage_score=0.70,
            support_count=7,
            partial_support_count=1,
            not_support_count=3,
            total_nuggets=11,
            vital_support_count=9,
            vital_total=10,
            scored_at=timezone.now(),
        )
        assert score.id is not None
        assert score.coverage_score == 0.70

    def test_str_with_coverage(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        score = OmissionScore.objects.create(
            pool=pool,
            article=article_npr,
            coverage_score=0.85,
        )
        assert 'NPR' in str(score)
        assert '85%' in str(score)

    def test_str_pending(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        score = OmissionScore.objects.create(
            pool=pool, article=article_npr,
        )
        assert 'pending' in str(score)

    def test_unique_together(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        OmissionScore.objects.create(pool=pool, article=article_npr)
        with pytest.raises(Exception):
            OmissionScore.objects.create(pool=pool, article=article_npr)


class TestNuggetJudgmentModel:
    """Tests for the NuggetJudgment model."""

    def test_create_judgment(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        cn = ConsensusNugget.objects.create(
            pool=pool, nugget_text='Test fact',
        )
        score = OmissionScore.objects.create(
            pool=pool, article=article_npr,
        )
        judgment = NuggetJudgment.objects.create(
            score=score,
            consensus_nugget=cn,
            label=NuggetJudgment.Label.SUPPORT,
        )
        assert judgment.label == 'support'

    def test_unique_together(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        cn = ConsensusNugget.objects.create(
            pool=pool, nugget_text='Test fact',
        )
        score = OmissionScore.objects.create(
            pool=pool, article=article_npr,
        )
        NuggetJudgment.objects.create(
            score=score, consensus_nugget=cn,
            label=NuggetJudgment.Label.SUPPORT,
        )
        with pytest.raises(Exception):
            NuggetJudgment.objects.create(
                score=score, consensus_nugget=cn,
                label=NuggetJudgment.Label.NOT_SUPPORT,
            )

    def test_all_label_choices(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        score = OmissionScore.objects.create(
            pool=pool, article=article_npr,
        )
        for label in NuggetJudgment.Label:
            cn = ConsensusNugget.objects.create(
                pool=pool, nugget_text=f'Fact for {label}',
            )
            j = NuggetJudgment.objects.create(
                score=score, consensus_nugget=cn, label=label,
            )
            assert j.label == label


# ---------------------------------------------------------------------------
# Deduplicator tests
# ---------------------------------------------------------------------------

class TestNuggetDeduplicator:
    """Tests for the NuggetDeduplicator service."""

    def test_empty_input(self):
        from apps.consensus.services.deduplicator import NuggetDeduplicator
        dedup = NuggetDeduplicator(threshold=0.85)
        result = dedup.deduplicate([], [])
        assert len(result.clusters) == 0
        assert len(result.assignments) == 0

    @patch('apps.consensus.services.deduplicator.NuggetDeduplicator._encode')
    def test_identical_nuggets_cluster_together(self, mock_encode):
        """Identical nuggets from different sources should cluster."""
        import numpy as np
        from apps.consensus.services.deduplicator import NuggetDeduplicator

        # 3 identical embeddings (sim=1.0) + 1 different
        identical_emb = np.array([1.0, 0.0, 0.0])
        different_emb = np.array([0.0, 1.0, 0.0])
        mock_encode.return_value = np.array([
            identical_emb, identical_emb, identical_emb, different_emb,
        ])

        dedup = NuggetDeduplicator(threshold=0.85)
        result = dedup.deduplicate(
            ['Fact A v1', 'Fact A v2', 'Fact A v3', 'Fact B'],
            ['NPR', 'Fox News', 'Reuters', 'NPR'],
        )

        assert len(result.clusters) == 2  # 2 distinct clusters

        # Find the big cluster (3 nuggets)
        big_cluster = [c for c in result.clusters if len(c.nugget_indices) == 3][0]
        assert big_cluster.source_count == 3
        assert 'NPR' in big_cluster.source_names
        assert 'Fox News' in big_cluster.source_names
        assert 'Reuters' in big_cluster.source_names

    @patch('apps.consensus.services.deduplicator.NuggetDeduplicator._encode')
    def test_dissimilar_nuggets_separate(self, mock_encode):
        """Dissimilar nuggets should form separate clusters."""
        import numpy as np
        from apps.consensus.services.deduplicator import NuggetDeduplicator

        # 3 orthogonal embeddings (sim=0.0)
        mock_encode.return_value = np.array([
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
            [0.0, 0.0, 1.0],
        ])

        dedup = NuggetDeduplicator(threshold=0.85)
        result = dedup.deduplicate(
            ['Fact A', 'Fact B', 'Fact C'],
            ['NPR', 'Fox News', 'Reuters'],
        )

        assert len(result.clusters) == 3

    @patch('apps.consensus.services.deduplicator.NuggetDeduplicator._encode')
    def test_same_source_counted_once(self, mock_encode):
        """Multiple nuggets from same source in one cluster count as 1 source."""
        import numpy as np
        from apps.consensus.services.deduplicator import NuggetDeduplicator

        identical_emb = np.array([1.0, 0.0, 0.0])
        mock_encode.return_value = np.array([
            identical_emb, identical_emb,
        ])

        dedup = NuggetDeduplicator(threshold=0.85)
        result = dedup.deduplicate(
            ['Fact from NPR v1', 'Fact from NPR v2'],
            ['NPR', 'NPR'],
        )

        assert len(result.clusters) == 1
        assert result.clusters[0].source_count == 1  # same source


# ---------------------------------------------------------------------------
# PoolBuilder tests
# ---------------------------------------------------------------------------

class TestPoolBuilder:
    """Tests for the PoolBuilder service."""

    @patch('apps.consensus.services.pool_builder.AutoAssigner')
    @patch('apps.consensus.services.pool_builder.NuggetDeduplicator')
    @patch('apps.consensus.services.pool_builder.NuggetExtractor')
    def test_full_pipeline(
        self, mock_extractor_cls, mock_dedup_cls, mock_assigner_cls,
        topic_with_articles
    ):
        """Test the complete build pipeline."""
        from apps.consensus.services.pool_builder import PoolBuilder
        from apps.consensus.services.deduplicator import (
            DeduplicationResult, NuggetCluster,
        )
        from apps.evaluation.services.auto_assigner import (
            AutoAssignResult, NuggetAssignment, AssignmentLabel,
        )

        # Mock extractor
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = [
            {'fact': 'The event happened today', 'type': 'claim'},
            {'fact': 'Five people were involved', 'type': 'statistic'},
        ]
        mock_extractor_cls.return_value = mock_extractor

        # Mock deduplicator
        mock_dedup = MagicMock()
        mock_dedup.deduplicate.return_value = DeduplicationResult(
            clusters=[
                NuggetCluster(
                    cluster_id=0,
                    representative_text='The event happened today',
                    nugget_indices=[0, 2],
                    source_names={'NPR', 'Fox News'},
                ),
                NuggetCluster(
                    cluster_id=1,
                    representative_text='Five people were involved',
                    nugget_indices=[1, 3],
                    source_names={'NPR', 'Fox News'},
                ),
            ],
            assignments=[0, 1, 0, 1],
        )
        mock_dedup_cls.return_value = mock_dedup

        # Mock assigner
        mock_assigner = MagicMock()
        mock_assigner.assign.return_value = AutoAssignResult(
            assignments=[
                NuggetAssignment(0, 'The event happened today', AssignmentLabel.SUPPORT),
                NuggetAssignment(1, 'Five people were involved', AssignmentLabel.NOT_SUPPORT),
            ]
        )
        mock_assigner_cls.return_value = mock_assigner

        builder = PoolBuilder(backend='deepseek')
        pool = builder.build(topic_with_articles.id)

        assert pool.status == ConsensusPool.Status.COMPLETE
        assert pool.nugget_count == 2
        assert pool.articles_processed == 2
        assert pool.built_at is not None

        # Verify extraction was called for each article
        assert mock_extractor.extract.call_count == 2

        # Verify scores were created
        scores = OmissionScore.objects.filter(pool=pool)
        assert scores.count() == 2

    @patch('apps.consensus.services.pool_builder.NuggetExtractor')
    def test_fails_with_too_few_articles(self, mock_extractor_cls, topic):
        """Pool should fail if topic has fewer than 2 articles."""
        from apps.consensus.services.pool_builder import PoolBuilder

        builder = PoolBuilder(backend='deepseek')
        pool = builder.build(topic.id)

        assert pool.status == ConsensusPool.Status.FAILED
        assert 'at least 2 articles' in pool.error_message

    @patch('apps.consensus.services.pool_builder.NuggetExtractor')
    def test_wire_articles_excluded(self, mock_extractor_cls, topic, source_npr, source_fox):
        """Wire copy articles should be excluded from pool building."""
        from apps.articles.models import Article
        from apps.topics.models import ArticleCluster
        from apps.consensus.services.pool_builder import PoolBuilder

        # Create one real article and one wire copy
        real_article = Article.objects.create(
            source=source_npr, title='Original NPR Story',
            url='https://npr.org/original', content='Real content. ' * 50,
            status=Article.ProcessingStatus.COMPLETE, is_wire_content=False,
        )
        wire_article = Article.objects.create(
            source=source_fox, title='AP Wire on Fox',
            url='https://foxnews.com/ap-wire', author='Associated Press',
            content='Wire content. ' * 50,
            status=Article.ProcessingStatus.COMPLETE, is_wire_content=True,
        )
        ArticleCluster.objects.create(topic=topic, article=real_article)
        ArticleCluster.objects.create(topic=topic, article=wire_article)

        # Only 1 non-wire article → should fail with "at least 2"
        builder = PoolBuilder(backend='deepseek')
        pool = builder.build(topic.id)

        assert pool.status == ConsensusPool.Status.FAILED
        assert 'at least 2 articles' in pool.error_message

    def test_skips_existing_pool(self, topic_with_articles):
        """Should return existing pool if rebuild=False."""
        from apps.consensus.services.pool_builder import PoolBuilder

        existing = ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
        )

        builder = PoolBuilder(backend='deepseek')
        result = builder.build(topic_with_articles.id, rebuild=False)

        assert result.id == existing.id

    @patch('apps.consensus.services.pool_builder.AutoAssigner')
    @patch('apps.consensus.services.pool_builder.NuggetDeduplicator')
    @patch('apps.consensus.services.pool_builder.NuggetExtractor')
    def test_rebuild_deletes_old_pool(
        self, mock_extractor_cls, mock_dedup_cls, mock_assigner_cls,
        topic_with_articles
    ):
        """Rebuild should delete old pool and create new one."""
        from apps.consensus.services.pool_builder import PoolBuilder
        from apps.consensus.services.deduplicator import (
            DeduplicationResult, NuggetCluster,
        )
        from apps.evaluation.services.auto_assigner import (
            AutoAssignResult, NuggetAssignment, AssignmentLabel,
        )

        old_pool = ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
        )
        old_id = old_pool.id

        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = [
            {'fact': 'A fact', 'type': 'claim'},
        ]
        mock_extractor_cls.return_value = mock_extractor

        mock_dedup = MagicMock()
        mock_dedup.deduplicate.return_value = DeduplicationResult(
            clusters=[
                NuggetCluster(
                    cluster_id=0,
                    representative_text='A fact',
                    nugget_indices=[0, 1],
                    source_names={'NPR', 'Fox News'},
                ),
            ],
            assignments=[0, 0],
        )
        mock_dedup_cls.return_value = mock_dedup

        mock_assigner = MagicMock()
        mock_assigner.assign.return_value = AutoAssignResult(
            assignments=[
                NuggetAssignment(0, 'A fact', AssignmentLabel.SUPPORT),
            ]
        )
        mock_assigner_cls.return_value = mock_assigner

        builder = PoolBuilder(backend='deepseek')
        new_pool = builder.build(topic_with_articles.id, rebuild=True)

        assert new_pool.id != old_id
        assert not ConsensusPool.objects.filter(id=old_id).exists()


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------

class TestBuildConsensusPoolTask:
    """Tests for the build_consensus_pool Celery task."""

    @patch('apps.consensus.services.pool_builder.AutoAssigner')
    @patch('apps.consensus.services.pool_builder.NuggetDeduplicator')
    @patch('apps.consensus.services.pool_builder.NuggetExtractor')
    def test_task_creates_pool(
        self, mock_extractor_cls, mock_dedup_cls, mock_assigner_cls,
        topic_with_articles
    ):
        from apps.consensus.tasks import build_consensus_pool
        from apps.consensus.services.deduplicator import (
            DeduplicationResult, NuggetCluster,
        )
        from apps.evaluation.services.auto_assigner import (
            AutoAssignResult, NuggetAssignment, AssignmentLabel,
        )

        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = [
            {'fact': 'Test fact', 'type': 'claim'},
        ]
        mock_extractor_cls.return_value = mock_extractor

        mock_dedup = MagicMock()
        mock_dedup.deduplicate.return_value = DeduplicationResult(
            clusters=[
                NuggetCluster(
                    cluster_id=0,
                    representative_text='Test fact',
                    nugget_indices=[0, 1],
                    source_names={'NPR', 'Fox News'},
                ),
            ],
            assignments=[0, 0],
        )
        mock_dedup_cls.return_value = mock_dedup

        mock_assigner = MagicMock()
        mock_assigner.assign.return_value = AutoAssignResult(
            assignments=[
                NuggetAssignment(0, 'Test fact', AssignmentLabel.SUPPORT),
            ]
        )
        mock_assigner_cls.return_value = mock_assigner

        result = build_consensus_pool(topic_with_articles.id)

        assert 'nuggets' in result
        assert ConsensusPool.objects.filter(
            topic=topic_with_articles
        ).exists()

    def test_task_handles_missing_topic(self, db):
        from apps.consensus.tasks import build_consensus_pool
        result = build_consensus_pool(99999)
        assert result is None


class TestBuildPoolsForReadyTopicsTask:
    """Tests for the build_pools_for_ready_topics task."""

    @patch('apps.consensus.tasks.build_consensus_pool')
    def test_queues_ready_topics(
        self, mock_task, topic_with_3_articles
    ):
        from apps.consensus.tasks import build_pools_for_ready_topics
        mock_task.delay = MagicMock()

        result = build_pools_for_ready_topics(min_sources=3)

        assert 'Queued 1' in result
        mock_task.delay.assert_called_once_with(topic_with_3_articles.id)

    @patch('apps.consensus.tasks.build_consensus_pool')
    def test_skips_topics_with_existing_pool(
        self, mock_task, topic_with_3_articles
    ):
        from apps.consensus.tasks import build_pools_for_ready_topics
        mock_task.delay = MagicMock()

        ConsensusPool.objects.create(
            topic=topic_with_3_articles,
            status=ConsensusPool.Status.COMPLETE,
        )

        result = build_pools_for_ready_topics(min_sources=3)

        assert 'Queued 0' in result
        mock_task.delay.assert_not_called()

    @patch('apps.consensus.tasks.build_consensus_pool')
    def test_skips_topics_with_few_sources(
        self, mock_task, topic_with_articles
    ):
        """topic_with_articles has only 2 sources, needs 3."""
        from apps.consensus.tasks import build_pools_for_ready_topics
        mock_task.delay = MagicMock()

        result = build_pools_for_ready_topics(min_sources=3)

        assert 'Queued 0' in result
        mock_task.delay.assert_not_called()


# ---------------------------------------------------------------------------
# News prompt test
# ---------------------------------------------------------------------------

class TestNewsPrompt:
    """Test that the news domain prompt is registered."""

    def test_news_prompt_exists(self):
        from apps.extraction.services.prompts import get_default_prompts
        system, user = get_default_prompts('news')
        assert 'journalist' in system.lower()
        assert '{text}' in user


# ---------------------------------------------------------------------------
# compute_scores formula tests
# ---------------------------------------------------------------------------

class TestComputeScores:
    """Tests for the compute_scores formula."""

    def test_basic_coverage_no_partial(self):
        """Support and not_support with no partial."""
        from apps.consensus.services.pool_builder import compute_scores
        result = compute_scores(
            support=7, partial=0, not_support=3, total=10,
            vital_support=3, vital_partial=0, vital_total=4,
            partial_weight=0.5, vital_weight=2.0,
        )
        assert abs(result['coverage_score'] - 0.7) < 1e-5
        assert abs(result['omission_rate'] - 0.3) < 1e-5

    def test_partial_support_weighted(self):
        """Partial support counted at 0.5."""
        from apps.consensus.services.pool_builder import compute_scores
        result = compute_scores(
            support=5, partial=4, not_support=1, total=10,
            vital_support=2, vital_partial=1, vital_total=3,
            partial_weight=0.5, vital_weight=2.0,
        )
        # coverage = (5 + 0.5*4) / 10 = 7/10 = 0.7
        assert abs(result['coverage_score'] - 0.7) < 1e-5
        assert abs(result['omission_rate'] - 0.3) < 1e-5

    def test_partial_full_weight(self):
        """With partial_weight=1.0, partial counts as full support."""
        from apps.consensus.services.pool_builder import compute_scores
        result = compute_scores(
            support=5, partial=4, not_support=1, total=10,
            vital_support=2, vital_partial=1, vital_total=3,
            partial_weight=1.0, vital_weight=2.0,
        )
        assert abs(result['coverage_score'] - 0.9) < 1e-5

    def test_vital_weighting(self):
        """Vital nuggets weighted more heavily in weighted_coverage_score."""
        from apps.consensus.services.pool_builder import compute_scores
        # Article covers all vital (3/3) but misses all okay (0/2)
        result = compute_scores(
            support=3, partial=0, not_support=2, total=5,
            vital_support=3, vital_partial=0, vital_total=3,
            partial_weight=0.5, vital_weight=2.0,
        )
        # coverage_score = 3/5 = 0.6
        assert abs(result['coverage_score'] - 0.6) < 1e-5
        # weighted = (3*2 + 0) / (3*2 + 2) = 6/8 = 0.75
        assert abs(result['weighted_coverage_score'] - 0.75) < 1e-5

    def test_zero_total(self):
        """No nuggets should give perfect scores."""
        from apps.consensus.services.pool_builder import compute_scores
        result = compute_scores(
            support=0, partial=0, not_support=0, total=0,
            vital_support=0, vital_partial=0, vital_total=0,
        )
        assert result['coverage_score'] == 1.0
        assert result['omission_rate'] == 0.0
        assert result['vital_omission_rate'] == 0.0
        assert result['weighted_coverage_score'] == 1.0

    def test_all_partial(self):
        """All nuggets partially supported."""
        from apps.consensus.services.pool_builder import compute_scores
        result = compute_scores(
            support=0, partial=10, not_support=0, total=10,
            vital_support=0, vital_partial=3, vital_total=3,
            partial_weight=0.5, vital_weight=2.0,
        )
        assert abs(result['coverage_score'] - 0.5) < 1e-5
        assert abs(result['vital_omission_rate'] - 0.5) < 1e-5

    def test_no_vital_nuggets(self):
        """Topic with no vital nuggets — weighted equals raw."""
        from apps.consensus.services.pool_builder import compute_scores
        result = compute_scores(
            support=5, partial=3, not_support=2, total=10,
            vital_support=0, vital_partial=0, vital_total=0,
            partial_weight=0.5, vital_weight=2.0,
        )
        assert result['vital_omission_rate'] == 0.0
        # weighted = same as coverage since no vital nuggets
        assert abs(result['weighted_coverage_score'] - result['coverage_score']) < 1e-5


# ---------------------------------------------------------------------------
# Proportional vital threshold tests
# ---------------------------------------------------------------------------

class TestProportionalVitalThreshold:
    """Tests for the _effective_vital_threshold method."""

    def test_small_source_count_uses_minimum(self):
        from apps.consensus.services.pool_builder import PoolBuilder
        builder = PoolBuilder(vital_threshold=3)
        # Formula: max(2, ceil(n * 0.4))
        assert builder._effective_vital_threshold(2) == 2
        assert builder._effective_vital_threshold(3) == 2
        assert builder._effective_vital_threshold(4) == 2
        assert builder._effective_vital_threshold(5) == 2

    def test_large_source_count_scales(self):
        from apps.consensus.services.pool_builder import PoolBuilder
        builder = PoolBuilder(vital_threshold=3)
        # Formula: max(2, ceil(n * 0.4))
        assert builder._effective_vital_threshold(6) == 3
        assert builder._effective_vital_threshold(8) == 4
        assert builder._effective_vital_threshold(10) == 4
        assert builder._effective_vital_threshold(20) == 8


# ---------------------------------------------------------------------------
# OmissionScore weighted_coverage_score property tests
# ---------------------------------------------------------------------------

class TestOmissionScoreWeightedProperty:
    """Tests for the weighted_coverage_score property on OmissionScore."""

    def test_weighted_property_computes_from_stored_counts(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        score = OmissionScore.objects.create(
            pool=pool, article=article_npr,
            support_count=3, partial_support_count=0, not_support_count=2,
            total_nuggets=5,
            vital_support_count=3, vital_partial_support_count=0, vital_total=3,
        )
        # weighted = (3*2 + 0) / (3*2 + 2) = 6/8 = 0.75
        assert abs(score.weighted_coverage_score - 0.75) < 1e-5

    def test_weighted_property_zero_nuggets(self, topic, article_npr):
        pool = ConsensusPool.objects.create(topic=topic)
        score = OmissionScore.objects.create(
            pool=pool, article=article_npr,
            total_nuggets=0,
        )
        assert score.weighted_coverage_score == 1.0
