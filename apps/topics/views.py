from django.core.exceptions import ObjectDoesNotExist
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.articles.models import Article
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
        ).order_by('-trending_score')


class TopicDetailView(generics.RetrieveAPIView):
    """Get detailed topic with articles."""
    serializer_class = TopicDetailSerializer
    lookup_field = 'slug'

    def get_queryset(self):
        return Topic.objects.prefetch_related(
            'clusters__article__source',
        )


class TopicReportAPIView(APIView):
    """Full media comparison report as JSON."""

    def get(self, request, slug):
        try:
            topic = Topic.objects.get(slug=slug)
        except Topic.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)

        data = {
            'topic': {
                'title': topic.title,
                'slug': topic.slug,
                'article_count': topic.article_count,
                'source_count': topic.source_count,
            },
            'pool_status': None,
            'consensus_pool': None,
            'neutral_summary': None,
            'story_omission': topic.get_coverage_summary(),
            'omission_data': [],
            'tone_data': [],
            'framing_data': [],
            'source_summary': [],
            'nuggets': [],
        }

        # Consensus pool
        pool = None
        try:
            pool = topic.consensus_pool
            data['pool_status'] = pool.status
            data['consensus_pool'] = {
                'status': pool.status,
                'nugget_count': pool.nugget_count,
                'vital_nugget_count': pool.vital_nugget_count,
                'articles_processed': pool.articles_processed,
                'built_at': pool.built_at,
            }
        except ObjectDoesNotExist:
            pass

        # Neutral summary
        try:
            summary = topic.neutral_summary
            if summary.status == 'complete':
                data['neutral_summary'] = summary.summary_text
        except ObjectDoesNotExist:
            pass

        if not pool or pool.status != 'complete':
            return Response(data)

        # Use pre-computed report cache for speed
        cache = pool.report_cache
        if not cache:
            pool.build_report_cache()
            pool.refresh_from_db(fields=['report_cache'])
            cache = pool.report_cache

        if cache:
            data['omission_data'] = cache.get('omission_data', [])
            data['tone_data'] = cache.get('tone_data', [])
            data['framing_data'] = cache.get('framing_data', [])
            data['source_summary'] = cache.get('source_summary', [])
            data['nuggets'] = cache.get('nuggets', [])

        return Response(data)


class TopicNuggetsAPIView(APIView):
    """List consensus nuggets for a topic."""

    def get(self, request, slug):
        try:
            topic = Topic.objects.get(slug=slug)
        except Topic.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)

        try:
            pool = topic.consensus_pool
        except ObjectDoesNotExist:
            return Response({'nuggets': [], 'pool_status': None})

        nuggets = pool.nuggets.order_by('-source_count', 'id')

        importance = request.query_params.get('importance')
        if importance:
            nuggets = nuggets.filter(importance=importance)

        from apps.consensus.serializers import ConsensusNuggetSerializer
        return Response({
            'pool_status': pool.status,
            'nuggets': ConsensusNuggetSerializer(nuggets, many=True).data,
        })


class TopicOmissionAPIView(APIView):
    """Per-source omission scores for a topic."""

    def get(self, request, slug):
        try:
            topic = Topic.objects.get(slug=slug)
        except Topic.DoesNotExist:
            return Response({'detail': 'Not found.'}, status=404)

        try:
            pool = topic.consensus_pool
        except ObjectDoesNotExist:
            return Response({'scores': [], 'pool_status': None})

        from apps.consensus.models import OmissionScore
        scores = (
            OmissionScore.objects.filter(pool=pool)
            .select_related('article__source')
            .order_by('-coverage_score')
        )

        detail = request.query_params.get('detail', '').lower() == 'true'

        if detail:
            from apps.consensus.serializers import OmissionScoreDetailSerializer
            scores = scores.prefetch_related('judgments__consensus_nugget')
            serializer_class = OmissionScoreDetailSerializer
        else:
            from apps.consensus.serializers import OmissionScoreSerializer
            serializer_class = OmissionScoreSerializer

        results = []
        for score in scores:
            score_data = serializer_class(score).data
            score_data['source_name'] = score.article.source.name
            results.append(score_data)

        return Response({
            'pool_status': pool.status,
            'scores': results,
        })
