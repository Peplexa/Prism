"""Management command to generate neutral summaries."""

from django.core.management.base import BaseCommand
from apps.topics.models import Topic


class Command(BaseCommand):
    help = "Generate neutral summaries for topics with completed consensus pools."

    def add_arguments(self, parser):
        parser.add_argument('--topic-id', type=int, help='Generate for a specific topic')
        parser.add_argument('--all-ready', action='store_true', help='Generate for all ready topics')
        parser.add_argument('--regenerate', action='store_true', help='Regenerate existing summaries')
        parser.add_argument('--sync', action='store_true', help='Run synchronously')
        parser.add_argument('--limit', type=int, default=50, help='Max topics to process')

    def handle(self, *args, **options):
        if options['topic_id']:
            self._generate_single(options['topic_id'], options['regenerate'], options['sync'])
        elif options['all_ready']:
            self._generate_all_ready(options['regenerate'], options['sync'], options['limit'])
        else:
            self.stderr.write("Specify --topic-id <ID> or --all-ready")

    def _generate_single(self, topic_id, regenerate, sync):
        try:
            topic = Topic.objects.get(id=topic_id)
        except Topic.DoesNotExist:
            self.stderr.write(f"Topic {topic_id} not found")
            return

        self.stdout.write(f"Generating summary for: {topic.title}")

        if sync:
            from apps.summary.services.summarizer import NeutralSummarizer
            summarizer = NeutralSummarizer(backend='deepseek')
            summary = summarizer.generate(topic_id, regenerate=regenerate)
            self.stdout.write(self.style.SUCCESS(
                f"Done! Status: {summary.status}, "
                f"{summary.nuggets_used} nuggets used"
            ))
        else:
            from apps.summary.tasks import generate_summary
            generate_summary.delay(topic_id, regenerate=regenerate)
            self.stdout.write(self.style.SUCCESS("Queued for processing."))

    def _generate_all_ready(self, regenerate, sync, limit):
        from apps.consensus.models import ConsensusPool

        queryset = ConsensusPool.objects.filter(
            status=ConsensusPool.Status.COMPLETE,
        )
        if not regenerate:
            queryset = queryset.filter(topic__neutral_summary__isnull=True)

        topic_ids = list(queryset.values_list('topic_id', flat=True)[:limit])
        self.stdout.write(f"Found {len(topic_ids)} topics ready for summary generation")

        for topic_id in topic_ids:
            if sync:
                from apps.summary.services.summarizer import NeutralSummarizer
                summarizer = NeutralSummarizer(backend='deepseek')
                try:
                    summary = summarizer.generate(topic_id, regenerate=regenerate)
                    self.stdout.write(f"  Topic {topic_id}: {summary.status}")
                except Exception as e:
                    self.stderr.write(f"  Topic {topic_id}: FAILED - {e}")
            else:
                from apps.summary.tasks import generate_summary
                generate_summary.delay(topic_id, regenerate=regenerate)

        mode = 'Generated' if sync else 'Queued'
        self.stdout.write(self.style.SUCCESS(f"Done! {mode} {len(topic_ids)} summaries."))
