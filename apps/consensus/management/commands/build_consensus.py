"""Management command to build consensus pools for topics."""

from django.core.management.base import BaseCommand
from django.db.models import Count

from apps.topics.models import Topic


class Command(BaseCommand):
    help = "Build consensus fact pools and score article omission."

    def add_arguments(self, parser):
        parser.add_argument(
            '--topic-id',
            type=int,
            help='Build pool for a specific topic ID',
        )
        parser.add_argument(
            '--all-ready',
            action='store_true',
            help='Build pools for all topics with enough sources',
        )
        parser.add_argument(
            '--rebuild',
            action='store_true',
            help='Rebuild existing pools',
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run synchronously instead of queuing Celery tasks',
        )
        parser.add_argument(
            '--min-sources',
            type=int,
            default=3,
            help='Minimum distinct sources required (default: 3)',
        )
        parser.add_argument(
            '--rescore',
            action='store_true',
            help='Recompute scores from existing judgments using current formula (no LLM)',
        )

    def handle(self, *args, **options):
        if options['rescore']:
            self._rescore(options.get('topic_id'))
            return

        topic_id = options['topic_id']
        all_ready = options['all_ready']
        rebuild = options['rebuild']
        sync = options['sync']
        min_sources = options['min_sources']

        if topic_id:
            self._build_single(topic_id, rebuild, sync)
        elif all_ready:
            self._build_all_ready(min_sources, rebuild, sync)
        else:
            self.stderr.write(
                "Specify --topic-id <ID>, --all-ready, or --rescore"
            )

    def _build_single(self, topic_id, rebuild, sync):
        try:
            topic = Topic.objects.get(id=topic_id)
        except Topic.DoesNotExist:
            self.stderr.write(f"Topic {topic_id} not found")
            return

        self.stdout.write(f"Building pool for: {topic.title}")

        if sync:
            from apps.consensus.services.pool_builder import PoolBuilder
            builder = PoolBuilder(backend='deepseek')
            pool = builder.build(topic_id, rebuild=rebuild)
            self.stdout.write(self.style.SUCCESS(
                f"Done! {pool.nugget_count} nuggets "
                f"({pool.vital_nugget_count} vital), "
                f"{pool.articles_processed} articles scored. "
                f"Status: {pool.status}"
            ))
        else:
            from apps.consensus.tasks import build_consensus_pool
            build_consensus_pool.delay(topic_id, rebuild=rebuild)
            self.stdout.write(self.style.SUCCESS("Queued for processing."))

    def _build_all_ready(self, min_sources, rebuild, sync):
        queryset = Topic.objects.annotate(
            distinct_sources=Count(
                'clusters__article__source', distinct=True
            )
        ).filter(distinct_sources__gte=min_sources)

        if not rebuild:
            queryset = queryset.filter(consensus_pool__isnull=True)

        topic_ids = list(queryset.values_list('id', flat=True))
        self.stdout.write(f"Found {len(topic_ids)} topics ready for pool building")

        for topic_id in topic_ids:
            if sync:
                from apps.consensus.services.pool_builder import PoolBuilder
                builder = PoolBuilder(backend='deepseek')
                try:
                    pool = builder.build(topic_id, rebuild=rebuild)
                    self.stdout.write(
                        f"  Topic {topic_id}: {pool.nugget_count} nuggets, "
                        f"{pool.articles_processed} articles"
                    )
                except Exception as e:
                    self.stderr.write(f"  Topic {topic_id}: FAILED - {e}")
            else:
                from apps.consensus.tasks import build_consensus_pool
                build_consensus_pool.delay(topic_id, rebuild=rebuild)

        mode = 'Built' if sync else 'Queued'
        self.stdout.write(self.style.SUCCESS(
            f"Done! {mode} {len(topic_ids)} pools."
        ))

    def _rescore(self, topic_id=None):
        """Recompute coverage scores from stored raw counts using current formula."""
        from apps.consensus.models import ConsensusPool, OmissionScore
        from apps.consensus.services.pool_builder import compute_scores

        pools = ConsensusPool.objects.filter(status='complete')
        if topic_id:
            pools = pools.filter(topic_id=topic_id)

        total_rescored = 0
        for pool in pools:
            scores = OmissionScore.objects.filter(pool=pool)
            for score in scores:
                result = compute_scores(
                    score.support_count,
                    score.partial_support_count,
                    score.not_support_count,
                    score.total_nuggets,
                    score.vital_support_count,
                    score.vital_partial_support_count,
                    score.vital_total,
                )
                score.coverage_score = result['coverage_score']
                score.omission_rate = result['omission_rate']
                score.vital_omission_rate = result['vital_omission_rate']
                score.save(update_fields=[
                    'coverage_score', 'omission_rate', 'vital_omission_rate',
                ])
                total_rescored += 1

            self.stdout.write(
                f"  Pool for topic {pool.topic_id}: rescored {scores.count()} articles"
            )

        self.stdout.write(self.style.SUCCESS(
            f"Rescored {total_rescored} articles across {pools.count()} pools"
        ))
