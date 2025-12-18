import logging
from celery import shared_task
from django.utils import timezone
from keyword_content.models import BlogPostPayload

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
        scheduled_posts = BlogPostPayload.objects.filter(
            status='scheduled',
            scheduled_at__lte=now
        )
        
        logger.info(f"Found {scheduled_posts.count()} posts to process")
        processed_count = 0
        
        # Process each scheduled post
        for post in scheduled_posts:
            try:
                # Update the post status to published
                post.status = 'published'
                post.published_at = timezone.now()
                post.save(update_fields=['status', 'published_at'])
                
                logger.info(f"✅ Successfully published post {post.id} ({post.title})")
                processed_count += 1
                
            except Exception as e:
                logger.error(f"❌ Error processing post {post.id}: {str(e)}", exc_info=True)
                
                # Update the post status to failed
                post.status = 'failed'
                post.last_error = str(e)
                post.save(update_fields=['status', 'last_error'])
                
        logger.info(f"✅ Finished processing {processed_count} scheduled posts")
        return {"processed": processed_count, "status": "completed"}
        
    except Exception as e:
        logger.error(f"❌ Error in process_scheduled_posts: {str(e)}", exc_info=True)
        raise
