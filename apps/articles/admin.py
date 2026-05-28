from django.contrib import admin
from .models import Source, Article


@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ['name', 'event_registry_uri', 'is_active']
    list_filter = ['is_active']
    search_fields = ['name', 'website_url', 'event_registry_uri']
    prepopulated_fields = {'slug': ('name',)}
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        (None, {
            'fields': ('name', 'slug', 'website_url', 'logo_url')
        }),
        ('Event Registry', {
            'fields': ('event_registry_uri',)
        }),
        ('Metadata', {
            'fields': ('is_active',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    list_display = ['title_short', 'source', 'status', 'is_wire_content', 'published_at', 'word_count', 'sentiment']
    list_filter = ['status', 'source', 'is_wire_content', 'published_at']
    search_fields = ['title', 'content', 'url']
    readonly_fields = ['word_count', 'event_registry_uri', 'sentiment', 'created_at', 'updated_at']
    date_hierarchy = 'published_at'

    fieldsets = (
        (None, {
            'fields': ('source', 'title', 'slug', 'url', 'author')
        }),
        ('Content', {
            'fields': ('summary', 'content', 'word_count')
        }),
        ('Processing', {
            'fields': ('status', 'is_wire_content', 'published_at')
        }),
        ('Event Registry', {
            'fields': ('event_registry_uri', 'sentiment'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def title_short(self, obj):
        return obj.title[:60] + '...' if len(obj.title) > 60 else obj.title
    title_short.short_description = 'Title'
