"""Admin interface for consensus pool and omission scoring."""

from django.contrib import admin

from .models import (
    ConsensusPool,
    ConsensusNugget,
    Contradiction,
    RawNugget,
    OmissionScore,
    NuggetJudgment,
)


class ConsensusNuggetInline(admin.TabularInline):
    model = ConsensusNugget
    extra = 0
    readonly_fields = [
        'nugget_text', 'importance', 'tier', 'source_count', 'source_names',
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class OmissionScoreInline(admin.TabularInline):
    model = OmissionScore
    extra = 0
    readonly_fields = [
        'article', 'coverage_score', 'omission_rate',
        'vital_omission_rate', 'support_count',
        'partial_support_count', 'not_support_count',
    ]
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ConsensusPool)
class ConsensusPoolAdmin(admin.ModelAdmin):
    list_display = [
        'topic_title', 'status', 'nugget_count',
        'vital_nugget_count', 'articles_processed', 'built_at',
    ]
    list_filter = ['status']
    readonly_fields = [
        'topic', 'status', 'articles_processed',
        'nugget_count', 'vital_nugget_count',
        'model_name', 'similarity_threshold',
        'built_at', 'error_message',
        'created_at', 'updated_at',
    ]
    inlines = [ConsensusNuggetInline, OmissionScoreInline]  # ContradictionInline added below

    actions = ['rebuild_pool']

    @admin.display(description='Topic')
    def topic_title(self, obj):
        return obj.topic.title[:60]

    @admin.action(description='Rebuild selected pools')
    def rebuild_pool(self, request, queryset):
        from .tasks import build_consensus_pool
        for pool in queryset:
            build_consensus_pool.delay(pool.topic_id, rebuild=True)
        self.message_user(
            request,
            f"Queued {queryset.count()} pools for rebuild.",
        )


@admin.register(ConsensusNugget)
class ConsensusNuggetAdmin(admin.ModelAdmin):
    list_display = [
        'nugget_text_short', 'tier', 'importance', 'source_count',
        'source_names', 'pool',
    ]
    list_filter = ['importance', 'tier', 'pool']
    readonly_fields = [
        'pool', 'nugget_text', 'importance', 'tier',
        'source_count', 'source_names', 'cluster_id',
    ]

    @admin.display(description='Nugget')
    def nugget_text_short(self, obj):
        return obj.nugget_text[:80]


@admin.register(OmissionScore)
class OmissionScoreAdmin(admin.ModelAdmin):
    list_display = [
        'article_title', 'source_name', 'coverage_pct',
        'weighted_coverage_pct', 'vital_omission_pct',
        'support_count', 'not_support_count', 'total_nuggets', 'scored_at',
    ]
    list_filter = ['pool']
    readonly_fields = [
        'pool', 'article', 'omission_rate',
        'vital_omission_rate', 'coverage_score',
        'support_count', 'partial_support_count',
        'not_support_count', 'total_nuggets',
        'vital_support_count', 'vital_partial_support_count', 'vital_total',
        'scored_at', 'error_message',
    ]

    @admin.display(description='Article')
    def article_title(self, obj):
        return obj.article.title[:60]

    @admin.display(description='Source')
    def source_name(self, obj):
        return obj.article.source.name

    @admin.display(description='Coverage')
    def coverage_pct(self, obj):
        if obj.coverage_score is not None:
            return f"{obj.coverage_score:.0%}"
        return '-'

    @admin.display(description='Weighted Coverage')
    def weighted_coverage_pct(self, obj):
        wcs = obj.weighted_coverage_score
        if wcs is not None:
            return f"{wcs:.0%}"
        return '-'

    @admin.display(description='Vital Omission')
    def vital_omission_pct(self, obj):
        if obj.vital_omission_rate is not None:
            return f"{obj.vital_omission_rate:.0%}"
        return '-'


@admin.register(Contradiction)
class ContradictionAdmin(admin.ModelAdmin):
    list_display = ['pool_topic', 'nugget_a_short', 'nugget_b_short', 'created_at']
    list_filter = ['pool']
    readonly_fields = [
        'pool', 'nugget_a', 'nugget_b', 'explanation',
        'created_at', 'updated_at',
    ]

    @admin.display(description='Topic')
    def pool_topic(self, obj):
        return obj.pool.topic.title[:40]

    @admin.display(description='Claim A')
    def nugget_a_short(self, obj):
        return obj.nugget_a.nugget_text[:50]

    @admin.display(description='Claim B')
    def nugget_b_short(self, obj):
        return obj.nugget_b.nugget_text[:50]
