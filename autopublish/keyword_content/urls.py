from django.urls import path
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from .views import BlogPost

urlpatterns = [
    path('generate/', csrf_exempt(BlogPost.as_view()), name='blog-post'),
]