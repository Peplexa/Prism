import json

from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import cache_page
from django.views.generic import TemplateView, DetailView, ListView

from apps.analysis.models import ArticleAnalysis
from apps.articles.models import Article, Source
from apps.topics.models import Topic
from apps.web.models import UserPreference


@method_decorator(cache_page(60 * 2), name='dispatch')
class HomeView(TemplateView):
    """Hero page with search bar."""
    template_name = 'home/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        trending = Topic.objects.filter(
            is_trending=True
        ).order_by('-trending_score')[:6]

        if not trending:
            # Fallback: show topics with most coverage
            trending = Topic.objects.filter(
                article_count__gte=1
            ).order_by('-article_count', '-trending_score')[:6]

        context['trending_topics'] = trending
        return context


@method_decorator(cache_page(60 * 2), name='dispatch')
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

        # Analysis data (tone + framing)
        try:
            analysis = article.analysis
            if analysis.status == 'complete':
                context['analysis'] = analysis
                context['subjectivity_pct'] = round(analysis.subjectivity_ratio * 100) if analysis.subjectivity_ratio is not None else None
                context['left_pct'] = round(analysis.leaning_left * 100) if analysis.leaning_left is not None else None
                context['center_pct'] = round(analysis.leaning_center * 100) if analysis.leaning_center is not None else None
                context['right_pct'] = round(analysis.leaning_right * 100) if analysis.leaning_right is not None else None
        except ObjectDoesNotExist:
            pass

        # Omission data
        omission = article.omission_scores.select_related('pool__topic').first()
        if omission and omission.coverage_score is not None:
            context['omission'] = omission
            context['coverage_pct'] = round(omission.coverage_score * 100)

        # Topic + related articles
        try:
            if article.cluster:
                context['topic'] = article.cluster.topic
                context['related_articles'] = Article.objects.filter(
                    cluster__topic=article.cluster.topic
                ).exclude(id=article.id).select_related('source')[:5]
        except ObjectDoesNotExist:
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
            Q(title__icontains=query) | Q(description__icontains=query),
            article_count__gte=1,
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

        # Search topics by title and description (exclude empty topics)
        topics = Topic.objects.filter(
            Q(title__icontains=query) | Q(description__icontains=query),
            article_count__gte=1,
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


class TopicReportView(DetailView):
    """Media Comparison Report for a topic."""
    template_name = 'topics/report.html'
    model = Topic
    context_object_name = 'topic'
    slug_field = 'slug'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        topic = self.object

        # Consensus pool
        pool = None
        try:
            pool = topic.consensus_pool
        except ObjectDoesNotExist:
            pass
        context['pool'] = pool

        # Neutral summary
        summary = None
        try:
            summary = topic.neutral_summary
        except ObjectDoesNotExist:
            pass
        context['summary'] = summary

        # Story-level omission
        context['coverage_summary'] = topic.get_coverage_summary()

        # Source articles (lightweight query for article links)
        context['source_articles'] = list(
            Article.objects.filter(cluster__topic=topic)
            .select_related('source')
            .order_by('source__name', '-published_at')
        )

        # Publication timeline — deduplicate by source (keep earliest)
        timeline_articles = sorted(
            [a for a in context['source_articles'] if a.published_at],
            key=lambda a: a.published_at,
        )
        if timeline_articles:
            earliest = timeline_articles[0].published_at
            latest = timeline_articles[-1].published_at
            span_seconds = max(
                (latest - earliest).total_seconds(), 1
            )
            # Group by source: keep earliest article, count duplicates
            from collections import OrderedDict
            source_groups = OrderedDict()
            for a in timeline_articles:
                name = a.source.name
                if name not in source_groups:
                    source_groups[name] = {'article': a, 'count': 1}
                else:
                    source_groups[name]['count'] += 1

            timeline_items = []
            for name, grp in source_groups.items():
                a = grp['article']
                timeline_items.append({
                    'source_name': name,
                    'published_at': a.published_at,
                    'offset_pct': round(
                        (a.published_at - earliest).total_seconds()
                        / span_seconds * 100, 1
                    ),
                    'delta_minutes': int(
                        (a.published_at - earliest).total_seconds() / 60
                    ),
                    'article_count': grp['count'],
                })
            # Sort by time
            timeline_items.sort(key=lambda x: x['published_at'])

            context['publication_timeline'] = timeline_items
            context['timeline_json'] = json.dumps([
                {
                    'source_name': item['source_name'],
                    'published_at': item['published_at'].isoformat(),
                    'offset_pct': item['offset_pct'],
                    'delta_minutes': item['delta_minutes'],
                    'article_count': item['article_count'],
                }
                for item in timeline_items
            ], default=str)
            context['timeline_start'] = earliest
            context['timeline_end'] = latest

        if not pool or pool.status != 'complete':
            return context

        # Use pre-computed report cache (built after pool completion).
        # If cache is missing (old pool), build it now on first access.
        cache = pool.report_cache
        if not cache:
            pool.build_report_cache()
            pool.refresh_from_db(fields=['report_cache'])
            cache = pool.report_cache

        if not cache:
            return context

        omission_data = cache.get('omission_data', [])
        tone_data = cache.get('tone_data', [])
        framing_data = cache.get('framing_data', [])

        context['omission_data'] = omission_data
        context['tone_data'] = tone_data
        context['framing_data'] = framing_data
        context['source_summary'] = cache.get('source_summary', [])

        # Nuggets
        nuggets = cache.get('nuggets', [])
        context['all_nuggets'] = nuggets
        has_tiers = any(n.get('tier') is not None for n in nuggets)
        context['has_tiers'] = has_tiers

        # Fact matrix
        matrix_data = cache.get('matrix_data', {})
        matrix_sources = cache.get('matrix_sources', [])

        display_nuggets = nuggets

        matrix_rows = []
        for nugget in display_nuggets:
            nug_judgments = matrix_data.get(str(nugget['id']), {})
            matrix_rows.append({
                'nugget_id': nugget['id'],
                'nugget_text': nugget['text'],
                'importance': nugget['importance'],
                'tier': nugget.get('tier'),
                'source_count': nugget['source_count'],
                'theme': nugget.get('theme', ''),
                'cells': {
                    src: nug_judgments.get(src, 'no_data')
                    for src in matrix_sources
                },
            })

        context['matrix_rows'] = matrix_rows
        context['matrix_sources'] = matrix_sources
        context['matrix_truncated'] = False

        # Filter button counts — from display_nuggets so counts match rendered rows
        context['vital_nuggets'] = [n for n in display_nuggets if n['importance'] == 'vital']
        if has_tiers:
            context['tier1_nuggets'] = [n for n in display_nuggets if n.get('tier') == 1]
            context['tier2_nuggets'] = [n for n in display_nuggets if n.get('tier') == 2]
            context['tier3_nuggets'] = [n for n in display_nuggets if n.get('tier') == 3]

        # Group matrix rows by theme for display
        from collections import OrderedDict
        themed_groups = OrderedDict()
        for row in matrix_rows:
            theme = row.get('theme') or 'Uncategorized'
            if theme not in themed_groups:
                themed_groups[theme] = []
            themed_groups[theme].append(row)
        context['themed_groups'] = dict(themed_groups)
        context['has_themes'] = any(n.get('theme') for n in display_nuggets)

        # JSON for Chart.js
        context['omission_json'] = json.dumps(omission_data)
        context['tone_json'] = json.dumps(tone_data)
        context['framing_json'] = json.dumps(framing_data)
        # Contradictions
        contradictions = cache.get('contradictions', [])
        context['contradictions'] = contradictions
        context['contradictions_json'] = json.dumps(contradictions)

        return context


class RegisterView(View):
    """Simple registration with username + password."""
    template_name = 'registration/register.html'

    def get(self, request):
        if request.user.is_authenticated:
            return redirect('web:home')
        form = UserCreationForm()
        return self._render(request, form)

    def post(self, request):
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('web:home')
        return self._render(request, form)

    def _render(self, request, form):
        from django.template.response import TemplateResponse
        return TemplateResponse(request, self.template_name, {'form': form})


def preferred_source_view(request):
    """Save/load preferred source for authenticated users."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Login required'}, status=401)

    pref, _ = UserPreference.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        source_name = request.POST.get('source_name', '').strip()
        if source_name:
            try:
                source = Source.objects.get(name=source_name)
                pref.preferred_source = source
                pref.save()
                return JsonResponse({'source_name': source.name})
            except Source.DoesNotExist:
                return JsonResponse({'error': 'Source not found'}, status=404)
        else:
            pref.preferred_source = None
            pref.save()
            return JsonResponse({'source_name': None})

    # GET
    return JsonResponse({
        'source_name': pref.preferred_source.name if pref.preferred_source else None,
    })
