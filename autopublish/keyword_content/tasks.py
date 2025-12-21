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

        # Process each keyword
        tasks = []
        for keyword_data in request_body.get('keywords', []):
            keyword = keyword_data['text']
            scheduled_time = keyword_data.get('scheduled_time', None)
            language = request_body.get('language', 'en')
            country = request_body.get('country', 'us')
            available_categories = request_body.get('available_categories', [])

            # Create the task chain for each keyword
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
            tasks.append(task_chain)

        # Use group to run all keyword task chains in parallel
        group(tasks).apply_async()

    except Exception as e:
        logger.error(f"Unexpected error in process_keyword_task: {str(e)}", exc_info=True)
        raise  # Re-raise the exception to mark the task as failed

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
    Celery Beat task to check for and publish scheduled posts from PostgreSQL.
    
    This task:
    1. Finds posts with status 'scheduled' where scheduled_at is in the past
    2. Calls save_to_wp task for each post to publish to WordPress
    3. save_to_wp handles the actual publishing and status updates
    
    Returns:
        dict: Summary of the publishing operation
    """
    from .models import BlogPostPayload
    
    scheduled_count = 0
    
    try:
        logger.info("Starting publish_scheduled_posts task")
        now = timezone.now()
        
        # Query PostgreSQL for posts that are scheduled and due for publishing
        posts_to_publish = BlogPostPayload.objects.filter(
            status='scheduled',
            scheduled_at__lte=now
        ).select_related('author')
        
        logger.info(f"Found {posts_to_publish.count()} posts to publish")
        
        for post in posts_to_publish:
            try:
                logger.info(f"Scheduling post for publishing: {post.id} - {post.title}")
                
                # Call save_to_wp task for this post
                save_to_wp.apply_async(
                    args=[post.id],
                    kwargs={'status': 'publish'}
                )
                scheduled_count += 1
                
            except Exception as e:
                error_msg = f"Error scheduling post {post.id}: {str(e)}"
                logger.error(error_msg)
                logger.error(traceback.format_exc())
    
    except Exception as e:
        error_msg = f"Error in publish_scheduled_posts: {str(e)}"
        logger.error(error_msg)
        logger.error(traceback.format_exc())
        raise  # Re-raise to mark the task as failed in Celery
    
    return {
        'status': 'completed',
        'scheduled_for_publishing': scheduled_count,
        'timestamp': timezone.now().isoformat(),
        'message': f'Scheduled {scheduled_count} posts for publishing'
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
                'canonical_url': payload.get('domain_link')
            }
        )
        
        # Handle categories
        if 'categories' in payload:
            post.categories = payload['categories']
            post.save()
        
        # Set status based on whether it's scheduled or not
        if scheduled_at:
            post.status = 'scheduled'
            post.save(update_fields=['status'])
            logger.info(f"Post {post.id} scheduled for {scheduled_at}")
        else:
            post.status = 'draft'
            post.save(update_fields=['status'])
        
        logger.info(f"Successfully {'created' if created else 'updated'} blog post in database: {post.id}")
        logger.info(f"SAVED IN DB: {post.id} - {title} (status: {post.status})")
        
        # Return the post data
        return {
            'success': True,
            'post_id': post.id,
            'title': title,
            'status': post.status,
            'scheduled_at': scheduled_at.isoformat() if scheduled_at else None
        }
        
    except Exception as e:
        error_msg = f"Error in save_blog_post: {str(e)}"
        logger.error(error_msg, exc_info=True)
        raise self.retry(exc=e, countdown=60, max_retries=3)


@shared_task(bind=True, name="autopublish.keyword_content.tasks.save_to_wp")
def save_to_wp(self, post_id, status='publish'):
    """
    Post the blog post to WordPress via API and update status in PostgreSQL.
    
    Args:
        post_id: The database ID of the BlogPostPayload to publish
        status: Status to set in WordPress ('draft', 'publish', 'pending')
        
    Returns:
        dict: The WordPress API response with status updates
    """
    from .models import BlogPostPayload
    import requests
    from django.utils.text import slugify
    
    try:
        # Get the post from database
        post = BlogPostPayload.objects.get(id=post_id)
        logger.info(f"Publishing post {post_id}: {post.title}")
        
        # Update status to 'publishing'
        post.status = 'publishing'
        post.save(update_fields=['status', 'updated_at'])
        
        # Log original categories for debugging
        logger.info(f"Original categories from DB: {post.categories}")
        logger.info(f"Categories type: {type(post.categories)}")
        
        # Process categories with better handling
        categories = []
        if post.categories:
            if isinstance(post.categories, str):
                # Handle string input that looks like a list (e.g., '[2]')
                if post.categories.startswith('[') and post.categories.endswith(']'):
                    try:
                        # Safely evaluate the string as a Python literal
                        import ast
                        categories = ast.literal_eval(post.categories)
                        if not isinstance(categories, list):
                            categories = [categories]  # Convert single value to list
                    except (ValueError, SyntaxError) as e:
                        logger.warning(f"Failed to parse categories string: {post.categories} - Error: {e}")
                        categories = [cat.strip() for cat in post.categories.strip('[]').split(',') if cat.strip()]
                else:
                    # Handle comma-separated string
                    categories = [cat.strip() for cat in post.categories.split(',') if cat.strip()]
            elif isinstance(post.categories, list):
                categories = post.categories
            else:
                logger.warning(f"Unexpected categories format: {post.categories}")
        
        # Convert to integers where possible and validate
        processed_categories = []
        for cat in categories:
            try:
                # Clean up the string (remove any brackets, quotes, etc.)
                cat_str = str(cat).strip('[]\'" ')
                if cat_str.isdigit():
                    processed_categories.append(int(cat_str))
                else:
                    logger.warning(f"Skipping non-numeric category: {cat}")
            except (ValueError, TypeError, AttributeError) as e:
                logger.warning(f"Skipping invalid category: {cat} - Error: {str(e)}")
        
        # Fallback to default category (Uncategorized = 1) if no valid categories
        if not processed_categories:
            logger.warning(f"No valid categories found. Defaulting to Uncategorized (ID: 1)")
            processed_categories = [1]
            
        logger.info(f"Processed categories for WordPress: {processed_categories}")
        
        # Prepare the WordPress API payload
        wp_payload = {
            'title': post.title,
            'content': post.content,
            'excerpt': post.excerpt or '',
            'status': status,
            'slug': post.slug or slugify(post.title),
            'categories': categories,
            'meta_title': post.meta_title or post.title[:60],
            'meta_description': (post.meta_description or '')[:160],
            'canonical': post.canonical_url or '',
            'og_title': (post.og_title or post.title)[:100],
            'og_description': (post.og_description or post.meta_description or '')[:200],
            'twitter_title': (post.twitter_title or post.title)[:100],
            'twitter_description': (post.twitter_description or post.meta_description or '')[:200],
            'featured_image': post.meta_image or ''
        }
        
        # Remove empty values
        wp_payload = {k: v for k, v in wp_payload.items() if v}
        
        # Log the payload
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
        logger.info(f"  Canonical URL: {wp_payload.get('canonical', 'N/A')}")
        logger.info("="*80)
        
        # Make the API request to WordPress
        from urllib.parse import urlparse
        
        # Get domain from post.payload if available, otherwise use canonical_url
        domain_link = None
        if hasattr(post, 'payload') and isinstance(post.payload, dict):
            domain_link = post.payload.get('domain_link')

        if not domain_link and hasattr(post, 'canonical_url'):
            domain_link = post.canonical_url
            
        # Fallback: Try to get from author profile
        if not domain_link and post.author:
            try:
                if hasattr(post.author, 'domain_link') and post.author.domain_link:
                    domain_link = post.author.domain_link
                    logger.info(f"Found domain_link in author model: {domain_link}")
                elif hasattr(post.author, 'profile') and hasattr(post.author.profile, 'domain_link'):
                    domain_link = post.author.profile.domain_link
                    logger.info(f"Found domain_link in author profile: {domain_link}")
            except Exception as e:
                logger.warning(f"Failed to get domain_link from author profile: {e}")

        if not domain_link:
            raise ValueError("No domain_link found in post payload, canonical_url, or author profile")
            
        # Ensure domain has a scheme and clean it up
        if not domain_link.startswith(('http://', 'https://')):
            domain_link = f'https://{domain_link}'
            
        # Extract just the domain and scheme
        parsed = urlparse(domain_link)
        base_domain = f"{parsed.scheme}://{parsed.netloc}"
        
        api_url = f'{base_domain.rstrip("/")}/wp-json/thirdparty/v1/create-post'
        
        # Set canonical URL in the payload if we have it
        canonical_url = None
        if hasattr(post, 'canonical_url') and post.canonical_url:
            canonical_url = post.canonical_url
        elif hasattr(post, 'payload') and isinstance(post.payload, dict) and 'canonical_url' in post.payload:
            canonical_url = post.payload['canonical_url']
            
        if canonical_url and 'canonical' not in wp_payload:
            wp_payload['canonical'] = canonical_url
            logger.info(f"Setting canonical URL to: {canonical_url}")
            
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        logger.info(f"Posting to WordPress at: {api_url}")
        response = requests.post(api_url, json=wp_payload, headers=headers, timeout=30)
        response_data = response.json()
        
        if response.status_code == 200 and response_data.get('success'):
            # Update the post to mark it as published
            post.status = 'published'
            post.published_at = timezone.now()
            post.save(update_fields=['status', 'published_at', 'updated_at'])
            
            logger.info(f"Successfully published post {post_id} to WordPress. WP Post ID: {response_data.get('post_id')}")
            
            return {
                'success': True,
                'wp_post_id': response_data.get('post_id'),
                'db_post_id': post_id,
                'message': response_data.get('message', 'Post created successfully'),
                'url': f"{base_domain.rstrip('/')}/?p={response_data.get('post_id')}"
            }
        else:
            error_msg = f"WordPress API error: {response.status_code} - {response_data}"
            logger.error(error_msg)
            raise Exception(error_msg)
            
    except BlogPostPayload.DoesNotExist:
        error_msg = f"Post {post_id} not found in database"
        logger.error(error_msg)
        raise Exception(error_msg)
        
    except Exception as e:
        error_msg = f"Error in save_to_wp for post {post_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # Update the post status to failed
        try:
            post = BlogPostPayload.objects.get(id=post_id)
            post.status = 'failed'
            post.last_error = str(e)
            post.save(update_fields=['status', 'last_error', 'updated_at'])
        except Exception as update_error:
            logger.error(f"Failed to update post status to failed: {update_error}")
        
        raise self.retry(exc=e, countdown=60, max_retries=3)


def prepare_content(kwargs, args):
    try:
        # Add your implementation here
        pass
    except Exception as e:
        logger.error(f"Error in prepare_content: {str(e)}")
        raise