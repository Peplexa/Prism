from django.contrib import admin

from .models import DataSource, Document, GroundTruthFact


@admin.register(DataSource)
class DataSourceAdmin(admin.ModelAdmin):
    list_display = ["name", "loader_class", "created_at"]
    search_fields = ["name"]


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ["external_id", "source", "split", "title", "created_at"]
    list_filter = ["source", "split"]
    search_fields = ["external_id", "title"]


@admin.register(GroundTruthFact)
class GroundTruthFactAdmin(admin.ModelAdmin):
    list_display = ["fact_type", "fact_text_preview", "document", "confidence"]
    list_filter = ["fact_type", "document__source"]
    search_fields = ["fact_text"]

    def fact_text_preview(self, obj):
        return obj.fact_text[:80] + "..." if len(obj.fact_text) > 80 else obj.fact_text

    fact_text_preview.short_description = "Fact"
