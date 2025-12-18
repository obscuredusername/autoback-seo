from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.text import slugify
from django.conf import settings
import jsonfield
import uuid

class BlogPlan(models.Model):
    """Model to store blog content generation plans"""
    STATUS_CHOICES = [
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('error', 'Error'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    keyword = models.CharField(max_length=255)
    language = models.CharField(max_length=10, default='en')
    country = models.CharField(max_length=10, default='us')
    available_categories = jsonfield.JSONField(default=list)
    tasks = jsonfield.JSONField(default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='processing')
    error = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'keyword_content'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.keyword} ({self.status})"




class BlogPostPayload(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('scheduled', 'Scheduled'),
        ('published', 'Published'),
        ('failed', 'Failed to Publish'),
    ]

    title = models.CharField(max_length=500)
    content = models.TextField(help_text="Original content of the article")
    excerpt = models.TextField(blank=True, null=True, help_text="Short excerpt of the content")
    slug = models.SlugField(max_length=500, unique=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    published_at = models.DateTimeField(blank=True, null=True, help_text="When this post was published")
    scheduled_at = models.DateTimeField(blank=True, null=True, help_text="When to publish this post")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Relationships
    categories = jsonfield.JSONField(default=list, blank=True)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_posts'
    )
    profile = models.ForeignKey(
        'user.Profile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posts'
    )
    
    # SEO fields
    meta_title = models.CharField(max_length=500, blank=True, null=True, help_text="SEO title")
    meta_description = models.TextField(blank=True, null=True, help_text="SEO description")
    meta_keywords = models.TextField(blank=True, null=True, help_text="SEO keywords")
    meta_image = models.URLField(blank=True, null=True, help_text="URL of the featured image")
    focus_keyword = models.CharField(max_length=255, blank=True, null=True)
    
    # Social media
    og_title = models.CharField(max_length=500, blank=True, null=True, help_text="Open Graph title")
    og_description = models.TextField(blank=True, null=True, help_text="Open Graph description")
    og_type = models.CharField(max_length=50, default='article', help_text="Open Graph type")
    twitter_card = models.CharField(max_length=50, default='summary_large_image', help_text="Twitter card type")
    twitter_title = models.CharField(max_length=500, blank=True, null=True, help_text="Twitter card title")
    twitter_description = models.TextField(blank=True, null=True, help_text="Twitter card description")
    
    # Additional metadata
    language = models.CharField(max_length=10, default='en', help_text="Content language code")
    word_count = models.PositiveIntegerField(default=0, help_text="Number of words in the content")
    reading_time = models.PositiveIntegerField(default=0, help_text="Estimated reading time in minutes")
    featured = models.BooleanField(default=False, help_text="Whether this is a featured post")
    canonical_url = models.URLField(blank=True, null=True, help_text="Canonical URL of the post")
    last_error = models.TextField(blank=True, null=True, help_text='Last error message if publishing failed')

    class Meta:
        app_label = 'keyword_content'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'scheduled_at']),
            models.Index(fields=['author']),
            models.Index(fields=['featured']),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)