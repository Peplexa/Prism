"""Tests for tone and framing analysis."""

import pytest
from unittest.mock import patch, MagicMock
from django.utils import timezone

from apps.analysis.models import ArticleAnalysis
from apps.analysis.tasks import analyze_article, analyze_unanalyzed_articles


class TestArticleAnalysisModel:
    """Tests for the ArticleAnalysis model."""

    def test_create_analysis(self, article_npr):
        analysis = ArticleAnalysis.objects.create(
            article=article_npr,
            status=ArticleAnalysis.AnalysisStatus.COMPLETE,
            subjectivity_ratio=0.35,
            sentence_count=20,
            subjective_sentence_count=7,
            avg_subjectivity_confidence=0.91,
            leaning_left=0.15,
            leaning_center=0.70,
            leaning_right=0.15,
            framing_chunks_analyzed=2,
            analyzed_at=timezone.now(),
        )
        assert analysis.id is not None
        assert analysis.article == article_npr

    def test_dominant_leaning_center(self, article_npr):
        analysis = ArticleAnalysis.objects.create(
            article=article_npr,
            leaning_left=0.15,
            leaning_center=0.70,
            leaning_right=0.15,
        )
        assert analysis.dominant_leaning == 'center'

    def test_dominant_leaning_left(self, article_fox):
        analysis = ArticleAnalysis.objects.create(
            article=article_fox,
            leaning_left=0.80,
            leaning_center=0.10,
            leaning_right=0.10,
        )
        assert analysis.dominant_leaning == 'left'

    def test_dominant_leaning_none_when_not_analyzed(self, article_npr):
        analysis = ArticleAnalysis.objects.create(article=article_npr)
        assert analysis.dominant_leaning is None

    def test_tone_label_highly_objective(self, article_npr):
        analysis = ArticleAnalysis.objects.create(
            article=article_npr,
            subjectivity_ratio=0.08,
        )
        assert analysis.tone_label == 'Highly Objective'

    def test_tone_label_mostly_objective(self, article_npr):
        analysis = ArticleAnalysis.objects.create(
            article=article_npr,
            subjectivity_ratio=0.12,
        )
        assert analysis.tone_label == 'Mostly Objective'

    def test_tone_label_mixed(self, article_npr):
        analysis = ArticleAnalysis.objects.create(
            article=article_npr,
            subjectivity_ratio=0.18,
        )
        assert analysis.tone_label == 'Mixed'

    def test_tone_label_mostly_subjective(self, article_fox):
        analysis = ArticleAnalysis.objects.create(
            article=article_fox,
            subjectivity_ratio=0.25,
        )
        assert analysis.tone_label == 'Mostly Subjective'

    def test_tone_label_highly_subjective(self, article_fox):
        analysis = ArticleAnalysis.objects.create(
            article=article_fox,
            subjectivity_ratio=0.35,
        )
        assert analysis.tone_label == 'Highly Subjective'

    def test_tone_label_none_when_not_analyzed(self, article_npr):
        analysis = ArticleAnalysis.objects.create(article=article_npr)
        assert analysis.tone_label is None

    def test_one_to_one_constraint(self, article_npr):
        ArticleAnalysis.objects.create(article=article_npr)
        with pytest.raises(Exception):
            ArticleAnalysis.objects.create(article=article_npr)

    def test_str_with_ratio(self, article_npr):
        analysis = ArticleAnalysis.objects.create(
            article=article_npr,
            subjectivity_ratio=0.35,
        )
        assert 'subj=0.35' in str(analysis)

    def test_str_without_ratio(self, article_npr):
        analysis = ArticleAnalysis.objects.create(article=article_npr)
        assert 'pending' in str(analysis)

    def test_related_name_from_article(self, article_npr):
        analysis = ArticleAnalysis.objects.create(
            article=article_npr,
            subjectivity_ratio=0.5,
        )
        assert article_npr.analysis == analysis


