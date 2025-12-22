from rest_framework import generics
from .models import Source, Article
from .serializers import SourceSerializer, ArticleListSerializer, ArticleDetailSerializer


class SourceListView(generics.ListAPIView):
    """List all news sources."""
    queryset = Source.objects.filter(is_active=True)
    serializer_class = SourceSerializer


class ArticleListView(generics.ListAPIView):
    """List articles with filtering."""
    serializer_class = ArticleListSerializer
    filterset_fields = ['source', 'status']
    search_fields = ['title', 'content']
    ordering_fields = ['published_at', 'created_at']
    ordering = ['-published_at']

    def get_queryset(self):
        return Article.objects.select_related('source').all()


class ArticleDetailView(generics.RetrieveAPIView):
    """Get article details."""
    queryset = Article.objects.select_related('source')
    serializer_class = ArticleDetailSerializer
