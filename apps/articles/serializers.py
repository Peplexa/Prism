from rest_framework import serializers
from .models import Source, Article


class SourceMinimalSerializer(serializers.ModelSerializer):
    bias_label = serializers.CharField(source='get_known_bias_display', read_only=True)

    class Meta:
        model = Source
        fields = ['id', 'name', 'slug', 'known_bias', 'bias_label', 'logo_url']


class SourceSerializer(SourceMinimalSerializer):
    class Meta(SourceMinimalSerializer.Meta):
        fields = SourceMinimalSerializer.Meta.fields + ['website_url']


class ArticleListSerializer(serializers.ModelSerializer):
    source = SourceMinimalSerializer(read_only=True)

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'url', 'source',
            'published_at', 'status', 'word_count', 'created_at'
        ]


class ArticleDetailSerializer(serializers.ModelSerializer):
    source = SourceSerializer(read_only=True)

    class Meta:
        model = Article
        fields = [
            'id', 'title', 'slug', 'url', 'source', 'author',
            'summary', 'content', 'published_at', 'status',
            'word_count', 'created_at', 'updated_at'
        ]
