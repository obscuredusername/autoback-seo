import base64
import logging
import os
import traceback
from datetime import datetime, timedelta
from django.utils import timezone
from celery import shared_task, signature, group, chain, chord
from django.conf import settings
from .models import BlogPostPayload, BlogPlan
import os
import json
import uuid
# Set up logging
logger = logging.getLogger(__name__)

@shared_task(bind=True, name="autopublish.keyword_content.tasks.process_keyword_task")
def process_keyword_task(self, request_body):
    """
    Celery task to process keywords asynchronously.
    This is a thin wrapper around process_keyword_task_impl to maintain compatibility.
    
    Expected request_body format:
    {
        'keywords': [
            {'text': 'keyword1', 'scheduled_time': '2023-01-01T00:00:00Z'},
            {'text': 'keyword2', 'scheduled_time': '2023-01-01T01:00:00Z'}
        ],
        'language': 'en',
        'country': 'us',
        'user_email': 'user@example.com',
        'collection': 'posts',
        'cookies': {...}
    }
    """
    try:
        # Parse the request body if it's a string
        if isinstance(request_body, str):
            request_body = json.loads(request_body)
 

        scraper_data = {
            "keywords": request_body.get("keywords", []),
            "language": request_body.get("language", "en"),
            "country": request_body.get("country", "us"),
            "available_categories": request_body.get("available_categories", []),
            "target_path": request_body.get("target_path", "CRM.posts"),
        }


        keyword = request_body['keywords'][0]['text']
        language = request_body.get('language', 'en')
        country = request_body.get('country', 'us')
        
        # Create the task chain with parallel execution of blog plan and scraping
        task_chain = (
            # Step 1: Fetch keyword prerequisites
            signature(
                'autopublish.keyword_content.tasks.fetch_keyword_content_prereqs',
                kwargs={
                    'keyword': keyword,
                    'language': language,
                    'country': country,
                    'available_categories': request_body.get('available_categories', []),
                }
            ) | 
            # Step 2: Run blog plan generation, scraping, and image processing in parallel
            # Then process the results and chain to content generation
            chord(
                # Parallel tasks in the header
                [
                    # Blog plan generation
                    signature(
                        'autopublish.content_generator.tasks.get_blog_plan',
                        kwargs={
                            'keyword': keyword,
                            'language': language,
                            'country': country
                        },
                        immutable=True
                    ),
                    # Scraping task
                    signature(
                        'autopublish.scraper.tasks.process_scraping_task',
                        kwargs={
                            'keyword': keyword,
                            'language': language,
                            'country': country,
                            'max_results': 5
                        },
                        immutable=True
                    ),
                    # Image processing task
                    signature(
                        'autopublish.scraper.tasks.process_and_save_images',
                        kwargs={
                            'query': keyword,
                            'max_results': 5,
                            'language': language,
                            'country': country
                        },
                        immutable=True
                    )
                ],
                # Callback that processes the parallel results
                signature(
                    'autopublish.keyword_content.tasks.process_blog_plan_and_scraped_data',
                    kwargs={
                        'language': language,
                        'country': country,
                        'target_path': request_body.get('target_path', 'CRM.posts'),
                        'user_email': request_body.get('user_email')
                    }
                ) | 
                # Step 5: Generate content with the combined data
                # The result from process_blog_plan_and_scraped_data will be passed as the first argument
                signature(
                    'autopublish.content_generator.tasks.generate_keyword_content'
                ) |
                # Step 6: Prepare payload (inject images, format data)
                signature(
                    'autopublish.content_generator.tasks.prepare_payload',
                    kwargs={}
                ) |
                # Step 7: Save blog post
                signature(
                    'autopublish.keyword_content.tasks.save_blog_post',
                    kwargs={
                        'user_email': request_body.get('user_email'),
                        'status': 'publish'
                    }
                )
            )
        )
        
        # Start the chain and return the result
        return task_chain.apply_async()
        
    except Exception as e:
        logger.error(f"Unexpected error in process_keyword_task: {str(e)}", exc_info=True)
        raise  # Re-raise the exception to mark the task as failed
        raise

