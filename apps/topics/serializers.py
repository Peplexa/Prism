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

    class Meta:
        model = Topic
        fields = [
            'id', 'title', 'slug', 'description', 'keywords',
            'article_count', 'source_count', 'trending_score',
            'is_trending', 'first_article_at', 'last_article_at',
            'articles', 'created_at'
        ]

    def get_articles(self, obj):
        clusters = obj.clusters.select_related('article__source').all()
        return ArticleClusterSerializer(clusters, many=True).data
