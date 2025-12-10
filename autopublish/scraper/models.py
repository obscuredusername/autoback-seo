from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.conf import settings

User = get_user_model()

class ScrapedArticle(models.Model):
    """
    Model to store scraped news articles from various sources.
    """
    SOURCE_CHOICES = [
        ('google', 'Google News'),
        ('yahoo', 'Yahoo News'),
        ('other', 'Other')
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('error', 'Error')
    ]
    
    # Article metadata
    title = models.CharField(max_length=500)
    url = models.URLField(max_length=1000, unique=True)
    source = models.CharField(max_length=100, db_index=True)
    source_type = models.CharField(max_length=10, choices=SOURCE_CHOICES, db_index=True)
    category = models.CharField(max_length=100, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True, db_index=True)
    author = models.CharField(max_length=255, blank=True, null=True)
    
    # Content
    content = models.TextField(blank=True, null=True)
    summary = models.TextField(blank=True, null=True)
    image_url = models.URLField(max_length=1000, blank=True, null=True)
    
    # System fields
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scraped_articles'
    )
    
    # Additional metadata
    language = models.CharField(max_length=10, default='en')
    country = models.CharField(max_length=10, default='us')
    keywords = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-published_at', '-created_at']
        indexes = [
            models.Index(fields=['source_type', 'category']),
            models.Index(fields=['status', 'published_at']),
        ]
    
    def __str__(self):
        return f"{self.title[:100]}... ({self.source_type}:{self.source})"
    
    def save(self, *args, **kwargs):
        # Auto-set created_by if not set and we have a request user
        from crum import get_current_user
        if not self.pk and not self.created_by_id:
            user = get_current_user()
            if user and user.is_authenticated:
                self.created_by = user
        super().save(*args, **kwargs)

