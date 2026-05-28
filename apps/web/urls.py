from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from . import views

app_name = 'web'

urlpatterns = [
    # Auth
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('register/', views.RegisterView.as_view(), name='register'),

    # User preferences
    path('preference/source/', views.preferred_source_view, name='preferred-source'),

    # Main pages
    path('', views.HomeView.as_view(), name='home'),
    path('ideas/', views.IdeasView.as_view(), name='ideas'),
    path('search/', views.SearchResultsView.as_view(), name='search'),
    path('topic/<slug:slug>/', views.TopicReportView.as_view(), name='topic-detail'),
    path('article/<int:pk>/', views.ArticleDetailView.as_view(), name='article-detail'),

    # HTMX partials
    path('htmx/search/', views.SearchResultsPartial.as_view(), name='htmx-search'),
    path('htmx/topics/', views.TopicListPartial.as_view(), name='htmx-topics'),
]