@shared_task(bind=True, name="autopublish.keyword_content.tasks.fetch_keyword_content_prereqs")
def fetch_keyword_content_prereqs(self, keyword: str, language: str = "en", country: str = "us", available_categories: list = None):
    """
    Prepare keyword content by generating a blog plan and scraping related content.
    
    Args:
        keyword: The main keyword to generate content for
        language: Language code (default: 'en')
        country: Country code (default: 'us')
        available_categories: List of available category IDs
        
    Returns:
        dict: Blog plan data for the next task in the chain
    """
    try:
        logger.info(f"Starting fetch_keyword_content_prereqs for keyword: {keyword}")
        
        # Create a new blog plan in PostgreSQL
        blog_plan = BlogPlan.objects.create(
            keyword=keyword,
            language=language,
            country=country,
            available_categories=available_categories or [],
            status='processing',
            tasks={}
        )
        
        logger.info(f"Created blog plan with ID: {blog_plan.id}")
        
        # Return a dictionary with the required fields for the next task
        # The entire dictionary will be passed as kwargs to the next task
        return {
            'keyword': keyword,
            'language': language,
            'country': country,
            'available_categories': available_categories or [],
            'plan_id': str(blog_plan.id)  # Include plan_id for reference
        }
        
    except Exception as e:
        error_msg = f"Error in fetch_keyword_content_prereqs: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        
        # Update the blog plan with error status if we have a blog_plan
        if 'blog_plan' in locals():
            try:
                blog_plan.status = 'error'
                blog_plan.error = str(e)
                blog_plan.save(update_fields=['status', 'error', 'updated_at'])
            except Exception as update_error:
                logger.error(f"Failed to update blog plan with error: {str(update_error)}")
        
        raise self.retry(exc=e, countdown=60)  # Retry after 60 seconds

@shared_task(bind=True, name="autopublish.keyword_content.tasks.publish_scheduled_posts")
def publish_scheduled_posts(self):
    """
    Celery Beat task to check for and publish scheduled posts.
    
    This task:
    1. Finds posts with status 'pending' or 'scheduled' where scheduledAt is in the past
    2. Validates that scheduledAt is set and in the past
    3. Publishes them to their target location if target_path is specified
    4. Updates their status to 'published' and sets publishedAt timestamp
    5. Handles errors and updates status to 'failed' if needed
    
    Returns:
        dict: Summary of the publishing operation
    """
    published_count = 0
    error_msg = None
    
    try:
        logger.info("Starting publish_scheduled_posts task")
        now = timezone.now()
        
        # Initialize MongoDB client
        mongo_uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
        mongo_db = os.getenv('MONGODB_NAME', 'autopublish')
        
        logger.info(f"Connecting to MongoDB: {mongo_uri}, DB: {mongo_db}")
        client = MongoClient(mongo_uri)
        db = client[mongo_db]
        
        # Find posts that are scheduled and due for publishing
        posts_collection = db['blog_posts']
        
        # Find posts that are scheduled and due for publishing
        query = {
            'status': {'$in': ['pending', 'scheduled']},
            'scheduledAt': {'$lte': now}
        }
        
        posts_to_publish = list(posts_collection.find(query))
        logger.info(f"Found {len(posts_to_publish)} posts to publish")
        
        for post in posts_to_publish:
            try:
                post_id = post.get('_id')
                logger.info(f"Processing post: {post_id}")
                
                # Get target collection from post or use default
                target_path = post.get('target_path', 'CRM.posts')
                if '.' in target_path:
                    target_db_name, target_collection = target_path.split('.', 1)
                else:
                    target_db_name = 'CRM'
                    target_collection = target_path
                
                # Update post status to 'publishing'
                update_result = posts_collection.update_one(
                    {'_id': post_id},
                    {
                        '$set': {
                            'status': 'publishing',
                            'updatedAt': timezone.now().isoformat()
                        }
                    }
                )
                
                # Get the target collection and insert the post
                target_db = client[target_db_name]
                result = target_db[target_collection].insert_one(post)
                
                # Update the post to mark it as published
                update_result = posts_collection.update_one(
                    {'_id': post_id},
                    {
                        '$set': {
                            'status': 'published',
                            'publishedAt': datetime.utcnow(),
                            'updatedAt': datetime.utcnow(),
                            'target_collection': f"{target_db_name}.{target_collection}"
                        }
                    }
                )
                
                logger.info(f"Successfully published post {post_id} to {target_db_name}.{target_collection}")
                published_count += 1
                
            except Exception as e:
                error_msg = f"Error publishing post {post_id}: {str(e)}"
                logger.error(error_msg)
                logger.error(traceback.format_exc())
                
                # Update the post status to failed
                posts_collection.update_one(
                    {'_id': post_id},
                    {
                        '$set': {
                            'status': 'failed',
                            'error_message': str(e),
                            'updatedAt': timezone.now().isoformat()
                        }
                    }
                )
    
    except Exception as e:
        error_msg = f"Error in publish_scheduled_posts: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise  # Re-raise to mark the task as failed in Celery
    
    finally:
        if 'client' in locals():
            try:
                client.close()
            except Exception as e:
                logger.error(f"Error closing MongoDB connection: {str(e)}")
    
    return {
        'status': 'completed',
        'published_posts': published_count,
        'timestamp': datetime.utcnow().isoformat(),
        'message': f'Successfully published {published_count} posts'
    }
    
