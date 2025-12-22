from django.contrib import admin
from .models import Source, Article


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ['name', 'known_bias', 'discovery_method', 'is_active', 'last_scraped_at']
    list_filter = ['known_bias', 'discovery_method', 'is_active']
    search_fields = ['name', 'website_url']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['last_scraped_at', 'created_at', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'website_url', 'logo_url')
        }),
        ('Discovery Settings', {
            'fields': ('discovery_method', 'discovery_url', 'article_link_selector')
        }),
        ('Metadata', {
            'fields': ('known_bias', 'is_active', 'scrape_frequency_hours')
        }),
        ('Timestamps', {
            'fields': ('last_scraped_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title_short', 'source', 'status', 'published_at', 'word_count']
    list_filter = ['status', 'source', 'published_at']
    search_fields = ['title', 'content', 'url']
    readonly_fields = ['word_count', 'created_at', 'updated_at']
    date_hierarchy = 'published_at'

    fieldsets = (
        (None, {
            'fields': ('source', 'title', 'slug', 'url', 'author')
        }),
        ('Content', {
            'fields': ('summary', 'content', 'word_count')
        }),
        ('Processing', {
            'fields': ('status', 'error_message', 'published_at')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def title_short(self, obj):
        return obj.title[:60] + '...' if len(obj.title) > 60 else obj.title
    title_short.short_description = 'Title'
