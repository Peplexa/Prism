"""Serializers for consensus pool and omission scoring."""

from rest_framework import serializers

from .models import ConsensusPool, ConsensusNugget, OmissionScore, NuggetJudgment


class ConsensusPoolSummarySerializer(serializers.ModelSerializer):
    """Summary of a consensus pool for topic detail views."""

    class Meta:
        model = ConsensusPool
        fields = [
            'status', 'nugget_count', 'vital_nugget_count',
            'articles_processed', 'built_at',
        ]


class NuggetJudgmentSerializer(serializers.ModelSerializer):
    """Individual nugget judgment for detailed omission breakdown."""
    nugget_text = serializers.CharField(
        source='consensus_nugget.nugget_text', read_only=True
    )
    importance = serializers.CharField(
        source='consensus_nugget.importance', read_only=True
    )

    class Meta:
        model = NuggetJudgment
        fields = ['nugget_text', 'importance', 'label']


class OmissionScoreSerializer(serializers.ModelSerializer):
    """Omission score for article detail views."""
    weighted_coverage_score = serializers.FloatField(read_only=True)

    class Meta:
        model = OmissionScore
        fields = [
            'omission_rate', 'vital_omission_rate', 'coverage_score',
            'weighted_coverage_score',
            'support_count', 'partial_support_count', 'not_support_count',
            'total_nuggets', 'vital_support_count', 'vital_partial_support_count',
            'vital_total', 'scored_at',
        ]


class OmissionScoreDetailSerializer(OmissionScoreSerializer):
    """Omission score with per-nugget judgments."""
    judgments = NuggetJudgmentSerializer(many=True, read_only=True)

    class Meta(OmissionScoreSerializer.Meta):
        fields = OmissionScoreSerializer.Meta.fields + ['judgments']


class ConsensusNuggetSerializer(serializers.ModelSerializer):
    """Serializer for consensus nuggets list endpoint."""

    class Meta:
        model = ConsensusNugget
        fields = [
            'id', 'nugget_text', 'importance',
            'source_count', 'source_names', 'cluster_id',
        ]


class NeutralSummarySerializer(serializers.Serializer):
    """Serializer for neutral summary data."""
    summary_text = serializers.CharField()
    nuggets_used = serializers.IntegerField()
    status = serializers.CharField()
    generated_at = serializers.DateTimeField()
