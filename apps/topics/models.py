from django.db import models
from django.utils.text import slugify
from apps.core.models import TimestampedModel


class Topic(TimestampedModel):
    """A news topic/story that groups related articles."""

    title = models.CharField(max_length=300)
    slug = models.SlugField(max_length=200, unique=True)
    description = models.TextField(blank=True)

    # Auto-generated keywords from clustering
    keywords = models.JSONField(default=list)

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

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:200]
        super().save(*args, **kwargs)

    def update_metrics(self):
        """Update article and source counts."""
        clusters = self.clusters.all()
        self.article_count = clusters.count()
        self.source_count = clusters.values('article__source').distinct().count()

        # Update article timestamps
        articles = clusters.values_list('article__published_at', flat=True)
        dates = [d for d in articles if d is not None]
        if dates:
            self.first_article_at = min(dates)
            self.last_article_at = max(dates)

        self.save(update_fields=[
            'article_count', 'source_count',
            'first_article_at', 'last_article_at'
        ])


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
