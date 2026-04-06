from django.db import models
from django.utils.text import slugify
from apps.core.models import TimestampedModel


class Topic(TimestampedModel):
    """A news topic/story that groups related articles."""

    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    # Keywords from Event Registry concepts
    keywords = models.JSONField(default=list)

    # Event Registry identifier
    event_registry_uri = models.CharField(
        max_length=200,
        unique=True,
        null=True,
        blank=True,
        help_text="Event URI in Event Registry"
    )

    # Topic metrics
    article_count = models.IntegerField(default=0)
    source_count = models.IntegerField(default=0)

    # Trending/popularity
    trending_score = models.FloatField(default=0.0)
    is_trending = models.BooleanField(default=False, db_index=True)

    # Timestamps for topic lifecycle
    first_article_at = models.DateTimeField(null=True)
    last_article_at = models.DateTimeField(null=True)

    class Meta:
        ordering = ['-trending_score', '-last_article_at']
        indexes = [
            models.Index(fields=['-trending_score', '-last_article_at']),
            models.Index(fields=['event_registry_uri']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:200]
        super().save(*args, **kwargs)

    def update_metrics(self):
        """Update article and source counts."""
        from django.db.models import Count, Min, Max
        metrics = self.clusters.aggregate(
            _article_count=Count('id'),
            _source_count=Count('article__source', distinct=True),
            _first_article_at=Min('article__published_at'),
            _last_article_at=Max('article__published_at'),
        )
        self.article_count = metrics['_article_count']
        self.source_count = metrics['_source_count']
        self.first_article_at = metrics['_first_article_at']
        self.last_article_at = metrics['_last_article_at']

        self.save(update_fields=[
            'article_count', 'source_count',
            'first_article_at', 'last_article_at'
        ])

    def get_covering_sources(self):
        """Return Source queryset of sources that have articles for this topic."""
        from apps.articles.models import Source
        source_ids = self.clusters.values_list('article__source_id', flat=True).distinct()
        return Source.objects.filter(pk__in=source_ids)

    def get_missing_sources(self):
        """Return active tracked sources that have NO articles for this topic."""
        from apps.articles.models import Source
        covering_ids = set(
            self.clusters.values_list('article__source_id', flat=True).distinct()
        )
        return Source.objects.filter(is_active=True).exclude(pk__in=covering_ids)

    def get_coverage_summary(self):
        """Compute story-level omission: which tracked sources ignored this event."""
        from apps.articles.models import Source
        # Single query for covering source IDs (was duplicated before)
        covering_ids = set(
            self.clusters.values_list('article__source_id', flat=True).distinct()
        )
        covering_list = list(
            Source.objects.filter(pk__in=covering_ids)
            .values('name', 'slug', 'known_bias')
            .order_by('name')
        )

        # "Notable" missing = sources with a known bias rating (editorially curated),
        # not every auto-created source from Event Registry
        notable_missing = list(
            Source.objects.filter(is_active=True)
            .exclude(pk__in=covering_ids)
            .exclude(known_bias=Source.BiasRating.CENTER)
            .values('name', 'slug', 'known_bias')
            .order_by('name')
        )

        return {
            'covering_sources': len(covering_list),
            'covering_source_details': covering_list,
            'notable_missing': notable_missing,
        }


class ArticleCluster(TimestampedModel):
    """Links an article to a topic cluster."""

    topic = models.ForeignKey(
        Topic,
        on_delete=models.CASCADE,
        related_name='clusters'
    )
    article = models.OneToOneField(
        'articles.Article',
        on_delete=models.CASCADE,
        related_name='cluster'
    )

    # Clustering confidence
    confidence_score = models.FloatField(default=0.0)

    # Position in cluster (for ordering by relevance)
    cluster_rank = models.IntegerField(default=0)

    class Meta:
        unique_together = ['topic', 'article']
        ordering = ['-confidence_score']

    def __str__(self):
        return f"{self.article.title[:30]} -> {self.topic.title[:30]}"
