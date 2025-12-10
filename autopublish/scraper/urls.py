from django.urls import path
from django.views.decorators.csrf import csrf_exempt
from . import views

urlpatterns = [
    # General keyword-based search endpoint
    path('keyword/', csrf_exempt(views.KeywordSearchView.as_view()), name='keyword-search'),
    
    # News by category endpoint (supports multiple vendors)
    path('news/', csrf_exempt(views.NewsByCategoryView.as_view()), name='news-by-category-slash'),
    
    # Image search endpoint
    path('images/', csrf_exempt(views.ImageSearchView.as_view()), name='image-search'),
]