@shared_task(bind=True, name='autopublish.keyword_content.tasks.process_blog_plan_and_scraped_data')
def process_blog_plan_and_scraped_data(self, results, **kwargs):
    """
    Process the results from blog plan generation, keyword scraping, and image processing.
    
    Args:
        results: List containing the results from the parallel tasks:
            - results[0]: Output from get_blog_plan
            - results[1]: Output from keyword_scraping
            - results[2]: Output from process_and_save_images (optional)
        **kwargs: Additional keyword arguments (language, country, etc.)
        
    Returns:
        dict: Combined data ready for content generation
    """
    try:
        logger.info(f"Processing blog plan and scraped data")
        
        if not results or len(results) < 2:
            raise ValueError(f"Expected at least 2 results (blog_plan and scraped_data), got {len(results) if results else 0}")
        
        # Extract results from the parallel tasks
        blog_plan_result = results[0]
        scraped_data_result = results[1]
        images_result = results[2] if len(results) > 2 else {}
        
        # Handle case where blog_plan_result might be a dict with 'result' key
        if isinstance(blog_plan_result, dict) and 'result' in blog_plan_result:
            blog_plan = blog_plan_result.get('result', {})
        else:
            blog_plan = blog_plan_result
            
        # Handle case where scraped_data_result might be a dict with 'result' key
        if isinstance(scraped_data_result, dict) and 'result' in scraped_data_result:
            scraped_data = scraped_data_result.get('result', {})
        else:
            scraped_data = scraped_data_result
            
        # Handle case where images_result might be a dict with 'result' key
        if isinstance(images_result, dict) and 'result' in images_result:
            images_data = images_result.get('result', {})
        else:
            images_data = images_result
        
        if not isinstance(blog_plan, dict):
            raise ValueError(f"Expected blog_plan to be a dict, got {type(blog_plan)}")
            
        if not isinstance(scraped_data, dict):
            raise ValueError(f"Expected scraped_data to be a dict, got {type(scraped_data)}")
        
        # Ensure we have the basic structure
        if 'data' not in blog_plan:
            blog_plan = {'data': blog_plan}
        
        # Add scraped data to blog plan
        blog_plan['scraped_data'] = scraped_data.get('results', [])
        
        # Add processed images to blog plan
        if isinstance(images_data, dict):
            blog_plan['processed_images'] = images_data.get('processed_images', [])
            blog_plan['image_results'] = images_data
            
            # Log image processing results
            if images_data.get('success') and images_data.get('processed_images'):
                logger.info(f"Successfully processed {len(images_data['processed_images'])} images")
        
        # Add any additional kwargs to the blog plan
        blog_plan.update(kwargs)
        
        # Promote important fields from blog_plan['data'] to top level for easier access
        if 'data' in blog_plan and isinstance(blog_plan['data'], dict):
            blog_plan_data = blog_plan['data']
            
            # Promote title
            if 'title' not in blog_plan and 'title' in blog_plan_data:
                blog_plan['title'] = blog_plan_data['title']
            
            # Promote category
            if 'category' not in blog_plan and 'category' in blog_plan_data:
                blog_plan['category'] = blog_plan_data['category']
            
            # Promote categories
            if 'categories' not in blog_plan and 'categories' in blog_plan_data:
                blog_plan['categories'] = blog_plan_data['categories']
            
            # Promote available_categories
            if 'available_categories' not in blog_plan and 'available_categories' in blog_plan_data:
                blog_plan['available_categories'] = blog_plan_data['available_categories']
        
        logger.info(f"Successfully processed blog plan, scraped data, and images for: {blog_plan.get('title', 'Unknown')}")
        logger.info(f"Category: {blog_plan.get('category', 'None')}, Categories: {blog_plan.get('categories', [])}")
        logger.info(f"DEBUG: Returning blog_plan with keys: {list(blog_plan.keys())}")
        logger.info(f"DEBUG: blog_plan['title'] = {blog_plan.get('title', 'NOT FOUND')}")
        logger.info(f"DEBUG: blog_plan['data'] keys = {list(blog_plan['data'].keys()) if 'data' in blog_plan and isinstance(blog_plan['data'], dict) else 'NO DATA KEY'}")
        return blog_plan
        
    except Exception as e:
        error_msg = f"Error in process_blog_plan_and_scraped_data: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        # Include the original results in the error for debugging
        error_data = {
            'error': str(e),
            'results_type': str(type(results)),
            'results_length': len(results) if hasattr(results, '__len__') else 'N/A',
            'blog_plan_type': str(type(blog_plan_result)),
            'scraped_data_type': str(type(scraped_data_result)),
            'traceback': traceback.format_exc()
        }
        logger.error(f"Error details: {error_data}")
        raise
        # If we have a blog_plan_id, update its status
        if 'blog_plan_id' in kwargs:
            try:
                blog_plan = BlogPlan.objects.get(id=kwargs['blog_plan_id'])
                blog_plan.status = 'error'
                blog_plan.error = error_msg
                blog_plan.save(update_fields=['status', 'error', 'updated_at'])
            except Exception as update_error:
                logger.error(f"Failed to update blog plan with error: {str(update_error)}")
        
        # Re-raise the exception to mark the task as failed
        raise self.retry(exc=e, countdown=60, max_retries=3)


