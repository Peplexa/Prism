"""Backfill is_wire_content flag on existing articles."""
from django.core.management.base import BaseCommand

from apps.articles.models import Article
from apps.articles.utils import is_wire_copy


class Command(BaseCommand):
    help = 'Flag existing articles that are wire service republications.'

    def handle(self, *args, **options):
        articles = Article.objects.select_related('source').all()
        flagged = 0
        for article in articles.iterator(chunk_size=500):
            flag = is_wire_copy(article.author, article.source.event_registry_uri)
            if flag != article.is_wire_content:
                article.is_wire_content = flag
                article.save(update_fields=['is_wire_content'])
                flagged += 1
        self.stdout.write(self.style.SUCCESS(f'Flagged {flagged} articles as wire content.'))
