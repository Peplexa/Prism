"""Tests for the NuggetPostProcessor service."""

import pytest
from unittest.mock import patch, MagicMock

from apps.consensus.models import (
    ConsensusPool,
    ConsensusNugget,
    RawNugget,
)

# Pre-import so @patch decorators can resolve dotted paths
import apps.consensus.services.post_processor  # noqa: F401


def _create_pool_with_nuggets(topic, article_npr, article_fox, raw_per_cluster=None):
    """
    Helper: create a pool with consensus nuggets and linked raw nuggets.

    raw_per_cluster: list of lists, where each inner list is
    [(article, text), ...] for that cluster's raw nuggets.
    If None, creates a default setup with 3 clusters (2 multi-member, 1 single).
    """
    pool = ConsensusPool.objects.create(
        topic=topic,
        status=ConsensusPool.Status.DEDUPLICATING,
        similarity_threshold=0.85,
    )

    if raw_per_cluster is None:
        raw_per_cluster = [
            # Cluster 0: multi-member (NPR + Fox)
            [
                (article_npr, 'Palat scored with 7:42 left in the third'),
                (article_fox, 'Palat gave Czechia a 3-2 lead'),
            ],
            # Cluster 1: multi-member (NPR + Fox)
            [
                (article_npr, 'Gudas is a Czech defenseman'),
                (article_fox, 'Gudas is a veteran defenseman'),
            ],
            # Cluster 2: single-member
            [
                (article_npr, 'The arena was sold out'),
            ],
        ]

    for cluster_id, members in enumerate(raw_per_cluster):
        source_names = sorted(set(a.source.name for a, _ in members))
        cn = ConsensusNugget.objects.create(
            pool=pool,
            nugget_text=members[0][1],  # first member as representative
            importance=(
                ConsensusNugget.Importance.VITAL
                if len(source_names) >= 2
                else ConsensusNugget.Importance.OKAY
            ),
            source_count=len(source_names),
            source_names=source_names,
            cluster_id=cluster_id,
        )
        for article, text in members:
            RawNugget.objects.create(
                pool=pool,
                article=article,
                nugget_text=text,
                nugget_type='claim',
                consensus_nugget=cn,
            )

    pool.nugget_count = len(raw_per_cluster)
    pool.save(update_fields=['nugget_count'])
    return pool


# ---------------------------------------------------------------------------
# Merge tests
# ---------------------------------------------------------------------------

