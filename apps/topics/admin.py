from django.contrib import admin
from .models import Topic, ArticleCluster


class ArticleClusterInline(admin.TabularInline):
    model = ArticleCluster
    extra = 0
    readonly_fields = ['article', 'confidence_score', 'cluster_rank']
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'article_count', 'source_count',
        'trending_score', 'is_trending', 'last_article_at'
    ]
    list_filter = ['is_trending', 'created_at']
    search_fields = ['title', 'description', 'keywords']
    prepopulated_fields = {'slug': ('title',)}
    readonly_fields = [
        'article_count', 'source_count', 'event_registry_uri',
        'first_article_at', 'last_article_at', 'created_at', 'updated_at'
    ]
    inlines = [ArticleClusterInline]

    fieldsets = (
        (None, {
            'fields': ('title', 'slug', 'description', 'keywords')
        }),
        ('Metrics', {
            'fields': ('article_count', 'source_count', 'trending_score', 'is_trending')
        }),
        ('Event Registry', {
            'fields': ('event_registry_uri',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('first_article_at', 'last_article_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['recalculate_metrics']

    def recalculate_metrics(self, request, queryset):
        for topic in queryset:
            topic.update_metrics()
        self.message_user(request, f"Updated metrics for {queryset.count()} topics.")
    recalculate_metrics.short_description = "Recalculate metrics for selected topics"


@admin.register(ArticleCluster)
class ArticleClusterAdmin(admin.ModelAdmin):
    list_display = ['article', 'topic', 'confidence_score', 'cluster_rank']
    list_filter = ['topic']
    search_fields = ['article__title', 'topic__title']
    raw_id_fields = ['article', 'topic']
