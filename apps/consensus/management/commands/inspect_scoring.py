"""
Inspect omission scoring details for a topic.

Shows per-article and per-nugget judgment breakdowns for
manual validation and debugging.

Usage:
    python manage.py inspect_scoring --topic-id 1
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.consensus.models import (
    ConsensusPool, ConsensusNugget, OmissionScore, NuggetJudgment,
)
from apps.consensus.services.pool_builder import PoolBuilder


class Command(BaseCommand):
    help = "Inspect omission scoring details for a topic."

    def add_arguments(self, parser):
        parser.add_argument(
            '--topic-id', type=int, required=True,
            help='Topic ID to inspect',
        )
        parser.add_argument(
            '--nuggets', action='store_true',
            help='Show per-nugget judgment matrix',
        )

    def handle(self, *args, **options):
        topic_id = options['topic_id']

        try:
            pool = ConsensusPool.objects.select_related('topic').get(
                topic_id=topic_id,
            )
        except ConsensusPool.DoesNotExist:
            self.stderr.write(f"No consensus pool for topic {topic_id}")
            return

        topic = pool.topic
        nuggets = list(pool.nuggets.order_by('id'))
        scores = list(
            OmissionScore.objects.filter(pool=pool)
            .select_related('article__source')
            .order_by('-coverage_score')
        )

        vital_count = sum(1 for n in nuggets if n.importance == 'vital')
        okay_count = len(nuggets) - vital_count

        pw = getattr(settings, 'CONSENSUS_PARTIAL_WEIGHT', 0.5)
        vw = getattr(settings, 'CONSENSUS_VITAL_WEIGHT', 2.0)
        vt = getattr(settings, 'CONSENSUS_VITAL_THRESHOLD', 3)

        # Compute effective threshold
        builder = PoolBuilder(vital_threshold=vt)
        effective_vt = builder._effective_vital_threshold(len(scores))

        # Header
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(f"SCORING INSPECTION: {topic.title[:60]}")
        self.stdout.write("=" * 80)
        self.stdout.write(f"Articles: {len(scores)}  |  "
                          f"Nuggets: {len(nuggets)} ({vital_count} vital, {okay_count} okay)")
        self.stdout.write(f"\nSettings:")
        self.stdout.write(f"  CONSENSUS_PARTIAL_WEIGHT = {pw}")
        self.stdout.write(f"  CONSENSUS_VITAL_WEIGHT   = {vw}")
        self.stdout.write(f"  CONSENSUS_VITAL_THRESHOLD = {vt} "
                          f"(effective: {effective_vt} for {len(scores)} sources)")

        # Source-by-source coverage table
        self.stdout.write(f"\n{'Source':<20} {'Support':>8} {'Partial':>8} "
                          f"{'Missing':>8} {'Coverage':>10} {'Weighted':>10}")
        self.stdout.write("-" * 80)

        for score in scores:
            source_name = score.article.source.name[:20]
            coverage_pct = f"{score.coverage_score:.1%}" if score.coverage_score is not None else "-"
            weighted_pct = f"{score.weighted_coverage_score:.1%}"
            self.stdout.write(
                f"{source_name:<20} {score.support_count:>8} "
                f"{score.partial_support_count:>8} {score.not_support_count:>8} "
                f"{coverage_pct:>10} {weighted_pct:>10}"
            )

        # Partial support cases
        partial_judgments = (
            NuggetJudgment.objects
            .filter(score__pool=pool, label=NuggetJudgment.Label.PARTIAL_SUPPORT)
            .select_related('score__article__source', 'consensus_nugget')
        )

        if partial_judgments.exists():
            self.stdout.write(f"\nPartial Support Cases ({partial_judgments.count()}):")
            for j in partial_judgments:
                self.stdout.write(
                    f"  {j.score.article.source.name}: "
                    f"\"{j.consensus_nugget.nugget_text[:60]}\" -> PARTIAL"
                )

        # Per-nugget matrix (optional)
        if options['nuggets']:
            self.stdout.write(f"\nPer-Nugget Judgment Matrix:")
            source_names = [s.article.source.name[:12] for s in scores]
            header = f"{'Nugget':<50} {'Imp':>5} " + " ".join(f"{n:>12}" for n in source_names)
            self.stdout.write(header)
            self.stdout.write("-" * len(header))

            # Build lookup: (score_id, nugget_id) -> label
            all_judgments = (
                NuggetJudgment.objects
                .filter(score__pool=pool)
                .values_list('score_id', 'consensus_nugget_id', 'label')
            )
            judgment_map = {
                (sid, nid): label for sid, nid, label in all_judgments
            }

            label_short = {
                'support': 'OK',
                'partial_support': 'PART',
                'not_support': 'MISS',
            }

            for nugget in nuggets:
                row = f"{nugget.nugget_text[:50]:<50} {nugget.importance[:5]:>5} "
                for score in scores:
                    label = judgment_map.get((score.id, nugget.id), '?')
                    row += f"{label_short.get(label, '?'):>12} "
                self.stdout.write(row)

        self.stdout.write("=" * 80 + "\n")
