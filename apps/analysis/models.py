from django.db import models
from apps.core.models import TimestampedModel


class ArticleAnalysis(TimestampedModel):
    """Tone and framing analysis results for a single article."""

    class AnalysisStatus(models.TextChoices):
        PENDING = 'pending', 'Pending'
        RUNNING = 'running', 'Running'
        COMPLETE = 'complete', 'Complete'
        FAILED = 'failed', 'Failed'

    article = models.OneToOneField(
        'articles.Article',
        on_delete=models.CASCADE,
        related_name='analysis',
    )

    status = models.CharField(
        max_length=20,
        choices=AnalysisStatus.choices,
        default=AnalysisStatus.PENDING,
        db_index=True,
    )
    error_message = models.TextField(blank=True)

    # --- Tone (subjectivity) results ---
    subjectivity_ratio = models.FloatField(
        null=True,
        blank=True,
        help_text="Proportion of subjective sentences (0.0=fully objective, 1.0=fully subjective)",
    )
    sentence_count = models.IntegerField(
        null=True,
        blank=True,
        help_text="Total sentences analyzed",
    )
    subjective_sentence_count = models.IntegerField(
        null=True,
        blank=True,
        help_text="Number of sentences classified as subjective",
    )
    avg_subjectivity_confidence = models.FloatField(
        null=True,
        blank=True,
        help_text="Average classifier confidence across all sentences",
    )

    # --- Framing (political leaning) results ---
    leaning_left = models.FloatField(
        null=True,
        blank=True,
        help_text="Probability of left-leaning framing (0.0-1.0)",
    )
    leaning_center = models.FloatField(
        null=True,
        blank=True,
        help_text="Probability of center framing (0.0-1.0)",
    )
    leaning_right = models.FloatField(
        null=True,
        blank=True,
        help_text="Probability of right-leaning framing (0.0-1.0)",
    )
    framing_chunks_analyzed = models.IntegerField(
        null=True,
        blank=True,
        help_text="Number of text chunks analyzed for framing",
    )

    # Metadata
    analyzed_at = models.DateTimeField(null=True, blank=True)
    model_versions = models.JSONField(
        default=dict,
        blank=True,
        help_text="Model names used for this analysis run",
    )

    class Meta:
        ordering = ['-analyzed_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
        ]

    def __str__(self):
        if self.subjectivity_ratio is not None:
            return f"Analysis of {self.article}: subj={self.subjectivity_ratio:.2f}"
        return f"Analysis of {self.article} ({self.status})"

    @property
    def dominant_leaning(self):
        """Return the label with highest probability, using margin-based center detection."""
        if self.leaning_left is None:
            return None
        from apps.analysis.utils import classify_leaning
        return classify_leaning(
            self.leaning_left,
            self.leaning_center,
            self.leaning_right,
        )

    @property
    def tone_label(self):
        """Human-readable tone label based on continuous subjectivity score."""
        if self.subjectivity_ratio is None:
            return None
        if self.subjectivity_ratio < 0.10:
            return 'Highly Objective'
        elif self.subjectivity_ratio < 0.15:
            return 'Mostly Objective'
        elif self.subjectivity_ratio < 0.22:
            return 'Mixed'
        elif self.subjectivity_ratio < 0.30:
            return 'Mostly Subjective'
        else:
            return 'Highly Subjective'
