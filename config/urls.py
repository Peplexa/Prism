from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView


def health_check(request):
    return JsonResponse({'status': 'ok'})


urlpatterns = [
    path('health/', health_check, name='health-check'),
    path('admin/', admin.site.urls),

    # API documentation
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),

    # API endpoints
    path('api/v1/', include([
        path('articles/', include('apps.articles.urls', namespace='api-articles')),
        path('topics/', include('apps.topics.urls', namespace='api-topics')),
    ])),

    # Web frontend
    path('', include('apps.web.urls', namespace='web')),
]
