"""Management command to run tone/framing analysis on articles."""

from django.core.management.base import BaseCommand

from apps.articles.models import Article
from apps.analysis.tasks import analyze_article


class Command(BaseCommand):
    help = "Run tone and framing analysis on articles."

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=100,
            help='Maximum articles to analyze (default: 100)',
        )
        parser.add_argument(
            '--reanalyze',
            action='store_true',
            help='Re-analyze articles that already have results',
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run synchronously instead of queuing Celery tasks',
        )

    def handle(self, *args, **options):
        limit = options['limit']
        reanalyze = options['reanalyze']
        sync = options['sync']

        queryset = Article.objects.filter(
            status=Article.ProcessingStatus.COMPLETE,
        ).exclude(content='')

        if not reanalyze:
            queryset = queryset.filter(analysis__isnull=True)

        article_ids = list(queryset.values_list('id', flat=True)[:limit])
        self.stdout.write(f"Found {len(article_ids)} articles to analyze")

        for article_id in article_ids:
            if sync:
                result = analyze_article(article_id)
                self.stdout.write(f"  {result}")
            else:
                analyze_article.delay(article_id)

        mode = 'Analyzed' if sync else 'Queued'
        self.stdout.write(self.style.SUCCESS(f"Done! {mode} {len(article_ids)} articles."))
