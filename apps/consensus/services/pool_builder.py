"""
Consensus pool builder service.

Orchestrates the three-step pipeline:
1. Extract nuggets from each article
2. Deduplicate into consensus nuggets
3. Score each article's omission
"""
from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor, as_completed

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.articles.models import Article
from apps.topics.models import Topic, ArticleCluster
from apps.extraction.services.extractor import NuggetExtractor
from apps.evaluation.services.auto_assigner import AutoAssigner, AssignmentLabel

from ..models import (
    ConsensusPool,
    ConsensusNugget,
    RawNugget,
    OmissionScore,
    NuggetJudgment,
)
from .deduplicator import NuggetDeduplicator
from .post_processor import NuggetPostProcessor

logger = logging.getLogger(__name__)


class PoolBuilder:
    """
    Builds a consensus fact pool for a topic and scores article omission.

    Reuses:
    - NuggetExtractor for LLM-based fact extraction
    - NuggetDeduplicator for semantic clustering
    - AutoAssigner for LLM-based support labeling
    """

    def __init__(
        self,
        backend: str = 'deepseek',
        similarity_threshold: float | None = None,
        vital_threshold: int | None = None,
    ):
        self.backend = backend
        self.similarity_threshold = similarity_threshold or getattr(
            settings, 'CONSENSUS_SIMILARITY_THRESHOLD', 0.85
        )
        self.vital_threshold = vital_threshold or getattr(
            settings, 'CONSENSUS_VITAL_THRESHOLD', 3
        )

    def build(self, topic_id: int, rebuild: bool = False) -> ConsensusPool:
        """
        Full pipeline: extract → deduplicate → score.

        Args:
            topic_id: Topic to build pool for.
            rebuild: If True, delete existing pool and rebuild.

        Returns:
            The completed ConsensusPool.
        """
        topic = Topic.objects.get(id=topic_id)

        # Handle existing pool
        existing_pool = None
        if hasattr(topic, 'consensus_pool') and topic.consensus_pool:
            if not rebuild:
                logger.info(f"Pool already exists for topic {topic_id}")
                return topic.consensus_pool
            existing_pool = topic.consensus_pool
            # Cache raw nuggets from existing pool before deleting
            cached_nuggets = self._cache_raw_nuggets(existing_pool)
            existing_pool.delete()
        else:
            cached_nuggets = {}

        pool = ConsensusPool.objects.create(
            topic=topic,
            status=ConsensusPool.Status.PENDING,
            similarity_threshold=self.similarity_threshold,
        )

        articles = self._get_articles(topic)
        if len(articles) < 2:
            pool.status = ConsensusPool.Status.FAILED
            pool.error_message = f"Need at least 2 articles, got {len(articles)}"
            pool.save()
            return pool

        try:
            # Step 1: Extract nuggets (reuse cached where possible)
            pool.status = ConsensusPool.Status.EXTRACTING
            pool.save(update_fields=['status'])
            self._extract_nuggets(pool, articles, cached_nuggets)

            # Step 2: Deduplicate
            pool.status = ConsensusPool.Status.DEDUPLICATING
            pool.save(update_fields=['status'])
            self._deduplicate_nuggets(pool, num_articles=len(articles))

            # Step 2b: Post-process (merge + tier)
            if getattr(settings, 'CONSENSUS_POST_PROCESSING_ENABLED', True):
                pool.status = ConsensusPool.Status.POST_PROCESSING
                pool.save(update_fields=['status'])
                self._post_process_nuggets(pool)

            # Step 3: Score articles
            pool.status = ConsensusPool.Status.SCORING
            pool.save(update_fields=['status'])
            self._score_articles(pool, articles)

            # Finalize
            pool.status = ConsensusPool.Status.COMPLETE
            pool.built_at = timezone.now()
            pool.save(update_fields=['status', 'built_at'])

            # Pre-compute report data so the web view loads instantly
            try:
                pool.build_report_cache()
            except Exception as e:
                logger.warning(f"Report cache build failed (non-fatal): {e}")

            logger.info(
                f"Pool complete for '{topic.title[:40]}': "
                f"{pool.nugget_count} nuggets ({pool.vital_nugget_count} vital), "
                f"{pool.articles_processed} articles scored"
            )

            # Auto-trigger neutral summary generation
            try:
                from apps.summary.tasks import generate_summary
                generate_summary.delay(topic_id)
            except (ImportError, ConnectionError, OSError):
                logger.warning(f"Could not queue summary generation for topic {topic_id}")

        except Exception as e:
            logger.error(f"Pool build failed for topic {topic_id}: {e}")
            pool.status = ConsensusPool.Status.FAILED
            pool.error_message = str(e)[:1000]
            pool.save(update_fields=['status', 'error_message'])
            raise

        return pool

    def _get_articles(self, topic: Topic) -> list[Article]:
        """Get all complete, non-wire-copy articles for a topic."""
        return list(
            Article.objects.filter(
                cluster__topic=topic,
                status=Article.ProcessingStatus.COMPLETE,
                is_wire_content=False,
            )
            .exclude(content='')
            .select_related('source')
        )

    @staticmethod
    def _cache_raw_nuggets(pool: ConsensusPool) -> dict[int, list[dict]]:
        """Cache raw nuggets from an existing pool, keyed by article ID."""
        cached = {}
        for rn in pool.raw_nuggets.values('article_id', 'nugget_text', 'nugget_type'):
            cached.setdefault(rn['article_id'], []).append({
                'fact': rn['nugget_text'],
                'type': rn['nugget_type'],
            })
        return cached

    def _extract_nuggets(
        self,
        pool: ConsensusPool,
        articles: list[Article],
        cached_nuggets: dict[int, list[dict]] | None = None,
    ) -> None:
        """Step 1: Extract nuggets from each article, reusing cached where available."""
        pool.model_name = getattr(settings, 'DEEPSEEK_MODEL', 'deepseek-reasoner')
        cached_nuggets = cached_nuggets or {}

        # Separate cached vs. needs-extraction
        to_extract = []
        for article in articles:
            if article.id in cached_nuggets:
                # Immediately save cached nuggets (no LLM call needed)
                raw_objects = [
                    RawNugget(
                        pool=pool, article=article,
                        nugget_text=n['fact'], nugget_type=n.get('type', ''),
                    )
                    for n in cached_nuggets[article.id]
                ]
                RawNugget.objects.bulk_create(raw_objects)
                logger.debug(
                    f"Cached {len(raw_objects)} nuggets from "
                    f"{article.source.name}: {article.title[:40]}"
                )
            else:
                to_extract.append(article)

        if cached_nuggets:
            cached_count = len(articles) - len(to_extract)
            logger.info(
                f"Reused cached nuggets for {cached_count}/{len(articles)} articles"
            )

        if not to_extract:
            pool.save(update_fields=['model_name'])
            return

        # Parallel extraction for new articles
        def _extract_one(article):
            extractor = NuggetExtractor(backend=self.backend)
            nuggets = extractor.extract(article.content, domain='news')
            return article, nuggets

        max_workers = min(len(to_extract), 20)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_extract_one, a): a for a in to_extract
            }
            for future in as_completed(futures):
                article = futures[future]
                try:
                    _, nuggets = future.result()
                    raw_objects = [
                        RawNugget(
                            pool=pool, article=article,
                            nugget_text=n['fact'], nugget_type=n.get('type', ''),
                        )
                        for n in nuggets
                    ]
                    RawNugget.objects.bulk_create(raw_objects)
                    logger.debug(
                        f"Extracted {len(nuggets)} nuggets from "
                        f"{article.source.name}: {article.title[:40]}"
                    )
                except Exception as e:
                    logger.error(
                        f"Extraction failed for article {article.id}: {e}"
                    )

        pool.save(update_fields=['model_name'])

    def _effective_vital_threshold(self, num_articles: int) -> int:
        """
        Compute effective vital threshold scaling with source count.

        For 2-4 sources, requires 2+ sources (any corroboration).
        For 5+ sources, requires at least 25% to call something vital.
        """
        return max(2, math.ceil(num_articles * 0.25))

    def _deduplicate_nuggets(
        self, pool: ConsensusPool, num_articles: int = 2
    ) -> None:
        """Step 2: Cluster raw nuggets into consensus nuggets."""
        raw_nuggets = list(
            pool.raw_nuggets
            .select_related('article__source')
            .order_by('id')
        )

        if not raw_nuggets:
            pool.nugget_count = 0
            pool.vital_nugget_count = 0
            pool.save(update_fields=['nugget_count', 'vital_nugget_count'])
            return

        nugget_texts = [rn.nugget_text for rn in raw_nuggets]
        source_names = [rn.article.source.name for rn in raw_nuggets]

        deduplicator = NuggetDeduplicator(threshold=self.similarity_threshold)
        result = deduplicator.deduplicate(nugget_texts, source_names)

        # Create ConsensusNugget for each cluster
        effective_threshold = self._effective_vital_threshold(num_articles)
        consensus_objects = []
        for cluster in result.clusters:
            importance = (
                ConsensusNugget.Importance.VITAL
                if cluster.source_count >= effective_threshold
                else ConsensusNugget.Importance.OKAY
            )
            cn = ConsensusNugget(
                pool=pool,
                nugget_text=cluster.representative_text,
                importance=importance,
                source_count=cluster.source_count,
                source_names=sorted(cluster.source_names),
                cluster_id=cluster.cluster_id,
            )
            consensus_objects.append(cn)

        ConsensusNugget.objects.bulk_create(consensus_objects)

        # Link raw nuggets to their consensus nugget
        # Refresh to get DB IDs
        cn_by_cluster = {
            cn.cluster_id: cn
            for cn in pool.nuggets.all()
        }

        for i, rn in enumerate(raw_nuggets):
            cluster_id = result.assignments[i]
            rn.consensus_nugget = cn_by_cluster.get(cluster_id)

        RawNugget.objects.bulk_update(raw_nuggets, ['consensus_nugget'])

        # Update pool counts
        pool.nugget_count = len(consensus_objects)
        pool.vital_nugget_count = sum(
            1 for cn in consensus_objects
            if cn.importance == ConsensusNugget.Importance.VITAL
        )
        pool.save(update_fields=['nugget_count', 'vital_nugget_count'])

    def _post_process_nuggets(self, pool: ConsensusPool) -> None:
        """Step 2b: LLM merge + tier assignment (non-fatal on failure)."""
        try:
            processor = NuggetPostProcessor(backend=self.backend)
            result = processor.process(pool)
            logger.info(
                f"Post-processing complete: {result.nuggets_merged} merged, "
                f"tiers: {result.tier1_count}/{result.tier2_count}/{result.tier3_count}"
            )
        except Exception as e:
            logger.warning(
                f"Post-processing failed for pool {pool.id}, "
                f"continuing with unmerged/untiered nuggets: {e}"
            )

    def _score_articles(
        self, pool: ConsensusPool, articles: list[Article]
    ) -> None:
        """Step 3: Score each article against the consensus pool (parallel)."""
        consensus_nuggets = list(pool.nuggets.order_by('id'))
        if not consensus_nuggets:
            return

        consensus_texts = [cn.nugget_text for cn in consensus_nuggets]
        vital_indices = {
            i for i, cn in enumerate(consensus_nuggets)
            if cn.importance == ConsensusNugget.Importance.VITAL
        }

        def _score_one(article):
            # Each thread gets its own AutoAssigner (own LLM client)
            assigner = AutoAssigner(backend=self.backend)
            self._score_single_article(
                pool, article, assigner,
                consensus_nuggets, consensus_texts, vital_indices,
            )
            return article

        scored = 0
        max_workers = min(len(articles), 20)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_score_one, a): a for a in articles
            }
            for future in as_completed(futures):
                article = futures[future]
                try:
                    future.result()
                    scored += 1
                    logger.debug(
                        f"Scored article {scored}/{len(articles)}: "
                        f"{article.source.name}"
                    )
                except Exception as e:
                    logger.error(
                        f"Scoring failed for article {article.id}: {e}"
                    )
                    OmissionScore.objects.update_or_create(
                        pool=pool,
                        article=article,
                        defaults={'error_message': str(e)[:1000]},
                    )

        pool.articles_processed = scored
        pool.save(update_fields=['articles_processed'])

    def _score_single_article(
        self,
        pool: ConsensusPool,
        article: Article,
        assigner: AutoAssigner,
        consensus_nuggets: list[ConsensusNugget],
        consensus_texts: list[str],
        vital_indices: set[int],
    ) -> OmissionScore:
        """Score a single article against the consensus pool."""
        # Pass article content as the "answer" to check against
        # consensus nuggets as the "ground truth facts" to verify
        result = assigner.assign(
            extracted_nuggets=[article.content],
            ground_truth_facts=consensus_texts,
            context=pool.topic.title,
        )

        # Create or update the score record
        omission_score, _ = OmissionScore.objects.update_or_create(
            pool=pool,
            article=article,
            defaults={'scored_at': timezone.now(), 'error_message': ''},
        )

        # Create individual judgments
        judgments = []
        support = partial = not_support = 0
        vital_support = vital_partial = 0

        for assignment in result.assignments:
            cn = consensus_nuggets[assignment.fact_index]
            label = _map_label(assignment.label)

            judgments.append(NuggetJudgment(
                score=omission_score,
                consensus_nugget=cn,
                label=label,
            ))

            if label == NuggetJudgment.Label.SUPPORT:
                support += 1
                if assignment.fact_index in vital_indices:
                    vital_support += 1
            elif label == NuggetJudgment.Label.PARTIAL_SUPPORT:
                partial += 1
                if assignment.fact_index in vital_indices:
                    vital_partial += 1
            else:
                not_support += 1

        # Clear old judgments and bulk create new ones (atomic to prevent orphans)
        with transaction.atomic():
            omission_score.judgments.all().delete()
            NuggetJudgment.objects.bulk_create(judgments)

        # Compute scores
        total = len(consensus_texts)
        vital_total = len(vital_indices)

        omission_score.support_count = support
        omission_score.partial_support_count = partial
        omission_score.not_support_count = not_support
        omission_score.total_nuggets = total
        omission_score.vital_support_count = vital_support
        omission_score.vital_partial_support_count = vital_partial
        omission_score.vital_total = vital_total

        scores = compute_scores(
            support, partial, not_support, total,
            vital_support, vital_partial, vital_total,
        )
        omission_score.coverage_score = scores['coverage_score']
        omission_score.omission_rate = scores['omission_rate']
        omission_score.vital_omission_rate = scores['vital_omission_rate']

        omission_score.save()
        return omission_score


