from django.db import models


class EvaluationRun(models.Model):
    """An evaluation comparing extracted nuggets to ground truth."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    MATCHER_CHOICES = [
        ("semantic", "Semantic Similarity"),
        ("exact", "Exact Match"),
        ("fuzzy", "Fuzzy Match"),
        ("llm", "LLM AutoAssign"),
    ]

    extraction_run = models.ForeignKey(
        "extraction.ExtractionRun",
        on_delete=models.CASCADE,
        related_name="evaluation_runs",
    )
    matcher_type = models.CharField(
        max_length=100, choices=MATCHER_CHOICES, default="semantic"
    )
    matcher_config = models.JSONField(default=dict, blank=True)  # Threshold, model, etc.
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Eval of {self.extraction_run.name} ({self.status})"


class MatchResult(models.Model):
    """Individual match between extracted nugget and ground truth."""

    MATCH_TYPE_CHOICES = [
        ("true_positive", "True Positive"),
        ("false_positive", "False Positive"),
        ("false_negative", "False Negative"),
        # AutoNuggetizer-style labels
        ("support", "Support (Full)"),
        ("partial_support", "Partial Support"),
        ("not_support", "Not Supported"),
    ]

    evaluation_run = models.ForeignKey(
        EvaluationRun, on_delete=models.CASCADE, related_name="matches"
    )
    document = models.ForeignKey(
        "datasets.Document", on_delete=models.CASCADE, related_name="match_results"
    )
    extracted_nugget = models.ForeignKey(
        "extraction.ExtractedNugget",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="match_results",
    )
    ground_truth_fact = models.ForeignKey(
        "datasets.GroundTruthFact",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="match_results",
    )
    similarity_score = models.FloatField(null=True, blank=True)
    match_type = models.CharField(max_length=50, choices=MATCH_TYPE_CHOICES)

    def __str__(self):
        return f"{self.match_type} (score: {self.similarity_score or 'N/A'})"


class ScoreReport(models.Model):
    """Aggregate scores for an evaluation run."""

    evaluation_run = models.OneToOneField(
        EvaluationRun, on_delete=models.CASCADE, related_name="score_report"
    )
    precision = models.FloatField()
    recall = models.FloatField()
    f1_score = models.FloatField()
    true_positives = models.IntegerField()
    false_positives = models.IntegerField()
    false_negatives = models.IntegerField()
    detailed_metrics = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"F1: {self.f1_score:.3f} (P: {self.precision:.3f}, R: {self.recall:.3f})"