@shared_task(bind=True, name='autopublish.keyword_content.tasks.process_blog_plan_scraped_data_and_images')
def process_blog_plan_scraped_data_and_images(self, results, **kwargs):
    """
    Process the results from blog plan generation, keyword scraping, and image processing.
    
    Args:
        results: List containing the results from the previous tasks:
            - results[0]: Output from process_blog_plan_and_scraped_data
            - results[1]: Output from process_and_save_images
        **kwargs: Additional keyword arguments (language, country, etc.)
            
    Returns:
        dict: Combined data ready for content generation with processed images
    """
    try:
        logger.info("Processing blog plan, scraped data, and images")
        
        if not results or len(results) != 2:
            raise ValueError(f"Expected 2 results (blog_plan_data and images_data), got {len(results) if results else 0}")
        
        # Extract results from the previous tasks
        blog_plan_data = results[0]
        images_data = results[1]
        
        # Log the processed image URLs
        if images_data.get('success') and images_data.get('processed_images'):
            logger.info(f"Successfully processed {len(images_data['processed_images'])} images:")
            for i, img_url in enumerate(images_data['processed_images'], 1):
                logger.info(f"  Image {i}: {img_url}")
        else:
            error_msg = images_data.get('error', 'Unknown error')
            logger.warning(f"Image processing completed with issues: {error_msg}")
        
        # Add processed images to the blog plan data
        if isinstance(blog_plan_data, dict):
            blog_plan_data['processed_images'] = images_data.get('processed_images', [])
        
        return blog_plan_data
        
    except Exception as e:
        logger.error(f"Error in process_blog_plan_scraped_data_and_images: {str(e)}")
        logger.error(traceback.format_exc())
        # Return whatever data we have, even if image processing failed
        return blog_plan_data if 'blog_plan_data' in locals() else {}