def _map_label(label: AssignmentLabel) -> str:
    """Map AutoAssigner label to NuggetJudgment label string."""
    mapping = {
        AssignmentLabel.SUPPORT: NuggetJudgment.Label.SUPPORT,
        AssignmentLabel.PARTIAL_SUPPORT: NuggetJudgment.Label.PARTIAL_SUPPORT,
        AssignmentLabel.NOT_SUPPORT: NuggetJudgment.Label.NOT_SUPPORT,
    }
    return mapping.get(label, NuggetJudgment.Label.NOT_SUPPORT)


def compute_scores(
    support: int,
    partial: int,
    not_support: int,
    total: int,
    vital_support: int,
    vital_partial: int,
    vital_total: int,
    partial_weight: float | None = None,
    vital_weight: float | None = None,
) -> dict:
    """
    Compute all coverage/omission scores from raw judgment counts.

    Returns dict with keys: coverage_score, omission_rate,
    vital_omission_rate, weighted_coverage_score.
    """
    pw = partial_weight if partial_weight is not None else getattr(
        settings, 'CONSENSUS_PARTIAL_WEIGHT', 0.5
    )
    vw = vital_weight if vital_weight is not None else getattr(
        settings, 'CONSENSUS_VITAL_WEIGHT', 2.0
    )

    if total > 0:
        coverage_score = (support + pw * partial) / total
        omission_rate = 1.0 - coverage_score
    else:
        coverage_score = 1.0
        omission_rate = 0.0

    if vital_total > 0:
        vital_covered = vital_support + pw * vital_partial
        vital_omission_rate = 1.0 - (vital_covered / vital_total)
    else:
        vital_omission_rate = 0.0

    # Importance-weighted coverage
    okay_total = total - vital_total
    okay_support = support - vital_support
    okay_partial = partial - vital_partial
    okay_covered = okay_support + pw * okay_partial
    vital_covered_w = vital_support + pw * vital_partial

    weighted_denom = vital_total * vw + okay_total
    if weighted_denom > 0:
        weighted_coverage_score = (vital_covered_w * vw + okay_covered) / weighted_denom
    else:
        weighted_coverage_score = 1.0

    return {
        'coverage_score': round(coverage_score, 6),
        'omission_rate': round(omission_rate, 6),
        'vital_omission_rate': round(vital_omission_rate, 6),
        'weighted_coverage_score': round(weighted_coverage_score, 6),
    }
