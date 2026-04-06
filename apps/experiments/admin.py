from django.contrib import admin

from .models import Experiment, ExperimentResult, PromptVersion


@admin.register(PromptVersion)
class PromptVersionAdmin(admin.ModelAdmin):
    list_display = ["name", "version", "is_active", "created_at"]
    list_filter = ["is_active", "name"]
    search_fields = ["name", "description"]


@admin.register(Experiment)
class ExperimentAdmin(admin.ModelAdmin):
    list_display = ["name", "source", "sample_size", "status", "created_at"]
    list_filter = ["status", "source"]
    filter_horizontal = ["prompt_versions"]


@admin.register(ExperimentResult)
class ExperimentResultAdmin(admin.ModelAdmin):
    list_display = ["experiment", "prompt_version", "f1_score", "created_at"]
    list_filter = ["experiment"]
