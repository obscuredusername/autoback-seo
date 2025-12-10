from django.urls import path
from .views import (
    UserCreateView, 
    UserLoginView, 
    UserLogoutView,
    SessionCheckView,
    UserList,
    CollectionCreateView
)

urlpatterns = [
    # Authentication endpoints
    path('create/', UserCreateView.as_view(), name='user-create'),
    path('login/', UserLoginView.as_view(), name='user-login'),
    path('logout/', UserLogoutView.as_view(), name='user-logout'),
    path('session/', SessionCheckView.as_view(), name='session-check'),
    
    # User management endpoints
    path('users/', UserList.as_view(), name='user-list'),  # GET all users
    path('users/<int:pk>/update/', UserList.as_view(), name='user-update'),
    path('users/<int:pk>/delete/', UserList.as_view(), name='user-delete'),
    
    # Collection management endpoints
    path('collections/create/', CollectionCreateView.as_view(), name='collection-create'),
]
