import logging
from celery import shared_task
from django.utils import timezone
from .models import ScheduledPost, PublishedPost

logger = logging.getLogger(__name__)

@shared_task(bind=True, name="process_scheduled_posts")
def process_scheduled_posts(self):
    """
    Celery beat task to process scheduled posts.
    Finds posts with status 'scheduled' and scheduled_at <= current time,
    then processes them and creates published versions.
    """
    logger.info("⏰ Starting scheduled posts processing...")
    
    try:
        # Get current time
        now = timezone.now()
        
        # Find all posts that are scheduled and due for publishing
        scheduled_posts = ScheduledPost.objects.filter(
            status='scheduled',
            scheduled_at__lte=now,
            target_path__isnull=False
        )
        
        logger.info(f"Found {scheduled_posts.count()} posts to process")
        processed_count = 0
        
        # Process each scheduled post
        for post in scheduled_posts:
            try:
                # Create a published version of the post
                published_post = PublishedPost.objects.create(
                    scheduled_post=post,
                    title=post.title,
                    content=post.content,
                    target_path=post.target_path,
                    published_at=timezone.now()
                )
                
                # Update the original post status to published
                post.status = 'published'
                post.published_at = timezone.now()
                post.save()
                
                logger.info(f"✅ Successfully published post {post.id} to {post.target_path}")
                processed_count += 1
                
            except Exception as e:
                logger.error(f"❌ Error processing post {post.id}: {str(e)}", exc_info=True)
                
                # Update the post status to failed
                post.status = 'failed'
                post.save(update_fields=['status'])
                
        logger.info(f"✅ Finished processing {processed_count} scheduled posts")
        return {"processed": processed_count, "status": "completed"}
        
    except Exception as e:
        logger.error(f"❌ Error in process_scheduled_posts: {str(e)}", exc_info=True)
        raise
