from rest_framework import serializers
from .models import Source, Article
from apps.analysis.models import ArticleAnalysis


class SourceMinimalSerializer(serializers.ModelSerializer):
    bias_label = serializers.CharField(source='get_known_bias_display', read_only=True)

    class Meta:
        model = Source
        fields = ['id', 'name', 'slug', 'known_bias', 'bias_label', 'logo_url']


class SourceSerializer(SourceMinimalSerializer):
    class Meta(SourceMinimalSerializer.Meta):
        fields = SourceMinimalSerializer.Meta.fields + [
            'website_url', 'event_registry_uri'
        ]


class ArticleListSerializer(serializers.ModelSerializer):
    source = SourceMinimalSerializer(read_only=True)

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'url', 'source',
            'published_at', 'status', 'word_count', 'sentiment',
            'created_at'
        ]


class ArticleAnalysisSerializer(serializers.ModelSerializer):
    tone_label = serializers.CharField(read_only=True)
    dominant_leaning = serializers.CharField(read_only=True)

    class Meta:
        model = ArticleAnalysis
        fields = [
            'status', 'subjectivity_ratio', 'sentence_count',
            'subjective_sentence_count', 'tone_label',
            'leaning_left', 'leaning_center', 'leaning_right',
            'dominant_leaning', 'analyzed_at',
        ]


class ArticleDetailSerializer(serializers.ModelSerializer):
    source = SourceSerializer(read_only=True)
    analysis = ArticleAnalysisSerializer(read_only=True)
    omission = serializers.SerializerMethodField()

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'url', 'source', 'author',
            'summary', 'content', 'published_at', 'status',
            'word_count', 'sentiment', 'analysis', 'omission',
            'created_at', 'updated_at'
        ]

    def get_omission(self, obj):
        from apps.consensus.serializers import OmissionScoreSerializer
        score = obj.omission_scores.first()
        if score:
            return OmissionScoreSerializer(score).data
        return None
