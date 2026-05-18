"""Flag near-duplicate articles within each topic via MinHash / LSH.

Complements the byline-based wire detection in `flag_wire_articles`: catches
cases where outlets republish wire copy (verbatim or lightly edited) but strip
the AP/Reuters byline and substitute an in-house author.

Within each topic, every article's content is converted to word shingles and a
MinHash signature is computed. A locality-sensitive hash (LSH) index supports
sub-quadratic pairwise comparison. Articles are processed in chronological order
and inserted into the index one by one: when a new article's signature matches
something already in the index (Jaccard >= threshold), it is a republication of
an earlier article and is flagged `is_wire_content=True`. The first article in
each cluster is kept as the original.
"""
from django.core.management.base import BaseCommand
from datasketch import MinHashLSH

from apps.articles.models import Article
from apps.articles.utils import (
    MINHASH_NUM_PERM,
    MINHASH_SHINGLE_SIZE,
    article_minhash,
)
from apps.topics.models import Topic


class Command(BaseCommand):
    help = (
        'Within each topic, flag near-duplicate articles as wire-derived via '
        'MinHash / LSH. Earliest-published article in each duplicate cluster is '
        'kept as the original.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--threshold',
            type=float,
            default=0.8,
            help=(
                'Jaccard similarity threshold for near-duplicate detection '
                '(default: 0.8). Broder (1997) used 0.5 for general web '
                'clustering, but news articles about the same event share '
                'enough topical vocabulary that 0.5 over-flags; 0.7-0.9 is '
                'appropriate for wire-copy republication detection.'
            ),
        )
        parser.add_argument(
            '--num-perm',
            type=int,
            default=MINHASH_NUM_PERM,
            help=f'MinHash permutations (default: {MINHASH_NUM_PERM}).',
        )
        parser.add_argument(
            '--shingle-size',
            type=int,
            default=MINHASH_SHINGLE_SIZE,
            help=f'Word-level shingle size (default: {MINHASH_SHINGLE_SIZE}).',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Report what would be flagged without writing to the database.',
        )

    def handle(self, *args, **options):
        threshold = options['threshold']
        num_perm = options['num_perm']
        shingle_size = options['shingle_size']
        dry_run = options['dry_run']

        topics_processed = 0
        clusters_with_dups = 0
        newly_flagged = 0

        for topic in Topic.objects.iterator():
            articles = list(
                Article.objects
                .filter(cluster__topic=topic)
                .exclude(content='')
                .order_by('published_at', 'id')
            )
            if len(articles) < 2:
                continue

            lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
            saw_duplicate_in_topic = False

            for article in articles:
                mh = article_minhash(
                    article.content,
                    num_perm=num_perm,
                    shingle_size=shingle_size,
                )
                if mh is None:
                    continue

                matches = lsh.query(mh)
                if matches:
                    saw_duplicate_in_topic = True
                    if not article.is_wire_content:
                        if not dry_run:
                            article.is_wire_content = True
                            article.save(update_fields=['is_wire_content'])
                        newly_flagged += 1

                # Always insert so subsequent articles can match against this one.
                lsh.insert(str(article.id), mh)

            if saw_duplicate_in_topic:
                clusters_with_dups += 1
            topics_processed += 1

        verb = 'Would flag' if dry_run else 'Flagged'
        self.stdout.write(self.style.SUCCESS(
            f'Processed {topics_processed} topics at threshold {threshold}. '
            f'{clusters_with_dups} topics contained near-duplicates. '
            f'{verb} {newly_flagged} articles newly as wire content.'
        ))