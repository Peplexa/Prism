from django.urls import path
from . import views

app_name = 'topics'

urlpatterns = [
    path('', views.TopicListView.as_view(), name='list'),
    path('trending/', views.TrendingTopicsView.as_view(), name='trending'),
    path('<slug:slug>/', views.TopicDetailView.as_view(), name='detail'),
]
