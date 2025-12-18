import logging
from datetime import datetime, timedelta, timezone
from django.utils.text import slugify
from bson import ObjectId
from pymongo import MongoClient
from django.conf import settings
from asgiref.sync import sync_to_async
from django.utils import timezone as django_timezone
from django.apps import apps
from django.contrib.auth import get_user_model
from django.utils.text import slugify
from bson import ObjectId
import json


# Set up logging
logger = logging.getLogger(__name__)

# Helper sync functions for database operations
async def get_mongodb_connection():
    """Get MongoDB connection using settings from Django"""
    try:
        logger.info(f"Connecting to MongoDB at: {settings.DATABASES['default']['CLIENT']['host']}")
        logger.info(f"Using database: {settings.DATABASES['default']['NAME']}")
        client = MongoClient(settings.DATABASES['default']['CLIENT']['host'])
        db = client[settings.DATABASES['default']['NAME']]
        # Test the connection
        db.command('ping')
        logger.info("✅ Successfully connected to MongoDB")
        return db
    except Exception as e:
        logger.error(f"❌ Failed to connect to MongoDB: {str(e)}")
        raise

async def get_target_path(request=None, metadata=None):
    """Get the target path with the following priority:
    1. User's collection field if set
    2. target_path from metadata
    3. Derived from user's email domain
    4. Default to 'CRM.posts'
    """
    target_path = 'CRM.posts'  # Default fallback
    
    try:
        if request and hasattr(request, 'user') and request.user.is_authenticated:
            User = get_user_model()
            user = await sync_to_async(User.objects.get)(id=request.user.id)
            
            # 1. First try to get from user's collection field
            if hasattr(user, 'collection') and user.collection:
                target_path = user.collection
                logger.info(f"Using collection from user model: {target_path}")
            
            # 2. If no collection set, try to derive from email
            elif hasattr(user, 'email') and user.email:
                domain = user.email.split('@')[-1].split('.')[0].upper()  # Get domain and convert to uppercase
                target_path = f"{domain}.posts"
                logger.info(f"Derived target_path from email: {target_path}")
                
                # Update user's collection field for future use
                user.collection = target_path
                await sync_to_async(user.save)()
        
        # 3. Fall back to metadata if user not available
        elif metadata and 'target_path' in metadata:
            target_path = metadata['target_path']
            logger.info(f"Using target_path from metadata: {target_path}")
            
    except Exception as e:
        logger.warning(f"Error getting target path: {str(e)}")
        logger.warning(f"Falling back to default target_path: {target_path}")
    
    # Ensure consistent format (preserve case for DB name, lowercase collection)
    if '.' in target_path:
        db_name, coll_name = target_path.split('.')
        target_path = f"{db_name}.{coll_name.lower()}"
    
    logger.info(f"Final target_path: {target_path}")
    target_path = target_path.strip().lower()
    if not target_path.endswith('.posts'):
        target_path = f"{target_path}.posts" if target_path else 'default.posts'
    
    logger.info(f"Using target_path: {target_path}")
    return target_path

