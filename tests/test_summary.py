"""Tests for neutral summary generation."""

import pytest
from unittest.mock import patch, MagicMock
from django.utils import timezone

from apps.summary.models import NeutralSummary
from apps.consensus.models import ConsensusPool, ConsensusNugget

# Pre-import subpackage modules so @patch decorators can resolve dotted paths
import apps.summary.services.summarizer  # noqa: F401


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class TestNeutralSummaryModel:
    """Tests for the NeutralSummary model."""

    def test_create_summary(self, topic):
        summary = NeutralSummary.objects.create(
            topic=topic,
            status=NeutralSummary.Status.COMPLETE,
            summary_text='A neutral summary of the event.',
            nuggets_used=5,
            model_name='deepseek-chat',
            generated_at=timezone.now(),
        )
        assert summary.id is not None
        assert summary.topic == topic
        assert summary.nuggets_used == 5

    def test_str_representation(self, topic):
        summary = NeutralSummary.objects.create(topic=topic)
        assert 'Test Topic' in str(summary)
        assert 'pending' in str(summary)

    def test_one_to_one_constraint(self, topic):
        NeutralSummary.objects.create(topic=topic)
        with pytest.raises(Exception):
            NeutralSummary.objects.create(topic=topic)


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------

class TestNeutralSummarizer:
    """Tests for the NeutralSummarizer service."""

    @patch('apps.summary.services.summarizer.get_llm_client')
    def test_generate_summary(self, mock_get_client, topic_with_articles):
        """Test successful summary generation."""
        pool = ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
            nugget_count=2,
        )
        ConsensusNugget.objects.create(
            pool=pool,
            nugget_text='The president signed the bill',
            importance='vital',
            source_count=3,
            source_names=['NPR', 'Fox News', 'Reuters'],
        )
        ConsensusNugget.objects.create(
            pool=pool,
            nugget_text='The bill allocates $500 billion',
            importance='okay',
            source_count=1,
            source_names=['NPR'],
        )

        mock_client = MagicMock()
        mock_client.chat.return_value = 'The president signed a bill allocating $500 billion.'
        mock_get_client.return_value = mock_client

        from apps.summary.services.summarizer import NeutralSummarizer
        summarizer = NeutralSummarizer(backend='deepseek')
        summary = summarizer.generate(topic_with_articles.id)

        assert summary.status == NeutralSummary.Status.COMPLETE
        assert summary.summary_text == 'The president signed a bill allocating $500 billion.'
        assert summary.nuggets_used == 2
        assert summary.generated_at is not None

        # Verify LLM was called with proper prompt
        mock_client.chat.assert_called_once()
        call_args = mock_client.chat.call_args
        messages = call_args[1]['messages'] if 'messages' in call_args[1] else call_args[0][0]
        assert any('neutral' in m['content'].lower() for m in messages)

    def test_requires_consensus_pool(self, topic):
        """Should raise ValueError if topic has no consensus pool."""
        from apps.summary.services.summarizer import NeutralSummarizer
        summarizer = NeutralSummarizer(backend='deepseek')
        with pytest.raises(ValueError, match='no consensus pool'):
            summarizer.generate(topic.id)

    def test_requires_complete_pool(self, topic):
        """Should raise ValueError if consensus pool is not complete."""
        ConsensusPool.objects.create(
            topic=topic,
            status=ConsensusPool.Status.EXTRACTING,
        )
        from apps.summary.services.summarizer import NeutralSummarizer
        summarizer = NeutralSummarizer(backend='deepseek')
        with pytest.raises(ValueError, match='not complete'):
            summarizer.generate(topic.id)

    def test_skips_existing_summary(self, topic):
        """Should return existing summary if regenerate=False."""
        existing = NeutralSummary.objects.create(
            topic=topic,
            status=NeutralSummary.Status.COMPLETE,
            summary_text='Existing summary.',
        )
        from apps.summary.services.summarizer import NeutralSummarizer
        summarizer = NeutralSummarizer(backend='deepseek')
        result = summarizer.generate(topic.id, regenerate=False)
        assert result.id == existing.id


# ---------------------------------------------------------------------------
# Task tests
# ---------------------------------------------------------------------------

class TestGenerateSummaryTask:
    """Tests for the generate_summary Celery task."""

    @patch('apps.summary.services.summarizer.get_llm_client')
    def test_task_generates_summary(self, mock_get_client, topic_with_articles):
        pool = ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
            nugget_count=1,
        )
        ConsensusNugget.objects.create(
            pool=pool,
            nugget_text='A consensus fact',
            source_count=3,
            source_names=['NPR', 'Fox News', 'Reuters'],
            importance='vital',
        )

        mock_client = MagicMock()
        mock_client.chat.return_value = 'Summary text.'
        mock_get_client.return_value = mock_client

        from apps.summary.tasks import generate_summary
        result = generate_summary(topic_with_articles.id)

        assert 'complete' in result
        assert NeutralSummary.objects.filter(
            topic=topic_with_articles
        ).exists()

    def test_task_handles_missing_topic(self, db):
        from apps.summary.tasks import generate_summary
        result = generate_summary(99999)
        assert result is None


class TestGenerateMissingSummariesTask:
    """Tests for the generate_missing_summaries task."""

    @patch('apps.summary.tasks.generate_summary')
    def test_queues_topics_without_summaries(self, mock_task, topic_with_articles):
        ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
        )
        mock_task.delay = MagicMock()

        from apps.summary.tasks import generate_missing_summaries
        result = generate_missing_summaries()

        assert 'Queued 1' in result
        mock_task.delay.assert_called_once_with(topic_with_articles.id)

    @patch('apps.summary.tasks.generate_summary')
    def test_skips_topics_with_summaries(self, mock_task, topic_with_articles):
        ConsensusPool.objects.create(
            topic=topic_with_articles,
            status=ConsensusPool.Status.COMPLETE,
        )
        NeutralSummary.objects.create(
            topic=topic_with_articles,
            status=NeutralSummary.Status.COMPLETE,
        )
        mock_task.delay = MagicMock()

        from apps.summary.tasks import generate_missing_summaries
        result = generate_missing_summaries()

        assert 'Queued 0' in result
        mock_task.delay.assert_not_called()
