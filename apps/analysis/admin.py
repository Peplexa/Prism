from django.contrib import admin
from .models import ArticleAnalysis
from .tasks import analyze_article


@admin.register(ArticleAnalysis)
class ArticleAnalysisAdmin(admin.ModelAdmin):
    list_display = [
        'article_title', 'source_name', 'status',
        'subjectivity_ratio', 'dominant_leaning',
        'analyzed_at',
    ]
    list_filter = ['status', 'article__source']
    search_fields = ['article__title', 'article__source__name']
    readonly_fields = [
        'article', 'subjectivity_ratio', 'sentence_count',
        'subjective_sentence_count', 'avg_subjectivity_confidence',
        'leaning_left', 'leaning_center', 'leaning_right',
        'framing_chunks_analyzed', 'analyzed_at', 'model_versions',
        'created_at', 'updated_at',
    ]
    raw_id_fields = ['article']

    fieldsets = (
        (None, {
            'fields': ('article', 'status', 'error_message')
        }),
        ('Tone Analysis', {
            'fields': (
                'subjectivity_ratio', 'sentence_count',
                'subjective_sentence_count', 'avg_subjectivity_confidence',
            )
        }),
        ('Framing Analysis', {
            'fields': (
                'leaning_left', 'leaning_center', 'leaning_right',
                'framing_chunks_analyzed',
            )
        }),
        ('Metadata', {
            'fields': ('analyzed_at', 'model_versions', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def article_title(self, obj):
        return obj.article.title[:60]
    article_title.short_description = 'Article'

    def source_name(self, obj):
        return obj.article.source.name
    source_name.short_description = 'Source'

    def dominant_leaning(self, obj):
        return obj.dominant_leaning
    dominant_leaning.short_description = 'Leaning'

    actions = ['reanalyze_selected']

    def reanalyze_selected(self, request, queryset):
        count = 0
        for analysis in queryset:
            analyze_article.delay(analysis.article_id)
            count += 1
        self.message_user(request, f"Queued {count} articles for re-analysis.")
    reanalyze_selected.short_description = "Re-analyze selected articles"
