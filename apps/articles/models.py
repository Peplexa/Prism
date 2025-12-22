from django.db import models
from django.utils.text import slugify
from apps.core.models import TimestampedModel


class Source(TimestampedModel):
    """News source configuration."""

    class BiasRating(models.TextChoices):
        FAR_LEFT = 'far_left', 'Far Left'
        LEFT = 'left', 'Left'
        CENTER_LEFT = 'center_left', 'Center Left'
        CENTER = 'center', 'Center'
        CENTER_RIGHT = 'center_right', 'Center Right'
        RIGHT = 'right', 'Right'
        FAR_RIGHT = 'far_right', 'Far Right'

    class DiscoveryMethod(models.TextChoices):
        RSS = 'rss', 'RSS Feed'
        SITEMAP = 'sitemap', 'Sitemap XML'
        HOMEPAGE = 'homepage', 'Homepage Scraping'

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    website_url = models.URLField()
    logo_url = models.URLField(blank=True)

    # Discovery configuration
    discovery_method = models.CharField(
        max_length=20,
        choices=DiscoveryMethod.choices,
        default=DiscoveryMethod.RSS
    )
    discovery_url = models.URLField(
        help_text="RSS feed URL, sitemap URL, or homepage URL for scraping"
    )

    # Optional: CSS selectors for homepage scraping
    article_link_selector = models.CharField(
        max_length=200,
        blank=True,
        help_text="CSS selector for article links (homepage scraping only)"
    )

    # Source metadata
    known_bias = models.CharField(
        max_length=20,
        choices=BiasRating.choices,
        default=BiasRating.CENTER
    )
    is_active = models.BooleanField(default=True)
    scrape_frequency_hours = models.IntegerField(default=1)
    last_scraped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class Article(TimestampedModel):
    """Individual news article."""

    class ProcessingStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        SCRAPED = 'scraped', 'Content Scraped'
        EMBEDDED = 'embedded', 'Embeddings Generated'
        CLUSTERED = 'clustered', 'Topic Assigned'
        COMPLETE = 'complete', 'Processing Complete'
        FAILED = 'failed', 'Processing Failed'

    source = models.ForeignKey(
        Source,
        on_delete=models.CASCADE,
        related_name='articles'
    )

    # Article metadata
    title = models.CharField(max_length=500)
    slug = models.SlugField(max_length=250)
    url = models.URLField(unique=True, db_index=True, max_length=2000)
    author = models.CharField(max_length=300, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    # Content
    summary = models.TextField(blank=True, help_text="Short summary/description")
    content = models.TextField(blank=True, help_text="Full article text")
    word_count = models.IntegerField(default=0)

    # Processing
    status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.PENDING,
        db_index=True
    )
    error_message = models.TextField(blank=True)

    # Embeddings (stored as JSON)
    embedding = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ['-published_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['source', 'published_at']),
        ]

    def __str__(self):
        return f"{self.source.name}: {self.title[:50]}"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)[:250]
        if self.content:
            self.word_count = len(self.content.split())
        super().save(*args, **kwargs)
