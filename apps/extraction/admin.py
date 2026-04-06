from django.contrib import admin

from .models import ExtractedNugget, ExtractionRun


@admin.register(ExtractionRun)
class ExtractionRunAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "source",
        "prompt_version",
        "model_name",
        "status",
        "documents_processed",
        "documents_total",
        "created_at",
    ]
    list_filter = ["status", "source", "model_name"]
    search_fields = ["name"]


@admin.register(ExtractedNugget)
class ExtractedNuggetAdmin(admin.ModelAdmin):
    list_display = ["nugget_type", "nugget_text_preview", "document", "extraction_run"]
    list_filter = ["nugget_type", "extraction_run"]
    search_fields = ["nugget_text"]

    def nugget_text_preview(self, obj):
        return obj.nugget_text[:80] + "..." if len(obj.nugget_text) > 80 else obj.nugget_text

    nugget_text_preview.short_description = "Nugget"
