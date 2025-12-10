from django.urls import path
from . import views

urlpatterns = [
    path('rephrase-news/', views.rephrase_news_content, name='rephrase-news'),
    path('generate-blog/', views.generate_blog_from_keyword, name='generate-blog'),
    path('generate-image/', views.generate_image, name='generate-image'),
    path('download-image/', views.download_image, name='download-image'),
]
