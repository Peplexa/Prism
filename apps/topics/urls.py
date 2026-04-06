from django.urls import path
from . import views

app_name = 'topics'

urlpatterns = [
    path('', views.TopicListView.as_view(), name='list'),
    path('trending/', views.TrendingTopicsView.as_view(), name='trending'),
    path('<slug:slug>/', views.TopicDetailView.as_view(), name='detail'),
    path('<slug:slug>/report/', views.TopicReportAPIView.as_view(), name='report'),
    path('<slug:slug>/nuggets/', views.TopicNuggetsAPIView.as_view(), name='nuggets'),
    path('<slug:slug>/omission/', views.TopicOmissionAPIView.as_view(), name='omission'),
]
