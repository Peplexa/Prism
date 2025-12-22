from django.views.generic import TemplateView, DetailView, ListView
from django.http import HttpResponse
from apps.topics.models import Topic
from apps.articles.models import Article


class HomeView(TemplateView):
    """Hero page with search bar."""
    template_name = 'home/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['trending_topics'] = Topic.objects.filter(
            is_trending=True
        ).order_by('-trending_score')[:6]
        return context


class IdeasView(ListView):
    """Trending/popular topics page."""
    template_name = 'ideas/list.html'
    model = Topic
    context_object_name = 'topics'
    paginate_by = 20

    def get_queryset(self):
        return Topic.objects.filter(
            article_count__gte=2
        ).order_by('-trending_score', '-last_article_at')


class TopicDetailView(DetailView):
    """Story cluster view with all coverage."""
    template_name = 'topics/detail.html'
    model = Topic
    context_object_name = 'topic'
    slug_field = 'slug'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        topic = self.object

        # Get articles with source info
        context['articles'] = Article.objects.filter(
            cluster__topic=topic
        ).select_related('source').order_by('-published_at')

        # Group by source for display
        sources = {}
        for article in context['articles']:
            source_name = article.source.name
            if source_name not in sources:
                sources[source_name] = {
                    'source': article.source,
                    'articles': []
                }
            sources[source_name]['articles'].append(article)
        context['sources'] = sources

        return context


class ArticleDetailView(DetailView):
    """Individual article view."""
    template_name = 'articles/detail.html'
    model = Article
    context_object_name = 'article'

    def get_queryset(self):
        return Article.objects.select_related('source')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        article = self.object

        try:
            if article.cluster:
                context['related_articles'] = Article.objects.filter(
                    cluster__topic=article.cluster.topic
                ).exclude(id=article.id).select_related('source')[:5]
        except Article.cluster.RelatedObjectDoesNotExist:
            pass

        return context


class SearchResultsView(ListView):
    """Full search results page."""
    template_name = 'search/results.html'
    model = Topic
    context_object_name = 'topics'
    paginate_by = 20

    def get_queryset(self):
        query = self.request.GET.get('q', '').strip()
        if len(query) < 2:
            return Topic.objects.none()

        return Topic.objects.filter(
            title__icontains=query
        ).order_by('-trending_score', '-last_article_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['query'] = self.request.GET.get('q', '').strip()
        return context


# HTMX Partial Views
class SearchResultsPartial(TemplateView):
    """HTMX partial for live search results."""
    template_name = 'home/partials/search_results.html'

    def get(self, request, *args, **kwargs):
        query = request.GET.get('q', '').strip()

        if len(query) < 2:
            return HttpResponse('')

        # Search topics
        topics = Topic.objects.filter(
            title__icontains=query
        )[:10]

        # Check if it's a URL (article submission)
        is_url = query.startswith('http://') or query.startswith('https://')

        context = {
            'topics': topics,
            'query': query,
            'is_url': is_url,
        }

        return self.render_to_response(context)


class TopicListPartial(TemplateView):
    """HTMX partial for topic list."""
    template_name = 'ideas/partials/topic_list.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['topics'] = Topic.objects.filter(
            article_count__gte=1
        ).order_by('-trending_score')[:20]
        return context
