from django.db import models
from django.utils import timezone

class ScheduledPost(models.Model):
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('published', 'Published'),
        ('failed', 'Failed')
    ]
    
    title = models.CharField(max_length=255)
    content = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    scheduled_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    target_path = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-scheduled_at']
        
    def __str__(self):
        return f"{self.title} ({self.status})"

class PublishedPost(models.Model):
    scheduled_post = models.ForeignKey(ScheduledPost, on_delete=models.CASCADE, related_name='published_versions')
    title = models.CharField(max_length=255)
    content = models.TextField()
    target_path = models.CharField(max_length=255)
    published_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        ordering = ['-published_at']
        
    def __str__(self):
        return f"{self.title} (Published at {self.published_at})"
