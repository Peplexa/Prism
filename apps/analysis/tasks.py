"""Celery tasks for article tone and framing analysis."""

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2)
def analyze_article(self, article_id):
    """
    Run tone and framing analysis on a single article.

    Creates or updates the ArticleAnalysis record.
    """
    from apps.articles.models import Article
    from apps.analysis.models import ArticleAnalysis
    from apps.analysis.services import ToneAnalyzer, FramingAnalyzer

    try:
        article = Article.objects.get(id=article_id)
    except Article.DoesNotExist:
        logger.error(f"Article {article_id} not found")
        return

    if not article.content:
        logger.warning(f"Article {article_id} has no content, skipping analysis")
        return "No content"

    analysis, _ = ArticleAnalysis.objects.get_or_create(article=article)
    analysis.status = ArticleAnalysis.AnalysisStatus.RUNNING
    analysis.error_message = ''
    analysis.save(update_fields=['status', 'error_message', 'updated_at'])

    errors = []

    # --- Tone analysis ---
    try:
        tone_analyzer = ToneAnalyzer()
        tone_result = tone_analyzer.analyze(article.content)
        analysis.subjectivity_ratio = tone_result.subjectivity_ratio
        analysis.sentence_count = tone_result.sentence_count
        analysis.subjective_sentence_count = tone_result.subjective_count
        analysis.avg_subjectivity_confidence = tone_result.avg_confidence
    except Exception as e:
        logger.error(f"Tone analysis failed for article {article_id}: {e}")
        errors.append(f"Tone: {e}")

    # --- Framing analysis ---
    try:
        framing_analyzer = FramingAnalyzer()
        framing_result = framing_analyzer.analyze(article.content)
        analysis.leaning_left = framing_result.left
        analysis.leaning_center = framing_result.center
        analysis.leaning_right = framing_result.right
        analysis.framing_chunks_analyzed = framing_result.chunks_analyzed
    except Exception as e:
        logger.error(f"Framing analysis failed for article {article_id}: {e}")
        errors.append(f"Framing: {e}")

    # Finalize
    analysis.analyzed_at = timezone.now()
    analysis.model_versions = {
        'tone': 'deepseek-chat',
        'framing': 'deepseek-chat',
    }

    if len(errors) >= 2:
        # Both analyses failed
        analysis.status = ArticleAnalysis.AnalysisStatus.FAILED
        analysis.error_message = '; '.join(errors)
        analysis.save()
        # Only retry if running as a Celery task (has request context)
        if hasattr(self, 'request') and self.request.id:
            raise self.retry(
                exc=Exception(analysis.error_message),
                countdown=60,
            )
        return f"Article {article_id}: failed"
    elif errors:
        # One analysis failed — save partial results
        analysis.status = ArticleAnalysis.AnalysisStatus.FAILED
        analysis.error_message = '; '.join(errors)
    else:
        analysis.status = ArticleAnalysis.AnalysisStatus.COMPLETE

    analysis.save()

    logger.info(f"Article {article_id} analysis: {analysis.status}")
    return f"Article {article_id}: {analysis.status}"


@shared_task
def analyze_unanalyzed_articles(limit=100):
    """
    Batch task: find articles without analysis and queue them.

    Catches articles that missed the post-ingestion trigger.
    """
    from apps.articles.models import Article

    articles = Article.objects.filter(
        status=Article.ProcessingStatus.COMPLETE,
        analysis__isnull=True,
    ).exclude(
        content=''
    ).values_list('id', flat=True)[:limit]

    count = 0
    for article_id in articles:
        analyze_article.delay(article_id)
        count += 1

    logger.info(f"Queued {count} articles for analysis")
    return f"Queued {count} articles"
