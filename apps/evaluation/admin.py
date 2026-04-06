from django.contrib import admin

from .models import EvaluationRun, MatchResult, ScoreReport


@admin.register(EvaluationRun)
class EvaluationRunAdmin(admin.ModelAdmin):
    list_display = [
        "extraction_run",
        "matcher_type",
        "status",
        "get_f1_score",
        "created_at",
    ]
    list_filter = ["status", "matcher_type"]

    def get_f1_score(self, obj):
        if hasattr(obj, "score_report"):
            return f"{obj.score_report.f1_score:.3f}"
        return "-"

    get_f1_score.short_description = "F1 Score"


@admin.register(MatchResult)
class MatchResultAdmin(admin.ModelAdmin):
    list_display = [
        "match_type",
        "document",
        "similarity_score",
        "evaluation_run",
    ]
    list_filter = ["match_type", "evaluation_run"]


@admin.register(ScoreReport)
class ScoreReportAdmin(admin.ModelAdmin):
    list_display = [
        "evaluation_run",
        "f1_score",
        "precision",
        "recall",
        "true_positives",
        "false_positives",
        "false_negatives",
    ]
