from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from rest_framework.routers import DefaultRouter
from .views import KeywordBlogPostView, NewsSchedulerView

# Create a router for ViewSets
router = DefaultRouter()

urlpatterns = [
    # Keyword-based content generation
    path('keyword/generate/', csrf_exempt(KeywordBlogPostView.as_view()), name='content-keyword-generate'),
    
    # News-based content generation
    path('news/generate/', NewsSchedulerView.as_view(), name='content-news-generate'),
    path('news/generate/<str:task_id>/', NewsSchedulerView.as_view(), name='content-news-task-status'),
]

# Include router URLs
urlpatterns += router.urls
