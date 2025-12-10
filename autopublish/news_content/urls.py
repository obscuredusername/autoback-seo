from django.urls import path
from rest_framework.routers import DefaultRouter
from . import views

# Create a router for ViewSets
router = DefaultRouter()

# Register your viewsets with the router
# router.register(r'newsposts', views.NewsPostViewSet)

urlpatterns = [
    # Schedule news fetching and processing
    path('generate/', views.NewsSchedulerView.as_view(), name='news-schedule'),
    path('generate/<str:task_id>/', views.NewsSchedulerView.as_view(), name='news-task-status'),
    
    # News post endpoints
]

# Include router URLs
urlpatterns += router.urls