@shared_task(bind=True, name="autopublish.keyword_content.tasks.post_to_wordpress")
def post_to_wordpress(self, payload, status='draft'):
    """
    Save the generated content to the database and post to WordPress.
    
    Args:
        payload: The prepared payload containing blog post data
        status: Status of the post ('draft', 'publish', 'pending')
        
    Returns:
        dict: Result of the operation with status and post data
    """
    logger = logging.getLogger(__name__)
    
    try:
        from .models import BlogPostPayload, Category
        from django.contrib.auth import get_user_model
        import requests
        from django.conf import settings
        from django.utils.text import slugify
        
        # Get or create a default author
        User = get_user_model()
        default_author = User.objects.filter(is_superuser=True).first()
        
        # Extract data if it's wrapped in a result dict from prepare_payload
        if isinstance(payload, dict) and 'data' in payload and isinstance(payload['data'], dict):
            logger.info("Unwrapping payload data in post_to_wordpress")
            payload = payload['data']
            
        # Extract post data - title should come from OpenAI generation
        title = payload.get('title', '')
        if not title or title == 'Unknown':
            # Try to extract from blog_plan if available
            if 'blog_plan' in payload and isinstance(payload['blog_plan'], dict):
                title = payload['blog_plan'].get('title', 'Untitled Post')
            else:
                title = 'Untitled Post'
                logger.warning("No title found in payload, using default")
        
        content = payload.get('content', '')
        meta_description = payload.get('meta_description', '')[:320]
        
        # Create or update the blog post in our database
        post, created = BlogPostPayload.objects.update_or_create(
            title=title,
            defaults={
                'content': content,
                'status': status,
                'meta_description': meta_description,
                'author': default_author,
                'language': payload.get('language', 'en'),
                'word_count': len(content.split()),
                'reading_time': max(1, len(content.split()) // 200),
            }
        )
        
        # Handle categories
        categories = []
        if 'categories' in payload:
            for cat_name in payload['categories']:
                category, _ = Category.objects.get_or_create(
                    name=cat_name,
                    defaults={'slug': slugify(cat_name)[:50]}
                )
                categories.append(category.name)  # Store category names for WordPress
            post.categories.set(categories)
        
        logger.info(f"Successfully {'created' if created else 'updated'} blog post in database: {post.id}")
        logger.info(f"SAVED IN DB: {post.id} - {title}")
        
        # Prepare WordPress API payload
        
        # Prepare categories - handle both categories and available_categories
        categories = []
        
        # First try to get from available_categories if it exists
        if 'available_categories' in payload and payload['available_categories']:
            # available_categories is a tuple of (category_names, category_name_to_id)
            if (isinstance(payload['available_categories'], (list, tuple)) and 
                len(payload['available_categories']) == 2 and
                isinstance(payload['available_categories'][1], dict)):
                
                category_name_to_id = payload['available_categories'][1]
                # Try to find a matching category based on the title or use the first available
                if 'category' in payload and payload['category'] in category_name_to_id:
                    categories = [int(category_name_to_id[payload['category']])]
                    logger.info(f"Using category from payload: {payload['category']} (ID: {categories[0]})")
                elif category_name_to_id:  # Fallback to first available category
                    first_cat_id = next(iter(category_name_to_id.values()))
                    categories = [int(first_cat_id)]
                    logger.info(f"Using first available category: {categories[0]}")
        
        # Fallback to direct categories if available_categories wasn't found or used
        if not categories and 'categories' in payload and payload['categories']:
            if isinstance(payload['categories'], (list, tuple)):
                categories = [int(cat) if str(cat).isdigit() else cat for cat in payload['categories'] if cat]
                logger.info(f"Using direct categories: {categories}")
        
        # If still no valid categories, use default (Uncategorized = 1)
        if not categories:
            categories = [1]
            logger.info("No valid categories found, using default category (Uncategorized)")
        else:
            logger.info(f"Final categories to use: {categories}")
        
        # Get status from payload or use the provided default
        post_status = payload.get('status', status)  # Use status from payload or parameter
        if post_status == 'drafted':  # Fix any legacy 'drafted' status
            post_status = 'publish'
            
        # Prepare the WordPress API payload for the custom endpoint
        wp_payload = {
            'title': title,
            'content': content,
            'excerpt': payload.get('excerpt', ''),
            'status': post_status,  # Use status from payload or default
            'slug': payload.get('slug', slugify(title)),
            'categories': categories,
            'tags': payload.get('tags', []),
            'meta_title': payload.get('meta_title', '')[:60],
            'meta_description': payload.get('meta_description', '')[:160],
            'canonical': payload.get('canonical', ''),
            'og_title': payload.get('og_title', '')[:100],
            'og_description': payload.get('og_description', '')[:200],
            'twitter_title': payload.get('twitter_title', '')[:100],
            'twitter_description': payload.get('twitter_description', '')[:200],
            'featured_image': payload.get('featured_image', '')
        }
        
        logger.info(f"Post status set to: {post_status}")
        logger.info(f"Categories being sent to WordPress: {categories}")
        
        # Remove empty values
        wp_payload = {k: v for k, v in wp_payload.items() if v}
        
        # Log the complete payload being sent to WordPress
        logger.info("="*80)
        logger.info("WORDPRESS PAYLOAD:")
        logger.info(f"  Title: {wp_payload.get('title', 'N/A')}")
        logger.info(f"  Status: {wp_payload.get('status', 'N/A')}")
        logger.info(f"  Categories: {wp_payload.get('categories', 'N/A')}")
        logger.info(f"  Slug: {wp_payload.get('slug', 'N/A')}")
        logger.info(f"  Featured Image: {wp_payload.get('featured_image', 'N/A')}")
        logger.info(f"  Meta Title: {wp_payload.get('meta_title', 'N/A')}")
        logger.info(f"  Meta Description: {wp_payload.get('meta_description', 'N/A')}")
        logger.info(f"  Content Length: {len(wp_payload.get('content', ''))} characters")
        logger.info("="*80)
        
        logger.info(f"Posting to WordPress API: {title}")
        logger.info(f"PUSHED IN WORDPRESS: {title}")
        
        # Make the API request to the custom endpoint
        api_url = 'https://extifixpro.com/wp-json/thirdparty/v1/create-post'
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        response = requests.post(api_url, json=wp_payload, headers=headers, timeout=30)
        response_data = response.json()
        
        if response.status_code == 200 and response_data.get('success'):
            logger.info(f"Successfully posted to WordPress. Post ID: {response_data.get('post_id')}")
            return {
                'success': True,
                'post_id': response_data.get('post_id'),
                'message': response_data.get('message', 'Post created successfully'),
                'url': f"https://extifixpro.com/?p={response_data.get('post_id')}"
            }
        else:
            error_msg = f"Failed to post to WordPress: {response.status_code} - {response_data}"
            logger.error(error_msg)
            raise Exception(error_msg)
            
    except Exception as e:
        error_msg = f"Error in post_to_wordpress: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise  # Re-raise the exception to mark the task as failed
        
@shared_task(bind=True, name="autopublish.keyword_content.tasks.save_blog_post")
def save_blog_post(self, payload, user_email=None, status='draft'):
    """
    Save the generated blog post to WordPress via API.
    
    Args:
        payload: The prepared payload from prepare_payload
        user_email: Email of the user who created the post (kept for backward compatibility)
        status: Status of the post ('draft', 'publish', 'pending')
        
    Returns:
        dict: The WordPress API response
    """
    try:
        # Extract data if it's wrapped in a result dict from prepare_payload
        if isinstance(payload, dict) and 'data' in payload and isinstance(payload['data'], dict):
            logger.info("Unwrapping payload data in save_blog_post")
            payload = payload['data']

        # Chain the post_to_wordpress task without blocking
        return post_to_wordpress.s(payload, status).apply_async()
        
    except Exception as e:
        error_msg = f"Error in save_blog_post: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise self.retry(exc=e, countdown=60, max_retries=3)

@shared_task(bind=True, name='autopublish.keyword_content.tasks.combine_results')
def combine_results(self, *args, **kwargs):
    """
    Combine image processing results with previous task results.
    
    This task can be used in a chain where the previous task's results need to be 
    combined with the current task's results.
    
    Args:
        *args: Positional arguments from previous tasks
        **kwargs: Keyword arguments including:
            - image_results: Results from image processing
            - language: Language code (default: 'en')
            - country: Country code (default: 'us')
            - blog_plan: Blog plan data (optional)
            - scraped_data: Scraped data (optional)
            
    Returns:
        dict: Combined results with status and data
    """
    logger = logging.getLogger(__name__)
    logger.info("Starting combine_results task")
    
    # Initialize default values
    image_results = {}
    language = kwargs.get('language', 'en')
    country = kwargs.get('country', 'us')
    blog_plan = kwargs.get('blog_plan', {})
    scraped_data = kwargs.get('scraped_data', {})
    
    try:
        # Extract image_results from args or kwargs
        if args and len(args) > 0:
            if isinstance(args[0], dict):
                # If first arg is a dict, it's likely the image_results
                image_results = args[0]
            elif len(args) >= 2:
                # If multiple args, they might be blog_plan and scraped_data
                blog_plan = args[0] if isinstance(args[0], dict) else {}
                scraped_data = args[1] if isinstance(args[1], dict) and len(args) > 1 else {}
        
        # Check if we have image_results in kwargs
        if 'image_results' in kwargs:
            image_results = kwargs['image_results']
            
        # Log what we found
        logger.info(f"Combining results - Blog plan: {bool(blog_plan)}, "
                   f"Scraped data: {bool(scraped_data)}, "
                   f"Image results: {bool(image_results)}")
        
        # Format the combined result
        combined = {
            'status': 'success',
            'data': {
                'blog_plan': blog_plan,
                'scraped_data': scraped_data,
                'image_results': image_results,
                'language': language,
                'country': country
            }
        }
        
        logger.info("Successfully combined results")
        return combined
        
    except Exception as e:
        error_msg = f"Error in combine_results: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            'status': 'error',
            'error': error_msg,
            'data': {
                'blog_plan': blog_plan,
                'scraped_data': scraped_data,
                'image_results': image_results,
                'language': language,
                'country': country
            }
        }

@shared_task(name='autopublish.keyword_content.tasks.identity')
def identity(*args, **kwargs):
    """
    Identity function that returns its input.
    Used in task chains to pass through results.
    """
    if args and len(args) == 1:
        return args[0]
    return args or kwargs or None

def prepare_content(kwargs, args):
    try:
        # Add your implementation here
        pass
    except Exception as e:
        logger.error(f"Error in prepare_content: {str(e)}")
        raise