class TestToneAnalyzer:
    """Tests for the ToneAnalyzer service."""

    @patch('apps.analysis.services.tone._get_model_and_tokenizer')
    def test_analyze_returns_result(self, mock_get):
        import torch
        from apps.analysis.services.tone import ToneAnalyzer, ToneResult

        mock_model = MagicMock()
        mock_model.config.id2label = {0: 'OBJ', 1: 'SUBJECTIVE'}
        mock_outputs = MagicMock()
        # 3 sentences: first objective, second subjective, third objective
        mock_outputs.logits = torch.tensor([
            [2.0, -2.0],   # high obj
            [-2.0, 2.0],   # high subj
            [2.0, -2.0],   # high obj
        ])
        mock_model.return_value = mock_outputs

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            'input_ids': torch.tensor([[1, 2], [3, 4], [5, 6]]),
            'attention_mask': torch.tensor([[1, 1], [1, 1], [1, 1]]),
        }

        mock_get.return_value = (mock_model, mock_tokenizer)

        analyzer = ToneAnalyzer()
        result = analyzer.analyze(
            "This is an objective sentence about news. "
            "This is emotionally charged and very upsetting! "
            "Another factual statement about the world here."
        )

        assert isinstance(result, ToneResult)
        assert result.sentence_count == 3
        assert result.subjective_count == 1
        assert abs(result.subjectivity_ratio - 1 / 3) < 0.01

    def test_analyze_empty_text(self):
        from apps.analysis.services.tone import ToneAnalyzer

        analyzer = ToneAnalyzer()
        result = analyzer.analyze("")

        assert result.sentence_count == 0
        assert result.subjectivity_ratio == 0.0

    def test_filters_short_fragments(self):
        from apps.analysis.services.tone import ToneAnalyzer

        mock_pipe = MagicMock()
        mock_pipe.return_value = [
            {'label': 'OBJ', 'score': 0.95},
        ]

        analyzer = ToneAnalyzer.__new__(ToneAnalyzer)
        analyzer.model_name = 'test-model'
        analyzer.confidence_threshold = 0.75
        analyzer.min_words = 5
        analyzer._pipe = mock_pipe

        # "Hi." is too short (< 5 words), only the long sentence should be analyzed
        result = analyzer.analyze(
            "Hi. This is a longer sentence that should be analyzed."
        )

        assert result.sentence_count == 1


class TestFramingAnalyzer:
    """Tests for the FramingAnalyzer service."""

    @patch('apps.analysis.services.framing._get_model_and_tokenizer')
    def test_analyze_returns_distribution(self, mock_get):
        import torch
        from apps.analysis.services.framing import FramingAnalyzer, FramingResult

        mock_model = MagicMock()
        mock_model.config.id2label = {0: 'left', 1: 'center', 2: 'right'}
        # Single sentence → model returns logits for 1 sentence
        mock_outputs = MagicMock()
        mock_outputs.logits = torch.tensor([[0.2, 0.6, 0.2]])  # softmax-ish
        mock_model.return_value = mock_outputs

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {'input_ids': torch.tensor([[1, 2, 3]]), 'attention_mask': torch.tensor([[1, 1, 1]])}

        mock_get.return_value = (mock_model, mock_tokenizer)

        analyzer = FramingAnalyzer()
        result = analyzer.analyze("Some political text about policy and governance here today.")

        assert isinstance(result, FramingResult)
        assert result.chunks_analyzed == 1
        # Exact values depend on softmax of [0.2, 0.6, 0.2]
        assert result.center > result.left
        assert result.center > result.right

    @patch('apps.analysis.services.framing._get_model_and_tokenizer')
    def test_analyze_averages_sentences(self, mock_get):
        import torch
        from apps.analysis.services.framing import FramingAnalyzer

        mock_model = MagicMock()
        mock_model.config.id2label = {0: 'left', 1: 'center', 2: 'right'}
        # Two sentences → model returns logits for 2 sentences
        mock_outputs = MagicMock()
        mock_outputs.logits = torch.tensor([
            [2.0, 0.0, 0.0],   # strongly left
            [0.0, 0.0, 2.0],   # strongly right
        ])
        mock_model.return_value = mock_outputs

        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = {
            'input_ids': torch.tensor([[1, 2, 3], [4, 5, 6]]),
            'attention_mask': torch.tensor([[1, 1, 1], [1, 1, 1]]),
        }

        mock_get.return_value = (mock_model, mock_tokenizer)

        analyzer = FramingAnalyzer()
        # Two sentences (splitter needs .!? followed by uppercase)
        result = analyzer.analyze("First sentence about policy and governance today. Second sentence about different political topics here.")

        assert result.chunks_analyzed == 2
        # Average of strongly-left and strongly-right should balance out
        assert abs(result.left - result.right) < 0.01

    def test_analyze_empty_text(self):
        from apps.analysis.services.framing import FramingAnalyzer

        analyzer = FramingAnalyzer()
        result = analyzer.analyze("")

        assert result.chunks_analyzed == 0
        assert result.left == 0.0


def _make_mock_tone_analyzer(return_value):
    """Create a ToneAnalyzer with a mocked pipeline."""
    from apps.analysis.services.tone import ToneAnalyzer
    mock_pipe = MagicMock()
    mock_pipe.return_value = return_value
    analyzer = ToneAnalyzer.__new__(ToneAnalyzer)
    analyzer.model_name = 'test-model'
    analyzer.confidence_threshold = 0.65
    analyzer.min_words = 5
    analyzer._pipe = mock_pipe
    return analyzer


