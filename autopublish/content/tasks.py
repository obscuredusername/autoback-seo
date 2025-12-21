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
    then calls save_to_wp to publish them to WordPress.
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
        scheduled_count = 0
        
        # Process each scheduled post by calling save_to_wp
        for post in scheduled_posts:
            try:
                logger.info(f"📤 Scheduling post {post.id} ({post.title}) for WordPress publishing")
                
                # Import and call the save_to_wp task
                from keyword_content.tasks import save_to_wp
                
                # Call save_to_wp task asynchronously
                save_to_wp.apply_async(
                    args=[post.id],
                    kwargs={'status': 'publish'}
                )
                
                scheduled_count += 1
                logger.info(f"✅ Successfully scheduled post {post.id} for publishing")
                
            except Exception as e:
                logger.error(f"❌ Error scheduling post {post.id}: {str(e)}", exc_info=True)
                
                # Update the post status to failed
                post.status = 'failed'
                post.last_error = str(e)
                post.save(update_fields=['status', 'last_error'])
                
        logger.info(f"✅ Finished scheduling {scheduled_count} posts for publishing")
        return {"scheduled": scheduled_count, "status": "completed"}
        
    except Exception as e:
        logger.error(f"❌ Error in process_scheduled_posts: {str(e)}", exc_info=True)
        raise
