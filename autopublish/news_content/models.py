from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from keyword_content.fields import ListField 

User = get_user_model()

class NewsCategory(models.Model):
    """Model to categorize news posts"""
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return self.name

class NewsPost(models.Model):
    """
    Model to store news articles with the same structure as BlogPostPayload
    """
    _id = models.AutoField(primary_key=True)
    
    # Status choices - matching BlogPostPayload
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('published', 'Published'),
        ('pending', 'Pending Review'),
        ('failed', 'Failed to Publish'),
        ('archived', 'Archived'),
    ]
    
    class Meta:
        app_label = 'news_content'
        db_table = 'content'  # Using 'content' as the collection name
        managed = False  # Tell Django not to manage the table creation
        ordering = ['-scheduledAt', '-createdAt']
        verbose_name = 'News Post'
        verbose_name_plural = 'News Posts'
        indexes = [
            models.Index(fields=['status', 'scheduledAt']),
            models.Index(fields=['status']),
            models.Index(fields=['scheduledAt']),
        ]

    # Core content fields - matching BlogPostPayload
    title = models.CharField(max_length=500)
    content = models.TextField(help_text="Content of the article")
    excerpt = models.TextField(blank=True, null=True, help_text="Short excerpt of the content")
    slug = models.SlugField(max_length=500, unique=True, blank=True)
    
    # Status and timestamps - matching BlogPostPayload
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='scheduled')
    publishedAt = models.DateTimeField(blank=True, null=True, help_text="When this post was published")
    scheduledAt = models.DateTimeField(blank=True, null=True, help_text="When to publish this post")
    createdAt = models.DateTimeField(auto_now_add=True)
    updatedAt = models.DateTimeField(auto_now=True)
    
    # Categories and taxonomy - matching BlogPostPayload
    categoryIds = ListField(
        object_id=True,
        help_text='List of category ObjectId strings',
        default=list
    )
    categories = models.ManyToManyField(
        NewsCategory, 
        related_name='news_posts',
        blank=True,
        db_table='news_content_newspost_categories'  # Custom table name to avoid conflict
    )
    tagIds = ListField(
        object_id=True,
        help_text='List of tag ObjectId strings',
        default=list
    )
    tags = ListField(
        help_text='List of tags',
        default=list
    )
    
    # Author and ownership - matching BlogPostPayload
    authorId = models.CharField(max_length=255, blank=True, null=True)
    user_email = models.EmailField(blank=True, null=True)
    
    # Metadata - matching BlogPostPayload
    metaTitle = models.CharField(max_length=500, blank=True, null=True, help_text="SEO title")
    metaDescription = models.TextField(blank=True, null=True, help_text="SEO description")
    metaKeywords = models.TextField(blank=True, null=True, help_text="SEO keywords")
    metaImage = models.URLField(blank=True, null=True, help_text="URL of the featured image")
    
    # Social sharing - matching BlogPostPayload
    ogTitle = models.CharField(max_length=500, blank=True, null=True, help_text="Open Graph title")
    ogDescription = models.TextField(blank=True, null=True, help_text="Open Graph description")
    ogType = models.CharField(max_length=50, default='article', help_text="Open Graph type")
    twitterCard = models.CharField(max_length=50, default='summary_large_image', help_text="Twitter card type")
    twitterDescription = models.TextField(blank=True, null=True, help_text="Twitter card description")
    
    # Content information - matching BlogPostPayload
    focusKeyword = models.CharField(max_length=255, blank=True, null=True, help_text="Primary keyword for the post")
    language = models.CharField(max_length=50, default='en', help_text="Content language code")
    word_count = models.IntegerField(default=0, help_text="Number of words in the content")
    readingTime = models.IntegerField(default=0, help_text="Estimated reading time in minutes")
    
    # Target publishing - matching BlogPostPayload
    target_path = models.CharField(
        max_length=500, 
        blank=True, 
        null=True,
        help_text='Target database and collection in format: db.collection (e.g., CRM.posts)'
    )
    
    # Additional fields - matching BlogPostPayload
    canonicalUrl = models.URLField(blank=True, null=True, help_text="Canonical URL of the post")
    featured = models.BooleanField(default=False, help_text="Whether this is a featured post")
    content_type = models.CharField(max_length=100, blank=True, null=True)
    image_urls = ListField(
    help_text='List of image URLs',
    default=list
)
    metadata = models.JSONField(default=dict, blank=True, help_text="Additional metadata in JSON format")
    
    # Error tracking - matching BlogPostPayload
    lastError = models.TextField(blank=True, null=True, help_text='Last error message if publishing failed')
    
    def __str__(self):
        return f"{self.title} ({self.status})"
    
    def save(self, *args, **kwargs):
        from django.utils import timezone
        from django.utils.text import slugify
        from bson import ObjectId
        import re
        import json
        
        # Ensure required fields have defaults
        if not hasattr(self, 'status') or not self.status:
            self.status = 'scheduled'
            
        # Validate status
        valid_statuses = [choice[0] for choice in self.STATUS_CHOICES]
        if self.status not in valid_statuses:
            self.status = 'scheduled'  # Default to scheduled if invalid status
            
        # Set timestamps if not provided
        now = timezone.now()
        if not self.pk and not self.createdAt:
            self.createdAt = now
        self.updatedAt = now
        
        # Auto-set status based on scheduledAt
        if self.scheduledAt and self.status == 'pending':
            self.status = 'scheduled'
            
        # Generate slug from title if not provided
        if not self.slug and self.title:
            # Create a basic slug
            slug = slugify(self.title.lower())
            
            # Remove special characters and ensure it's URL-safe
            slug = re.sub(r'[^\w\-]', '', slug)
            
            # Ensure the slug is not empty
            if not slug:
                slug = f"post-{self._id or 'new'}"
                
            # Make sure the slug is unique
            original_slug = slug
            counter = 1
            while NewsPost.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{original_slug}-{counter}"
                counter += 1
                
            self.slug = slug
        
        # Handle scheduling logic
        if not self.scheduledAt and not self.pk:
            try:
                latest_post = NewsPost.objects.order_by('-scheduledAt').first()
                if latest_post and latest_post.scheduledAt:
                    self.scheduledAt = latest_post.scheduledAt + timezone.timedelta(minutes=30)
                else:
                    self.scheduledAt = now
                
                if self.scheduledAt > now:
                    self.status = 'scheduled'
            except Exception as e:
                print(f"Error getting latest post for scheduling: {e}")
                self.scheduledAt = now
        
        # Handle target_path
        if not self.target_path:
            # Check metadata first
            if hasattr(self, 'metadata') and isinstance(self.metadata, dict) and 'target_path' in self.metadata:
                self.target_path = self.metadata['target_path']
            # Then check user's collection
            elif hasattr(self, 'user_email') and self.user_email:
                try:
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    user = User.objects.filter(email=self.user_email).first()
                    if user and hasattr(user, 'collection') and user.collection:
                        self.target_path = user.collection
                except Exception as e:
                    print(f"Error getting user collection: {e}")
            
            # Default fallback
            if not self.target_path:
                self.target_path = 'CRM.posts'
        
        # Ensure JSON fields are properly initialized and in correct format
        if not hasattr(self, 'categoryIds') or self.categoryIds is None:
            self.categoryIds = ["68598639e46eb0ed3674d3f6"]  # Default category ID
        elif isinstance(self.categoryIds, str):
            # If categoryIds is a string, try to parse it as JSON
            try:
                parsed = json.loads(self.categoryIds)
                self.categoryIds = parsed if isinstance(parsed, list) else ["68598639e46eb0ed3674d3f6"]
            except (json.JSONDecodeError, TypeError):
                self.categoryIds = ["68598639e46eb0ed3674d3f6"]
        elif not isinstance(self.categoryIds, list):
            # If it's not a list, convert it to a list with the default category
            self.categoryIds = ["68598639e46eb0ed3674d3f6"]
            
        # Ensure the default category ID is included if the list is empty
        if not self.categoryIds:
            self.categoryIds = ["68598639e46eb0ed3674d3f6"]
            
        if not hasattr(self, 'tagIds') or self.tagIds is None:
            self.tagIds = []
        if not hasattr(self, 'metadata') or self.metadata is None:
            self.metadata = {}
        if not hasattr(self, 'image_urls') or self.image_urls is None:
            self.image_urls = []
            
        # Ensure authorId is a string if it's an ObjectId
        if hasattr(self, 'authorId') and isinstance(self.authorId, ObjectId):
            self.authorId = str(self.authorId)
        
        # Call the parent save method
        try:
            super().save(*args, **kwargs)
            print(f"✅ Saved NewsPost with ID: {self._id}, categoryIds: {self.categoryIds}")
        except Exception as e:
            print(f"❌ Error saving NewsPost: {e}")
            print(f"Category IDs type: {type(self.categoryIds)}, value: {self.categoryIds}")
            raise


class NewsSource(models.Model):
    """
    Model to track different news sources
    """
    name = models.CharField(max_length=200)
    domain = models.URLField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    last_scraped = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        app_label = 'news_content'
        ordering = ['name']
    
    def __str__(self):
        return self.name
