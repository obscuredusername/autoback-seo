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
            "target_path": request_body.get("target_path", "CRM.posts"),
        }


        keyword = request_body['keywords'][0]['text']
        scheduled_time = request_body['keywords'][0].get('scheduled_time', None)
        language = request_body.get('language', 'en')
        country = request_body.get('country', 'us')
        available_categories = request_body.get('available_categories', [])
        
        # Create the task chain with chord for parallel execution
        task_chain = (
            # Step 1: Create blog plan record and get metadata
            signature(
                'autopublish.keyword_content.tasks.fetch_keyword_content_prereqs',
                kwargs={
                    'keyword': keyword,
                    'language': language,
                    'country': country,
                    'available_categories': available_categories,
                    'scheduled_time': scheduled_time,
                }
            ) | 
            # Step 2: Run parallel tasks and process results
            chord(
                # Parallel tasks
                [
                    signature(
                        'autopublish.content_generator.tasks.get_blog_plan',
                        kwargs={
                            'keyword': keyword,
                            'language': language,
                            'country': country,
                            'available_categories': available_categories
                        },
                        immutable=True
                    ),
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
                # Callback to process parallel results
                signature(
                    'autopublish.keyword_content.tasks.process_parallel_results',
                    kwargs={
                        'keyword': keyword,
                        'language': language,
                        'country': country,
                        'available_categories': available_categories,
                        'scheduled_time': scheduled_time
                    }
                ) |
                # Step 3: Generate content with the structured data
                signature(
                    'autopublish.content_generator.tasks.generate_keyword_content'
                ) |
                # Step 4: Prepare payload (inject images, format data)
                signature(
                    'autopublish.content_generator.tasks.prepare_payload',
                    kwargs={
                        'user_email': request_body.get('user_email'),
                        'domain_link': request_body.get('domain_link'),
                        'target_path': request_body.get('target_path', 'CRM.posts')
                    }
                ) |
                # Step 5: Save blog post
                signature(
                    'autopublish.keyword_content.tasks.save_blog_post',
                    kwargs={
                        'user_email': request_body.get('user_email'),
                        'status': 'publish',
                        'scheduled_time': scheduled_time
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
def fetch_keyword_content_prereqs(self, keyword: str, language: str = "en", country: str = "us", available_categories: list = None, scheduled_time: str = None):
    """
    Prepare keyword content prerequisites - creates blog plan record and returns metadata.
    The actual parallel tasks are handled in process_keyword_task via chord.
    
    Args:
        keyword: The main keyword to generate content for
        language: Language code (default: 'en')
        country: Country code (default: 'us')
        available_categories: List of [category_names, category_name_to_id_dict]
        scheduled_time: Scheduled time for the post
        
    Returns:
        dict: Metadata to pass to parallel tasks
    """
    try:
        logger.info(f"Starting fetch_keyword_content_prereqs for keyword: {keyword}")
        
        # Create a new blog plan in PostgreSQL
        blog_plan_record = BlogPlan.objects.create(
            keyword=keyword,
            language=language,
            country=country,
            available_categories=available_categories or [],
            status='processing',
            tasks={}
        )
        
        logger.info(f"Created blog plan record with ID: {blog_plan_record.id}")
        
        # Return metadata for the next tasks
        return {
            'keyword': keyword,
            'language': language,
            'country': country,
            'plan_id': str(blog_plan_record.id),
            'available_categories': available_categories,
            'scheduled_time': scheduled_time
        }  
    except Exception as e:
        error_msg = f"Error in fetch_keyword_content_prereqs: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        
        # Update the blog plan with error status if we have a blog_plan_record
        if 'blog_plan_record' in locals():
            try:
                blog_plan_record.status = 'error'
                blog_plan_record.error = str(e)
                blog_plan_record.save(update_fields=['status', 'error', 'updated_at'])
            except Exception as update_error:
                logger.error(f"Failed to update blog plan with error: {str(update_error)}")
        
        raise self.retry(exc=e, countdown=60)  # Retry after 60 seconds


@shared_task(bind=True, name='autopublish.keyword_content.tasks.process_parallel_results')
def process_parallel_results(self, results, **kwargs):
    """
    Process results from parallel tasks (blog_plan, scraper, images) and structure data.
    
    Args:
        results: List of results from parallel tasks
        **kwargs: Additional metadata (keyword, language, country, available_categories, plan_id, scheduled_time)
        
    Returns:
        dict: Structured data ready for content generation
    """
    try:
        logger.info("Processing parallel task results")
        
        # Extract metadata from kwargs
        keyword = kwargs.get('keyword', '')
        language = kwargs.get('language', 'en')
        country = kwargs.get('country', 'us')
        available_categories = kwargs.get('available_categories', [])
        plan_id = kwargs.get('plan_id', '')
        scheduled_time = kwargs.get('scheduled_time', None)
        
        # Extract results
        blog_plan_result = results[0] if len(results) > 0 else {}
        scraped_data_result = results[1] if len(results) > 1 else {}
        images_result = results[2] if len(results) > 2 else {}
        
        # Extract blog plan data
        blog_plan_data = blog_plan_result.get('data', blog_plan_result) if isinstance(blog_plan_result, dict) else {}
        
        # Extract selected category from blog plan
        selected_category = blog_plan_data.get('category', '')
        logger.info(f"Blog plan selected category: {selected_category}")
        
        # Match category with available categories to get ID
        category_id = None
        category_name = selected_category
        
        if available_categories and len(available_categories) == 2:
            category_names_list = available_categories[0]
            category_name_to_id = available_categories[1]
            
            # Filter out Uncategorized from the mapping
            filtered_name_to_id = {k: v for k, v in category_name_to_id.items() if k.lower() != 'uncategorized'}
            
            # If selected category is Uncategorized or not found, use first available category
            if selected_category.lower() == 'uncategorized' or selected_category not in filtered_name_to_id:
                if filtered_name_to_id:
                    # Use the first non-Uncategorized category
                    category_name = list(filtered_name_to_id.keys())[0]
                    category_id = filtered_name_to_id[category_name]
                    logger.info(f"Selected category was '{selected_category}', using first available: {category_name} (ID: {category_id})")
                else:
                    # Fallback to Uncategorized only if no other categories exist
                    category_id = category_name_to_id.get('Uncategorized', '1')
                    category_name = 'Uncategorized'
                    logger.warning(f"No valid categories available, falling back to Uncategorized (ID: {category_id})")
            else:
                # Use the matched category
                category_id = filtered_name_to_id[selected_category]
                logger.info(f"Matched category '{selected_category}' to ID: {category_id}")
        
        # Extract image URLs
        image_urls = []
        if isinstance(images_result, dict):
            processed_images = images_result.get('processed_images', [])
            image_urls = processed_images[:2] if len(processed_images) >= 2 else processed_images
            logger.info(f"Extracted {len(image_urls)} image URLs")
        
        # Extract scraped data
        scraped_data = scraped_data_result.get('results', []) if isinstance(scraped_data_result, dict) else []
        
        # Build structured response
        structured_data = {
            'keyword': keyword,
            'language': language,
            'country': country,
            'blog_plan': blog_plan_data,
            'category': {
                'name': category_name,
                'id': category_id
            },
            'image_urls': image_urls,
            'scraped_data': scraped_data,
            'available_categories': available_categories,
            'scheduled_time': scheduled_time
        }
        
        logger.info(f"Successfully processed parallel results for keyword: {keyword}")
        logger.info(f"Category: {category_name} (ID: {category_id}), Images: {len(image_urls)}, Scraped items: {len(scraped_data)}")
        
        return structured_data
        
    except Exception as e:
        error_msg = f"Error in process_parallel_results: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise

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
            processed_images = images_data.get('processed_images', [])
            blog_plan_data['processed_images'] = processed_images
            
            # Set the first image as the featured image if available
            if processed_images and len(processed_images) > 0:
                blog_plan_data['featured_image'] = processed_images[0]
                logger.info(f"Set featured image to: {processed_images[0]}")
        
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
        from .models import BlogPostPayload
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
        if 'categories' in payload:
            # Store categories as a list in the JSONField
            post.categories = [c for c in payload['categories'] if isinstance(c, str)]
            post.save()
        
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
            'meta_title': payload.get('meta_title') or title[:60],
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
        domain_link = payload.get('domain_link', 'https://extifixpro.com')
        api_url = f'{domain_link}/wp-json/thirdparty/v1/create-post'
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
                'url': f"{domain_link}/?p={response_data.get('post_id')}"
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
def save_blog_post(self, payload, user_email=None, status='draft', scheduled_time=None):
    """
    Save the generated blog post to PostgreSQL database.
    
    Args:
        payload: The prepared payload from prepare_payload
        user_email: Email of the user who created the post (kept for backward compatibility)
        status: Status of the post ('draft', 'publish', 'pending')
        scheduled_time: ISO format scheduled time for the post
        
    Returns:
        dict: The saved post data with database ID
    """
    try:
        from .models import BlogPostPayload
        from django.contrib.auth import get_user_model
        from django.utils.text import slugify
        
        # Extract data if it's wrapped in a result dict from prepare_payload
        if isinstance(payload, dict) and 'data' in payload and isinstance(payload['data'], dict):
            logger.info(f"Unwrapping payload data in save_blog_post")
            payload = payload['data']
        
        # Get or create default author (ID=1)
        User = get_user_model()
        default_author = User.objects.filter(id=1).first()
        if not default_author:
            default_author = User.objects.filter(is_superuser=True).first()
        
        # Extract post data
        title = payload.get('title', '')
        if not title or title == 'Unknown':
            if 'blog_plan' in payload and isinstance(payload['blog_plan'], dict):
                title = payload['blog_plan'].get('title', 'Untitled Post')
            else:
                title = 'Untitled Post'
                logger.warning("No title found in payload, using default")
        
        content = payload.get('content', '')
        
        # Get scheduled_time from payload or parameter
        if not scheduled_time:
            scheduled_time = payload.get('scheduled_time', None)
        
        # Parse scheduled_time to datetime if it's a string
        from datetime import datetime
        scheduled_at = None
        if scheduled_time:
            try:
                if isinstance(scheduled_time, str):
                    # Handle ISO format with or without milliseconds
                    scheduled_at = datetime.fromisoformat(scheduled_time.replace('Z', '+00:00'))
                else:
                    scheduled_at = scheduled_time
                logger.info(f"Scheduled time set to: {scheduled_at}")
            except Exception as e:
                logger.warning(f"Failed to parse scheduled_time: {e}")
        
        # Get meta_description or use excerpt as fallback
        meta_description = payload.get('meta_description', '')
        if not meta_description:
            meta_description = payload.get('excerpt', '')
        excerpt = meta_description[:320] if meta_description else ''
        
        # Get the keyword from blog_plan or payload
        keyword = payload.get('keyword', '')
        if not keyword and 'blog_plan' in payload and isinstance(payload['blog_plan'], dict):
            keywords_list = payload['blog_plan'].get('keywords', [])
            keyword = keywords_list[0] if keywords_list else ''
        
        # Get featured image (first image or from payload)
        featured_image = payload.get('featured_image', '')
        if not featured_image and 'image_urls' in payload and payload['image_urls']:
            featured_image = payload['image_urls'][0]
        
        # Prepare meta fields
        meta_title = title  # Use original title as meta_title
        meta_keywords = keyword  # Use plural field name
        focus_keyword = keyword  # Use the same keyword
        meta_image = featured_image
        
        # Prepare OG fields (same as meta fields)
        og_title = payload.get('og_title', title)
        og_description = payload.get('og_description', meta_description)
        
        # Prepare Twitter fields (same as meta fields)
        twitter_title = payload.get('twitter_title', title)
        twitter_description = payload.get('twitter_description', meta_description)
        
        # Create or update the blog post in our database
        post, created = BlogPostPayload.objects.update_or_create(
            title=title,
            defaults={
                'content': content,
                'excerpt': excerpt,
                'status': 'draft',  # Always save as draft initially
                'slug': payload.get('slug', slugify(title)),
                'meta_title': meta_title,
                'meta_description': meta_description[:320],
                'meta_keywords': meta_keywords,
                'focus_keyword': focus_keyword,
                'meta_image': meta_image,
                'og_title': og_title[:100],
                'og_description': og_description[:200],
                'twitter_title': twitter_title[:100],
                'twitter_description': twitter_description[:200],
                'author_id': 1,  # Always use author ID 1
                'language': payload.get('language', 'en'),
                'word_count': len(content.split()),
                'reading_time': max(1, len(content.split()) // 200),
                'scheduled_at': scheduled_at,  # Set from keyword scheduled_time
                'published_at': None,  # Will be set when published to WP
            }
        )
        
        # Handle categories
        if 'categories' in payload:
            post.categories = payload['categories']
            post.save()
        
        logger.info(f"Successfully {'created' if created else 'updated'} blog post in database: {post.id}")
        logger.info(f"SAVED IN DB: {post.id} - {title}")
        
        # Add the database ID to the payload for the next task
        payload['db_post_id'] = post.id
        payload['db_post_title'] = title
        
        # Chain to save_to_wp task
        return save_to_wp.s(payload, status).apply_async()
        
    except Exception as e:
        error_msg = f"Error in save_blog_post: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise self.retry(exc=e, countdown=60, max_retries=3)


@shared_task(bind=True, name="autopublish.keyword_content.tasks.save_to_wp")
def save_to_wp(self, payload, status='draft'):
    """
    Post the blog post to WordPress via API.
    
    Args:
        payload: The prepared payload with post data
        status: Status of the post ('draft', 'publish', 'pending')
        
    Returns:
        dict: The WordPress API response
    """
    try:
        import requests
        from django.utils.text import slugify
        
        # Extract data if it's wrapped
        if isinstance(payload, dict) and 'data' in payload and isinstance(payload['data'], dict):
            logger.info("Unwrapping payload data in save_to_wp")
            payload = payload['data']
        
        # Extract post data
        title = payload.get('title', 'Untitled Post')
        content = payload.get('content', '')
        
        # Prepare categories
        categories = []
        if 'categories' in payload and payload['categories']:
            if isinstance(payload['categories'], (list, tuple)):
                categories = [int(cat) if str(cat).isdigit() else cat for cat in payload['categories'] if cat]
                logger.info(f"Using direct categories: {categories}")
        
        # If no valid categories, use default (Uncategorized = 1)
        if not categories:
            categories = [1]
            logger.info("No valid categories found, using default category (Uncategorized)")
        else:
            logger.info(f"Final categories to use: {categories}")
        
        # Get status from payload or use the provided default
        post_status = payload.get('status', status)
        if post_status == 'drafted':
            post_status = 'publish'
        
        # Prepare the WordPress API payload
        wp_payload = {
            'title': title,
            'content': content,
            'excerpt': payload.get('excerpt', ''),
            'status': post_status,
            'slug': payload.get('slug', slugify(title)),
            'categories': categories,
            'tags': payload.get('tags', []),
            'meta_title': payload.get('meta_title', title)[:60],
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
        logger.info(f"PUSHED TO WORDPRESS: {title}")
        
        # Make the API request to the custom endpoint
        domain_link = payload.get('domain_link', 'https://extifixpro.com')
        api_url = f'{domain_link}/wp-json/thirdparty/v1/create-post'
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        response = requests.post(api_url, json=wp_payload, headers=headers, timeout=30)
        response_data = response.json()
        
        if response.status_code == 200 and response_data.get('success'):
            logger.info(f"Successfully posted to WordPress. Post ID: {response_data.get('post_id')}")
            
            # Update the database record with published status and timestamp
            db_post_id = payload.get('db_post_id')
            if db_post_id:
                try:
                    from .models import BlogPostPayload
                    from django.utils import timezone
                    
                    post = BlogPostPayload.objects.get(id=db_post_id)
                    post.status = 'publish'
                    post.published_at = timezone.now()
                    post.save(update_fields=['status', 'published_at'])
                    logger.info(f"Updated DB post {db_post_id} status to 'publish' and set published_at")
                except Exception as e:
                    logger.error(f"Failed to update DB post status: {e}")
            
            return {
                'success': True,
                'post_id': response_data.get('post_id'),
                'db_post_id': db_post_id,
                'message': response_data.get('message', 'Post created successfully'),
                'url': f"{domain_link}/?p={response_data.get('post_id')}"
            }
        else:
            error_msg = f"Failed to post to WordPress: {response.status_code} - {response_data}"
            logger.error(error_msg)
            raise Exception(error_msg)
            
    except Exception as e:
        error_msg = f"Error in save_to_wp: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise self.retry(exc=e, countdown=60, max_retries=3)


def prepare_content(kwargs, args):
    try:
        # Add your implementation here
        pass
    except Exception as e:
        logger.error(f"Error in prepare_content: {str(e)}")
        raise