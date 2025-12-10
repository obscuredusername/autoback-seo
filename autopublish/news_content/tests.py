import os
import json
from datetime import datetime, timedelta
from django.test import TestCase, override_settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.conf import settings
from .models import NewsPost

User = get_user_model()

class NewsPostModelTest(TestCase):
    def setUp(self):
        # Create a test user
        self.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123',
            collection='test.collection'
        )
        
        # Sample news data
        self.news_data = {
            'title': 'Test News Article',
            'content': 'This is a test news article content.',
            'excerpt': 'A test excerpt for the news article.',
            'user_email': 'test@example.com',
            'metadata': {
                'source': 'Test Source',
                'url': 'https://example.com/test-article',
                'target_path': 'test.collection.news'
            },
            'categoryIds': ['tech', 'ai'],
            'tagIds': ['test', 'draft']
        }
    
    def test_create_news_post_with_metadata(self):
        """Test creating a news post with metadata"""
        news = NewsPost.objects.create(**{
            **self.news_data,
            'scheduledAt': timezone.now() + timedelta(hours=1)
        })
        
        self.assertEqual(news.title, self.news_data['title'])
        self.assertEqual(news.metadata['source'], 'Test Source')
        self.assertEqual(news.metadata['url'], 'https://example.com/test-article')
        self.assertEqual(news.status, 'scheduled')
    
    def test_auto_schedule_30_minutes_apart(self):
        """Test automatic scheduling of news posts 30 minutes apart"""
        # First post with explicit time
        first_time = timezone.now() + timedelta(hours=1)
        first_post = NewsPost.objects.create(
            title='First Post',
            content='First content',
            scheduledAt=first_time
        )
        
        # Second post without time should be scheduled 30 minutes after first
        second_post = NewsPost.objects.create(
            title='Second Post',
            content='Second content'
        )
        
        self.assertEqual(second_post.scheduledAt, first_time + timedelta(minutes=30))
    
    def test_target_path_from_user_collection(self):
        """Test that target_path is set from user's collection"""
        news = NewsPost.objects.create(
            title='Test Target Path',
            content='Testing target path assignment',
            user_email='test@example.com'
        )
        
        # Should use the user's collection as target_path
        self.assertEqual(news.target_path, 'test.collection')
    
    def test_target_path_from_metadata(self):
        """Test that target_path can be overridden in metadata"""
        news = NewsPost.objects.create(
            title='Test Target Path Override',
            content='Testing target path override',
            user_email='test@example.com',
            metadata={'target_path': 'custom.collection'}
        )
        
        # Should use the target_path from metadata
        self.assertEqual(news.target_path, 'custom.collection')
    
    def test_default_target_path(self):
        """Test that a default target_path is used when none is provided"""
        news = NewsPost.objects.create(
            title='Test Default Target Path',
            content='Testing default target path',
            user_email='nonexistent@example.com'  # No such user
        )
        
        # Should fall back to default
        self.assertEqual(news.target_path, 'CRM.posts')
