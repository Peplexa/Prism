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

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    website_url = models.URLField()
    logo_url = models.URLField(blank=True)

    # Event Registry identifier (e.g. "npr.org", "foxnews.com")
    event_registry_uri = models.CharField(
        max_length=200,
        unique=True,
        blank=True,
        default='',
        help_text="Source URI in Event Registry (e.g. 'npr.org')"
    )

    # Source metadata
    known_bias = models.CharField(
        max_length=20,
        choices=BiasRating.choices,
        default=BiasRating.CENTER
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name)[:45] or 'source'
            slug = base_slug
            counter = 2
            while Source.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Article(TimestampedModel):
    """Individual news article."""

    class ProcessingStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
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
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)

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

    # Wire service detection
    is_wire_content = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if this article is a republished wire service story (AP, Reuters, AFP, etc.)"
    )

    # Event Registry metadata
    event_registry_uri = models.CharField(
        max_length=200,
        unique=True,
        null=True,
        blank=True,
        help_text="Article URI in Event Registry"
    )
    sentiment = models.FloatField(
        null=True,
        blank=True,
        help_text="Sentiment score from Event Registry (-1 to 1)"
    )

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