async def get_system_user_id():
    """
    Get a valid system user ID to use as author for automated content.
    Returns:
        ObjectId: A valid user ID from the database
    """
    try:
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        # Try to get the first active staff user
        user = await sync_to_async(User.objects.filter(is_active=True, is_staff=True).first)()
        
        # If no staff user, get any active user
        if not user:
            user = await sync_to_async(User.objects.filter(is_active=True).first)()
        
        if user:
            return user
            
    except Exception as e:
        logger.error(f"Error getting system user: {str(e)}")
        
    # Return None if no user is found
    return None

    async def save_news_to_content(article_data, request=None):
        """
        Save a news article using BlogPostPayload model (same as keywords)
        
        Args:
            article_data (dict): Dictionary containing article data with the following structure:
                - original_article: Original article data
                - rephrased_article: Rephrased content
                - metadata: Additional metadata
            request: Django request object (optional, for getting user info)
        
        Returns:
            str: The ID of the saved article, or None if failed
        """
        logger.info("=== Starting save_news_to_content ===")
        logger.info(f"Input article_data: {article_data}")
        
        try:
            # Extract data with defaults
            original = article_data.get('original_article', {})
            rephrased = article_data.get('rephrased_article', {})
            metadata = article_data.get('metadata', {})
            
            logger.info(f"Original article keys: {original.keys()}")
            logger.info(f"Rephrased article keys: {rephrased.keys()}")
            
            # Prepare content for saving
            title = original.get('title', 'Untitled Article')
            logger.info(f"Processing article: {title}")
            
            # Get content from rephrased or original
            content = rephrased.get('content', '')
            if isinstance(content, dict):
                content = content.get('content', '') or original.get('content', '')
            
            logger.info(f"Content length: {len(content)} characters")
            
            # Get target_path from user's email or metadata
            target_path = await get_target_path(request, metadata)
            logger.info(f"Using target_path: {target_path}")
            
            # Generate a slug from the title
            def generate_slug(title):
                if not title or not isinstance(title, str):
                    title = "untitled-article"
                slug = slugify(title)
                # Add timestamp to make it unique
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                return f"{slug}-{timestamp}" if slug else f"article-{timestamp}"
                
            # Generate slug for the post - ensure it's never empty
            slug = generate_slug(title)
            if not slug:
                slug = f"article-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            logger.info(f"Generated slug: {slug}")
            
            # Using the specified category ID
            category_id = "6872543bb13173a4a942d3c4"
            logger.info(f"Using category ID: {category_id}")
            
            # Ensure categoryIds is a list with the specified ID
            category_ids = [category_id]
            
            # Get scheduled time from metadata
            scheduled_at = None
            
            # First try to get from metadata.scheduledAt
            if 'scheduledAt' in metadata and metadata['scheduledAt']:
                scheduled_at = metadata['scheduledAt']
                logger.info(f"Found scheduledAt in metadata: {scheduled_at}")
            # Then try to get from article_data directly (for backward compatibility)
            elif 'scheduled_time' in article_data and article_data['scheduled_time']:
                scheduled_at = article_data['scheduled_time']
                logger.info(f"Found scheduled_time in article_data: {scheduled_at}")
            
            # Parse the scheduled time if it's a string
            if scheduled_at and isinstance(scheduled_at, str):
                try:
                    from dateutil import parser
                    scheduled_at = parser.parse(scheduled_at)
                    logger.info(f"Parsed scheduled time: {scheduled_at}")
                except (ValueError, TypeError) as e:
                    logger.error(f"Error parsing scheduled time {scheduled_at}: {e}")
                    scheduled_at = None
            
            # Ensure timezone-aware datetime
            if scheduled_at and scheduled_at.tzinfo is None:
                scheduled_at = scheduled_at.replace(tzinfo=datetime.timezone.utc)
                logger.info(f"Ensured timezone awareness: {scheduled_at}")
            
            # If no valid scheduled time is provided, use current time + 1 hour as fallback
            if not scheduled_at:
                scheduled_at = django_timezone.now() + datetime.timedelta(hours=1)
                logger.info(f"Using fallback scheduled time: {scheduled_at}")
            
            # Ensure scheduled time is at least 5 minutes in the future
            min_scheduled_time = django_timezone.now() + datetime.timedelta(minutes=5)
            if scheduled_at < min_scheduled_time:
                scheduled_at = min_scheduled_time
                logger.info(f"Adjusted scheduled time to minimum: {scheduled_at}")
                
            logger.info(f"Final scheduled time: {scheduled_at}")
            
            # Always set status to 'scheduled' as per requirements
            status = 'scheduled'
            logger.info(f"Setting status to: {status}")
            
            # Get MongoDB connection - always use 'content' database
            db = await get_mongodb_connection()
            
            # Get author - prioritize authenticated user, then system user
            try:
                if request and hasattr(request, 'user') and request.user.is_authenticated:
                    author = request.user
                else:
                    # Get a valid system user
                    author = await get_system_user_id()
                    if not author:
                        logger.warning("No author found, using None")
            except Exception as e:
                logger.error(f"Error getting author: {str(e)}")
                author = None
                
            # Create the news post using BlogPostPayload model
            from keyword_content.models import BlogPostPayload
            
            # Handle image URLs
            image_urls = original.get('image_urls', [])
            meta_image = original.get('urlToImage', '')
            
            # If we have image URLs but no meta image, use the first one
            if image_urls and not meta_image:
                meta_image = image_urls[0]
            
            # Create the blog post payload with all required fields
            news_post = BlogPostPayload(
                title=title[:500],
                content=content,
                excerpt=original.get('description', '')[:500] if original.get('description') else '',
                slug=slug,  # Use the slug we generated earlier
                status=status,
                categories=category_ids if isinstance(category_ids, list) else [str(category_ids).strip('"[] ')] if category_ids else [],
                author=author,
                scheduled_at=scheduled_at,
                meta_title=title[:500],
                meta_description=original.get('description', '')[:500] if original.get('description') else '',
                meta_image=meta_image,  # Set the meta image
                word_count=len(content.split()),
                reading_time=max(1, len(content.split()) // 200)
            )
            
            try:
                # Save the news post
                await sync_to_async(news_post.save)()
                logger.info(f"✅ Successfully saved news post with ID: {news_post.id} and slug: {news_post.slug}")
                logger.info(f"✅ Categories: {news_post.categories}")
                
                return str(news_post.id)
                
            except Exception as save_error:
                logger.error(f"❌ Error saving news post: {str(save_error)}")
                logger.error(f"Error type: {type(save_error).__name__}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Unexpected error in save_news_to_content: {str(e)}")
            logger.error(f"Error type: {type(e).__name__}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return None
