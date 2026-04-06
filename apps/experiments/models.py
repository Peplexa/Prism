from django.db import models


class PromptVersion(models.Model):
    """Version-controlled extraction prompts."""

    name = models.CharField(max_length=200)
    version = models.CharField(max_length=50)
    system_prompt = models.TextField()
    user_prompt_template = models.TextField()  # Contains {text} placeholder
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ["name", "version"]

    def __str__(self):
        return f"{self.name} v{self.version}"

    def render_user_prompt(self, text: str, **kwargs) -> str:
        """Render the user prompt template with the given text."""
        return self.user_prompt_template.format(text=text, **kwargs)


class Experiment(models.Model):
    """A prompt tuning experiment."""

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    source = models.ForeignKey(
        "datasets.DataSource", on_delete=models.CASCADE, related_name="experiments"
    )
    prompt_versions = models.ManyToManyField(PromptVersion, related_name="experiments")
    sample_size = models.IntegerField(default=100)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class ExperimentResult(models.Model):
    """Results for a specific prompt version in an experiment."""

    experiment = models.ForeignKey(
        Experiment, on_delete=models.CASCADE, related_name="results"
    )
    prompt_version = models.ForeignKey(
        PromptVersion, on_delete=models.CASCADE, related_name="experiment_results"
    )
    evaluation_run = models.ForeignKey(
        "evaluation.EvaluationRun",
        on_delete=models.CASCADE,
        related_name="experiment_results",
    )
    f1_score = models.FloatField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.experiment.name} - {self.prompt_version} (F1: {self.f1_score:.3f})"
