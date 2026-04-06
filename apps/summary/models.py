from django.db import models
from apps.core.models import TimestampedModel


class NeutralSummary(TimestampedModel):
    """LLM-generated neutral summary from consensus facts."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        GENERATING = 'generating', 'Generating'
        COMPLETE = 'complete', 'Complete'
        FAILED = 'failed', 'Failed'

    topic = models.OneToOneField(
        'topics.Topic',
        on_delete=models.CASCADE,
        related_name='neutral_summary',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    summary_text = models.TextField(blank=True)
    nuggets_used = models.IntegerField(default=0)
    model_name = models.CharField(max_length=100, blank=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ['-generated_at']

    def __str__(self):
        return f"Summary for {self.topic.title[:40]} ({self.status})"