class TestMergeClusters:

    @patch('apps.consensus.services.post_processor.get_llm_client')
    def test_merge_single_member_clusters_skipped(
        self, mock_get_client, topic, article_npr, article_fox
    ):
        """Single-member clusters should not trigger LLM calls."""
        pool = _create_pool_with_nuggets(
            topic, article_npr, article_fox,
            raw_per_cluster=[
                [(article_npr, 'Fact A')],
                [(article_fox, 'Fact B')],
            ],
        )

        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        from apps.consensus.services.post_processor import NuggetPostProcessor
        processor = NuggetPostProcessor(backend='deepseek')
        result = processor._merge_clusters(pool)

        assert result == 0
        mock_client.generate.assert_not_called()

    @patch('apps.consensus.services.post_processor.get_llm_client')
    def test_merge_updates_nugget_text(
        self, mock_get_client, topic, article_npr, article_fox
    ):
        """Merge should update ConsensusNugget.nugget_text with LLM response."""
        pool = _create_pool_with_nuggets(topic, article_npr, article_fox)

        mock_client = MagicMock()
        mock_client.generate.return_value = (
            '["Palat scored to give Czechia a 3-2 lead with 7:42 left", '
            '"Gudas is a veteran Czech defenseman"]'
        )
        mock_get_client.return_value = mock_client

        from apps.consensus.services.post_processor import NuggetPostProcessor
        processor = NuggetPostProcessor(backend='deepseek')
        merged_count = processor._merge_clusters(pool)

        assert merged_count == 2

        nuggets = list(pool.nuggets.order_by('cluster_id'))
        assert 'Palat scored to give Czechia a 3-2 lead' in nuggets[0].nugget_text
        assert 'veteran Czech defenseman' in nuggets[1].nugget_text
        # Single-member cluster unchanged
        assert nuggets[2].nugget_text == 'The arena was sold out'

    @patch('apps.consensus.services.post_processor.get_llm_client')
    def test_merge_preserves_count(
        self, mock_get_client, topic, article_npr, article_fox
    ):
        """Merging should NOT change the number of ConsensusNuggets."""
        pool = _create_pool_with_nuggets(topic, article_npr, article_fox)
        count_before = pool.nuggets.count()

        mock_client = MagicMock()
        mock_client.generate.return_value = '["Merged A", "Merged B"]'
        mock_get_client.return_value = mock_client

        from apps.consensus.services.post_processor import NuggetPostProcessor
        processor = NuggetPostProcessor(backend='deepseek')
        processor._merge_clusters(pool)

        assert pool.nuggets.count() == count_before

    @patch('apps.consensus.services.post_processor.get_llm_client')
    def test_merge_raw_nuggets_untouched(
        self, mock_get_client, topic, article_npr, article_fox
    ):
        """RawNugget rows should not be modified by merging."""
        pool = _create_pool_with_nuggets(topic, article_npr, article_fox)
        raw_texts_before = list(
            RawNugget.objects.filter(pool=pool)
            .order_by('id')
            .values_list('nugget_text', flat=True)
        )

        mock_client = MagicMock()
        mock_client.generate.return_value = '["Merged A", "Merged B"]'
        mock_get_client.return_value = mock_client

        from apps.consensus.services.post_processor import NuggetPostProcessor
        processor = NuggetPostProcessor(backend='deepseek')
        processor._merge_clusters(pool)

        raw_texts_after = list(
            RawNugget.objects.filter(pool=pool)
            .order_by('id')
            .values_list('nugget_text', flat=True)
        )
        assert raw_texts_before == raw_texts_after


