from django.db import models


class ExtractionRun(models.Model):
    """A batch extraction run."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    name = models.CharField(max_length=200)
    source = models.ForeignKey(
        "datasets.DataSource", on_delete=models.CASCADE, related_name="extraction_runs"
    )
    prompt_version = models.ForeignKey(
        "experiments.PromptVersion",
        on_delete=models.SET_NULL,
        null=True,
        related_name="extraction_runs",
    )
    model_name = models.CharField(max_length=100)  # e.g., 'deepseek-r1:8b'
    parameters = models.JSONField(default=dict, blank=True)  # Temperature, etc.
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    documents_processed = models.IntegerField(default=0)
    documents_total = models.IntegerField(default=0)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.status})"


class ExtractedNugget(models.Model):
    """A nugget (atomic fact) extracted by the LLM."""

    extraction_run = models.ForeignKey(
        ExtractionRun, on_delete=models.CASCADE, related_name="nuggets"
    )
    document = models.ForeignKey(
        "datasets.Document", on_delete=models.CASCADE, related_name="extracted_nuggets"
    )
    nugget_text = models.TextField()
    nugget_type = models.CharField(max_length=100, blank=True)
    confidence = models.FloatField(null=True, blank=True)
    raw_response = models.TextField(blank=True)  # Original LLM response
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nugget_type}: {self.nugget_text[:50]}..."
