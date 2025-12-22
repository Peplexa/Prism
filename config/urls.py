from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),

    # API endpoints
    path('api/v1/', include([
        path('articles/', include('apps.articles.urls', namespace='api-articles')),
        path('topics/', include('apps.topics.urls', namespace='api-topics')),
    ])),

    # Web frontend
    path('', include('apps.web.urls', namespace='web')),
]
