from django.db import models


class DataSource(models.Model):
    """Represents a dataset source (Rotowire, BillSum)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    loader_class = models.CharField(max_length=200)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Document(models.Model):
    """A document from a dataset (game summary, bill text)."""

    source = models.ForeignKey(
        DataSource, on_delete=models.CASCADE, related_name="documents"
    )
    external_id = models.CharField(max_length=200)
    split = models.CharField(max_length=20)  # train/valid/test

    # For Rotowire: summary text; For BillSum: bill text
    primary_text = models.TextField()

    # For Rotowire: box score JSON; For BillSum: summary text
    reference_content = models.JSONField()

    title = models.CharField(max_length=500, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["source", "external_id"]

    def __str__(self):
        return f"{self.source.name}:{self.external_id}"


class GroundTruthFact(models.Model):
    """Individual facts extracted from reference content (ground truth)."""

    document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="ground_truth_facts"
    )
    fact_text = models.TextField()
    fact_type = models.CharField(max_length=100)  # player_stat, provision, etc.
    confidence = models.FloatField(default=1.0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.fact_type}: {self.fact_text[:50]}..."
