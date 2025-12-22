from rest_framework import generics
from .models import Topic
from .serializers import TopicListSerializer, TopicDetailSerializer


class TopicListView(generics.ListAPIView):
    """List all topics with pagination."""
    serializer_class = TopicListSerializer
    search_fields = ['title', 'keywords']
    ordering_fields = ['trending_score', 'last_article_at', 'article_count']
    ordering = ['-trending_score']

    def get_queryset(self):
        return Topic.objects.filter(article_count__gte=1)


class TrendingTopicsView(generics.ListAPIView):
    """List trending topics."""
    serializer_class = TopicListSerializer

    def get_queryset(self):
        return Topic.objects.filter(
            is_trending=True
        ).order_by('-trending_score')[:20]


class TopicDetailView(generics.RetrieveAPIView):
    """Get detailed topic with articles."""
    serializer_class = TopicDetailSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return Topic.objects.prefetch_related(
            'clusters__article__source',
        )
