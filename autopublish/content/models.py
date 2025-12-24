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
        app_label = 'content'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.keyword} ({self.status})"


class BlogPostPayload(models.Model):
    """
    Centralized model for storing blog posts with comprehensive metadata.
    This model handles posts from both keyword-based and news-based content generation.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Review'),
        ('scheduled', 'Scheduled'),
        ('publishing', 'Publishing'),
        ('published', 'Published'),
        ('failed', 'Failed to Publish'),
    ]

    # Core fields
    title = models.CharField(max_length=500, help_text="Post title")
    content = models.TextField(help_text="HTML content of the article")
    excerpt = models.TextField(blank=True, null=True, help_text="Short excerpt of the content")
    slug = models.SlugField(max_length=500, unique=True, blank=True, help_text="URL-friendly slug")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Timestamps
    published_at = models.DateTimeField(blank=True, null=True, help_text="When this post was published")
    scheduled_at = models.DateTimeField(blank=True, null=True, help_text="When to publish this post")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Relationships
    categories = jsonfield.JSONField(default=list, blank=True, help_text="Array of category IDs")
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='authored_posts',
        help_text="Post author"
    )
    profile = models.ForeignKey(
        'user.Profile',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='posts',
        help_text="User profile associated with this post"
    )
    
    # SEO fields
    meta_title = models.CharField(max_length=500, blank=True, null=True, help_text="SEO title")
    meta_description = models.TextField(blank=True, null=True, help_text="SEO description")
    meta_keywords = models.TextField(blank=True, null=True, help_text="SEO keywords")
    meta_image = models.URLField(blank=True, null=True, help_text="URL of the featured image")
    focus_keyword = models.CharField(max_length=255, blank=True, null=True, help_text="Primary SEO keyword")
    
    # Social media fields
    og_title = models.CharField(max_length=500, blank=True, null=True, help_text="Open Graph title")
    og_description = models.TextField(blank=True, null=True, help_text="Open Graph description")
    og_type = models.CharField(max_length=50, default='article', help_text="Open Graph type")
    twitter_card = models.CharField(max_length=50, default='summary_large_image', help_text="Twitter card type")
    twitter_title = models.CharField(max_length=500, blank=True, null=True, help_text="Twitter card title")
    twitter_description = models.TextField(blank=True, null=True, help_text="Twitter card description")
    og_image = models.URLField(blank=True, null=True, help_text="Open Graph image URL")
    twitter_image = models.URLField(blank=True, null=True, help_text="Twitter card image URL")
    
    # Additional metadata
    language = models.CharField(max_length=10, default='en', help_text="Content language code (e.g., 'en', 'fr')")
    word_count = models.PositiveIntegerField(default=0, help_text="Number of words in the content")
    reading_time = models.PositiveIntegerField(default=0, help_text="Estimated reading time in minutes")
    featured = models.BooleanField(default=False, help_text="Whether this is a featured post")
    canonical_url = models.URLField(blank=True, null=True, help_text="Canonical URL / WordPress site URL")
    last_error = models.TextField(blank=True, null=True, help_text='Last error message if publishing failed')
    
    # Source tracking (for news posts)
    source_url = models.URLField(blank=True, null=True, help_text="Original source URL (for news posts)")
    source_name = models.CharField(max_length=255, blank=True, null=True, help_text="Original source name")

    class Meta:
        app_label = 'content'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'scheduled_at'], name='content_status_scheduled_idx'),
            models.Index(fields=['author'], name='content_author_idx'),
            models.Index(fields=['featured'], name='content_featured_idx'),
            models.Index(fields=['created_at'], name='content_created_idx'),
        ]
        verbose_name = 'Blog Post'
        verbose_name_plural = 'Blog Posts'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        """Auto-generate slug if not provided"""
        if not self.slug:
            base_slug = slugify(self.title)
            slug = base_slug
            counter = 1
            # Ensure unique slug
            while BlogPostPayload.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        
        # Calculate word count if content exists
        if self.content and self.word_count == 0:
            # Strip HTML tags and count words
            import re
            text = re.sub(r'<[^>]+>', '', self.content)
            self.word_count = len(text.split())
            # Estimate reading time (average 200 words per minute)
            self.reading_time = max(1, self.word_count // 200)
        
        super().save(*args, **kwargs)

    @property
    def is_scheduled(self):
        """Check if post is scheduled for future publishing"""
        return self.status == 'scheduled' and self.scheduled_at and self.scheduled_at > timezone.now()

    @property
    def is_ready_to_publish(self):
        """Check if post is ready to be published"""
        return self.status == 'scheduled' and self.scheduled_at and self.scheduled_at <= timezone.now()

    @property
    def is_published(self):
        """Check if post has been published"""
        return self.status == 'published' and self.published_at is not None