class TestMergeJsonParseFallback:

    def test_clean_json(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_json_string_array(
            '["fact one", "fact two"]', 2
        )
        assert result == ['fact one', 'fact two']

    def test_markdown_wrapped_json(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_json_string_array(
            '```json\n["fact one", "fact two"]\n```', 2
        )
        assert result == ['fact one', 'fact two']

    def test_extra_text_around_array(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_json_string_array(
            'Here are the merged facts:\n["fact one", "fact two"]\nDone.', 2
        )
        assert result == ['fact one', 'fact two']

    def test_truncated_response_pads_with_empty(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_json_string_array(
            '["fact one"]', 3
        )
        assert len(result) == 3
        assert result[0] == 'fact one'
        assert result[1] == ''
        assert result[2] == ''

    def test_total_failure_returns_empty_strings(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_json_string_array(
            'I cannot process this request.', 2
        )
        assert result == ['', '']

    def test_thinking_tags_stripped(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_json_string_array(
            '<think>Let me think...</think>["fact one", "fact two"]', 2
        )
        assert result == ['fact one', 'fact two']


# ---------------------------------------------------------------------------
# Tier tests
# ---------------------------------------------------------------------------

class TestTierAssignment:

    @patch('apps.consensus.services.post_processor.get_llm_client')
    def test_tier_assignment_correct_count(
        self, mock_get_client, topic, article_npr, article_fox
    ):
        """All nuggets should get tier values matching LLM response."""
        pool = _create_pool_with_nuggets(topic, article_npr, article_fox)

        mock_client = MagicMock()
        mock_client.generate.return_value = '[1, 2, 3]'
        mock_get_client.return_value = mock_client

        from apps.consensus.services.post_processor import NuggetPostProcessor
        processor = NuggetPostProcessor(backend='deepseek')
        tier1, tier2, tier3 = processor._assign_tiers(pool)

        assert tier1 == 1
        assert tier2 == 1
        assert tier3 == 1

        # Verify DB state
        nuggets = list(pool.nuggets.order_by('-source_count', 'id'))
        tiers = [n.tier for n in nuggets]
        assert 1 in tiers
        assert 2 in tiers
        assert 3 in tiers


class TestTierParseFallback:

    def test_clean_json(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_tier_array('[1, 2, 3, 1]', 4)
        assert result == [1, 2, 3, 1]

    def test_wrong_length_pads_with_3(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_tier_array('[1, 2]', 5)
        assert len(result) == 5
        assert result == [1, 2, 3, 3, 3]

    def test_invalid_values_default_to_3(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_tier_array('[1, 5, "high", 2]', 4)
        assert result == [1, 3, 3, 2]

    def test_line_by_line_fallback(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_tier_array(
            'Fact 1: Tier 1\nFact 2: Tier 2\nFact 3: Tier 3', 3
        )
        assert result == [1, 2, 3]

    def test_total_failure_defaults_all_to_3(self):
        from apps.consensus.services.post_processor import NuggetPostProcessor
        result = NuggetPostProcessor._parse_tier_array(
            'I cannot assign tiers.', 4
        )
        assert result == [3, 3, 3, 3]


class TestTierRetierPass:

    @patch('apps.consensus.services.post_processor.get_llm_client')
    def test_retier_reduces_tier1_count(
        self, mock_get_client, topic, article_npr, article_fox
    ):
        """When chunked tiering produces too many tier-1 facts, re-tier should reduce."""
        # Create a pool with 5 nuggets
        pool = _create_pool_with_nuggets(
            topic, article_npr, article_fox,
            raw_per_cluster=[
                [(article_npr, f'Fact {i}'), (article_fox, f'Fact {i} v2')]
                for i in range(5)
            ],
        )

        mock_client = MagicMock()
        # First call: tier assignment returns too many tier-1s (all 5)
        # Second call: re-tier selects only fact 1 and 3 (1-indexed)
        mock_client.generate.side_effect = [
            '[1, 1, 1, 1, 1]',  # all tier 1
            '[1, 3]',           # select facts 1 and 3
        ]
        mock_get_client.return_value = mock_client

        from apps.consensus.services.post_processor import NuggetPostProcessor
        processor = NuggetPostProcessor(backend='deepseek')
        processor.tier1_target = 2  # only want 2 headline facts

        # Use chunked tiering to trigger re-tier
        nuggets = list(pool.nuggets.order_by('-source_count', 'id'))
        result = processor._tier_chunked(pool, nuggets, chunk_size=5)

        # Should have exactly 2 tier-1 facts (indices 0 and 2, i.e. 1-indexed 1 and 3)
        tier1_count = sum(1 for t in result if t == 1)
        assert tier1_count == 2


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestProcessNonfatalOnError:

    @patch('apps.consensus.services.post_processor.get_llm_client')
    def test_process_nonfatal_on_llm_error(
        self, mock_get_client, topic, article_npr, article_fox
    ):
        """If LLM raises an error, process() should not crash."""
        pool = _create_pool_with_nuggets(topic, article_npr, article_fox)
        original_texts = {
            cn.id: cn.nugget_text
            for cn in pool.nuggets.all()
        }

        mock_client = MagicMock()
        mock_client.generate.side_effect = ConnectionError("API unavailable")
        mock_get_client.return_value = mock_client

        from apps.consensus.services.post_processor import NuggetPostProcessor
        processor = NuggetPostProcessor(backend='deepseek')
        result = processor.process(pool)

        # Should not raise, merge count is 0
        assert result.nuggets_merged == 0

        # Original texts preserved
        for cn in pool.nuggets.all():
            assert cn.nugget_text == original_texts[cn.id]

        # Tiers default to 3 on error
        for cn in pool.nuggets.all():
            assert cn.tier == 3


class TestRebuildClearsTiers:

    @patch('apps.consensus.services.pool_builder.NuggetPostProcessor')
    @patch('apps.consensus.services.pool_builder.AutoAssigner')
    @patch('apps.consensus.services.pool_builder.NuggetDeduplicator')
    @patch('apps.consensus.services.pool_builder.NuggetExtractor')
    def test_rebuild_clears_tiers(
        self,
        mock_extractor_cls, mock_dedup_cls, mock_assigner_cls,
        mock_processor_cls,
        topic_with_articles,
    ):
        """Rebuilding a pool should start with tier=None on all nuggets."""
        from apps.consensus.services.pool_builder import PoolBuilder
        from apps.consensus.services.deduplicator import (
            DeduplicationResult, NuggetCluster,
        )
        from apps.evaluation.services.auto_assigner import (
            AutoAssignResult, NuggetAssignment, AssignmentLabel,
        )

        # Create initial pool with tiers set
        old_pool = ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
        )
        ConsensusNugget.objects.create(
            pool=old_pool, nugget_text='Old fact', tier=1,
            source_count=2, source_names=['NPR', 'Fox News'],
        )

        # Setup mocks for rebuild
        mock_extractor = MagicMock()
        mock_extractor.extract.return_value = [
            {'fact': 'New fact', 'type': 'claim'},
        ]
        mock_extractor_cls.return_value = mock_extractor

        mock_dedup = MagicMock()
        mock_dedup.deduplicate.return_value = DeduplicationResult(
            clusters=[
                NuggetCluster(
                    cluster_id=0,
                    representative_text='New fact',
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
                NuggetAssignment(0, 'New fact', AssignmentLabel.SUPPORT),
            ]
        )
        mock_assigner_cls.return_value = mock_assigner

        # Mock post-processor to verify it receives nuggets with tier=None
        mock_processor = MagicMock()
        mock_processor_cls.return_value = mock_processor

        def check_tiers_are_none(pool):
            for cn in pool.nuggets.all():
                assert cn.tier is None, f"Expected tier=None, got {cn.tier}"
            from apps.consensus.services.post_processor import PostProcessingResult
            return PostProcessingResult(0, 0, 0, 0)

        mock_processor.process.side_effect = check_tiers_are_none

        builder = PoolBuilder(backend='deepseek')
        new_pool = builder.build(topic_with_articles.id, rebuild=True)

        assert new_pool.status == ConsensusPool.Status.COMPLETE
        # Old pool should be gone
        assert not ConsensusPool.objects.filter(id=old_pool.id).exists()
        # Post-processor was called
        mock_processor.process.assert_called_once()


class TestUntieredPoolBackwardCompat:

    def test_summarizer_handles_none_tiers(self, topic):
        """Summarizer should fall back to VITAL/OKAY format when tiers are None."""
        pool = ConsensusPool.objects.create(
            topic=topic,
            status=ConsensusPool.Status.COMPLETE,
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='A vital fact',
            importance=ConsensusNugget.Importance.VITAL,
            source_count=3, source_names=['NPR', 'Fox', 'Reuters'],
            tier=None,
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='An okay fact',
            importance=ConsensusNugget.Importance.OKAY,
            source_count=1, source_names=['NPR'],
            tier=None,
        )

        from apps.summary.services.summarizer import NeutralSummarizer
        nuggets = list(pool.nuggets.order_by('-source_count'))
        formatted = NeutralSummarizer._format_nuggets(nuggets)

        assert '[VITAL]' in formatted
        assert '[OKAY]' in formatted
        assert 'HEADLINE' not in formatted

    def test_summarizer_uses_tiers_when_present(self, topic):
        """Summarizer should use tier format when tiers are set."""
        pool = ConsensusPool.objects.create(
            topic=topic,
            status=ConsensusPool.Status.COMPLETE,
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='Headline fact',
            importance=ConsensusNugget.Importance.VITAL,
            source_count=3, source_names=['NPR', 'Fox', 'Reuters'],
            tier=1,
        )
        ConsensusNugget.objects.create(
            pool=pool, nugget_text='Detail fact',
            importance=ConsensusNugget.Importance.OKAY,
            source_count=1, source_names=['NPR'],
            tier=3,
        )

        from apps.summary.services.summarizer import NeutralSummarizer
        nuggets = list(pool.nuggets.order_by('tier', '-source_count'))
        formatted = NeutralSummarizer._format_nuggets(nuggets)

        assert 'HEADLINE FACTS' in formatted
        assert 'DETAIL FACTS' in formatted
        assert '[VITAL]' not in formatted
