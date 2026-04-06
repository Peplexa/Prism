from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers
from .models import Topic, ArticleCluster
from apps.articles.serializers import ArticleListSerializer


class TopicListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Topic
        fields = [
            'id', 'title', 'slug', 'keywords', 'article_count',
            'source_count', 'trending_score', 'is_trending',
            'first_article_at', 'last_article_at'
        ]


class ArticleClusterSerializer(serializers.ModelSerializer):
    article = ArticleListSerializer(read_only=True)

    class Meta:
        model = ArticleCluster
        fields = ['id', 'article', 'confidence_score', 'cluster_rank']


class TopicDetailSerializer(serializers.ModelSerializer):
    articles = serializers.SerializerMethodField()
    consensus_pool = serializers.SerializerMethodField()
    coverage_summary = serializers.SerializerMethodField()

    class Meta:
        model = Topic
        fields = [
            'id', 'title', 'slug', 'description', 'keywords',
            'article_count', 'source_count', 'trending_score',
            'is_trending', 'first_article_at', 'last_article_at',
            'event_registry_uri', 'articles', 'consensus_pool',
            'coverage_summary', 'created_at'
        ]

    def get_articles(self, obj):
        clusters = obj.clusters.select_related('article__source').all()
        return ArticleClusterSerializer(clusters, many=True).data

    def get_consensus_pool(self, obj):
        from apps.consensus.serializers import ConsensusPoolSummarySerializer
        try:
            pool = obj.consensus_pool
            return ConsensusPoolSummarySerializer(pool).data
        except ObjectDoesNotExist:
            return None

    def get_coverage_summary(self, obj):
        return obj.get_coverage_summary()
