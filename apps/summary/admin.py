from django.contrib import admin
from .models import NeutralSummary


@admin.register(NeutralSummary)
class NeutralSummaryAdmin(admin.ModelAdmin):
    list_display = ['topic_title', 'status', 'nuggets_used', 'model_name', 'generated_at']
    list_filter = ['status']
    readonly_fields = [
        'topic', 'status', 'summary_text', 'nuggets_used',
        'model_name', 'generated_at', 'error_message',
        'created_at', 'updated_at',
    ]

    @admin.display(description='Topic')
    def topic_title(self, obj):
        return obj.topic.title[:60]