def _make_mock_framing_analyzer(return_value):
    """Create a FramingAnalyzer with a mocked pipeline."""
    from apps.analysis.services.framing import FramingAnalyzer
    mock_pipe = MagicMock()
    mock_pipe.return_value = return_value
    analyzer = FramingAnalyzer.__new__(FramingAnalyzer)
    analyzer.model_name = 'test-model'
    analyzer.tokenizer_name = 'test-tokenizer'
    analyzer._pipe = mock_pipe
    return analyzer


class TestAnalyzeArticleTask:
    """Tests for the analyze_article Celery task."""

    def test_analyze_creates_complete_record(self, article_npr):
        tone_instance = _make_mock_tone_analyzer(
            [{'label': 'OBJ', 'score': 0.95}] * 10
        )
        # Article fixture is ~500 words = 2 chunks, so mock returns nested lists
        framing_instance = _make_mock_framing_analyzer([
            [
                {'label': '0', 'score': 0.2},
                {'label': '1', 'score': 0.6},
                {'label': '2', 'score': 0.2},
            ],
            [
                {'label': '0', 'score': 0.2},
                {'label': '1', 'score': 0.6},
                {'label': '2', 'score': 0.2},
            ],
        ])

        with patch('apps.analysis.services.ToneAnalyzer', return_value=tone_instance), \
             patch('apps.analysis.services.FramingAnalyzer', return_value=framing_instance):
            result = analyze_article(article_npr.id)

        assert 'complete' in result.lower()
        analysis = ArticleAnalysis.objects.get(article=article_npr)
        assert analysis.status == ArticleAnalysis.AnalysisStatus.COMPLETE
        assert analysis.subjectivity_ratio is not None
        assert analysis.leaning_center is not None
        assert analysis.analyzed_at is not None

    def test_analyze_missing_article(self, db):
        result = analyze_article(99999)
        assert result is None

    def test_analyze_empty_content(self, source_npr):
        from apps.articles.models import Article
        article = Article.objects.create(
            source=source_npr,
            title='Empty',
            url='https://npr.org/empty',
            content='',
            status=Article.ProcessingStatus.COMPLETE,
        )
        result = analyze_article(article.id)
        assert result == "No content"

    def test_partial_failure_saves_what_succeeded(self, article_npr):
        from apps.analysis.services.tone import ToneResult
        from apps.analysis.services.framing import FramingAnalyzer

        mock_tone = MagicMock()
        mock_tone.analyze.return_value = ToneResult(
            subjectivity_ratio=0.2, sentence_count=5,
            subjective_count=1, avg_confidence=0.9,
        )

        mock_framing = MagicMock(spec=FramingAnalyzer)
        mock_framing.analyze.side_effect = RuntimeError("Model load failed")

        with patch('apps.analysis.services.ToneAnalyzer', return_value=mock_tone), \
             patch('apps.analysis.services.FramingAnalyzer', return_value=mock_framing):
            result = analyze_article(article_npr.id)

        analysis = ArticleAnalysis.objects.get(article=article_npr)
        assert analysis.status == ArticleAnalysis.AnalysisStatus.FAILED
        assert analysis.subjectivity_ratio is not None  # Tone succeeded
        assert 'Framing' in analysis.error_message


class TestAnalyzeUnanalyzedTask:
    """Tests for the batch analysis task."""

    @patch('apps.analysis.tasks.analyze_article')
    def test_queues_unanalyzed_articles(self, mock_task, article_npr, article_fox):
        mock_task.delay = MagicMock()

        result = analyze_unanalyzed_articles(limit=10)

        assert 'Queued 2' in result
        assert mock_task.delay.call_count == 2

    @patch('apps.analysis.tasks.analyze_article')
    def test_skips_already_analyzed(self, mock_task, article_npr):
        mock_task.delay = MagicMock()

        ArticleAnalysis.objects.create(
            article=article_npr,
            status=ArticleAnalysis.AnalysisStatus.COMPLETE,
        )

        result = analyze_unanalyzed_articles(limit=10)

        assert 'Queued 0' in result
        mock_task.delay.assert_not_called()

    @patch('apps.analysis.tasks.analyze_article')
    def test_respects_limit(self, mock_task, article_npr, article_fox):
        mock_task.delay = MagicMock()

        result = analyze_unanalyzed_articles(limit=1)

        assert 'Queued 1' in result
        assert mock_task.delay.call_count == 1
