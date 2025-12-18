import asyncio
from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction
import re
from datetime import datetime
from bson import ObjectId

# Import the ContentGenerator class from base
from .base import ContentGenerator

# Create an instance of ContentGenerator
content_generator = ContentGenerator()

def generate_slug(title: str) -> str:
    """
    Generate a URL-friendly slug from a title string.
    
    Args:
        title: The title to convert to a slug
        
    Returns:
        str: A URL-friendly slug
    """
    if not title:
        raise ValueError("Title cannot be empty")
    
    # Convert to lowercase and strip whitespace
    slug = title.lower().strip()
    
    # Remove special characters, keep alphanumeric, spaces, and hyphens
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    
    # Replace spaces and multiple hyphens with single hyphen
    slug = re.sub(r'[\s-]+', '-', slug)
    
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    
    return slug

logger = get_task_logger(__name__)

@shared_task(bind=True, name='autopublish.content_generator.tasks.get_blog_plan')
def get_blog_plan(self, *args, **kwargs):
    """
    Generate a blog plan for the given keyword.
    
    This task can be called in two ways:
    1. With keyword, language, country as separate arguments
    2. With a single dict containing all parameters (from previous task)
    
    Returns:
        dict: Generated blog plan with status information
    """
    # Handle both direct call and chained call
    if args and isinstance(args[0], dict):
        params = args[0]
        keyword = params.get('keyword')
        language = params.get('language', 'en')
        country = params.get('country', 'us')
        available_categories = params.get('available_categories', [])
        plan_id = params.get('plan_id')
    else:
        keyword = kwargs.get('keyword')
        language = kwargs.get('language', 'en')
        country = kwargs.get('country', 'us')
        available_categories = kwargs.get('available_categories', [])
        plan_id = kwargs.get('plan_id')
    
    if not keyword:
        error_msg = "No keyword provided for blog plan generation"
        logger.error(error_msg)
        return {
            'status': 'error',
            'message': error_msg,
            'data': None
        }
    
    logger.info(f"Starting blog plan generation for keyword: {keyword}")
    
    # Filter out "Uncategorized" from available categories
    filtered_categories = available_categories
    if available_categories and len(available_categories) == 2:
        category_names_list = available_categories[0]
        category_name_to_id = available_categories[1]
        
        # Remove "Uncategorized" from both lists
        filtered_names = [name for name in category_names_list if name.lower() != 'uncategorized']
        filtered_name_to_id = {k: v for k, v in category_name_to_id.items() if k.lower() != 'uncategorized'}
        
        filtered_categories = [filtered_names, filtered_name_to_id]
        logger.info(f"Filtered out 'Uncategorized', remaining categories: {filtered_names}")
    
    async def generate_plan():
        try:
            # Generate the blog plan using the content_generator instance
            return await content_generator.generate_blog_plan(
                keyword=keyword,
                language=language,
                available_categories=filtered_categories
            )
        except Exception as e:
            logger.error(f"Error in generate_blog_plan: {str(e)}", exc_info=True)
            return None
    
    try:
        task_id = self.request.id if hasattr(self, 'request') else 'unknown'
        logger.info(f"Starting blog plan task {task_id} for keyword: {keyword}")
        
        # Run the async function in an event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        blog_plan = loop.run_until_complete(generate_plan())
        loop.close()
        
        # Ensure the blog plan has the required fields
        if not isinstance(blog_plan, dict):
            blog_plan = {}
            
        if 'title' not in blog_plan:
            blog_plan['title'] = f"Blog about {keyword}"
            
        if 'sections' not in blog_plan or not blog_plan['sections']:
            blog_plan['sections'] = [
                {
                    'heading': f"Introduction to {keyword}",
                    'content': f"This is an introduction to {keyword}.",
                    'word_count': 100
                },
                {
                    'heading': f"Why {keyword} is important",
                    'content': f"Here's why {keyword} is important.",
                    'word_count': 150
                },
                {
                    'heading': f"How to get started with {keyword}",
                    'content': f"Here's how you can get started with {keyword}.",
                    'word_count': 200
                },
                {
                    'heading': f"Conclusion about {keyword}",
                    'content': f"In conclusion, {keyword} is an important topic.",
                    'word_count': 100
                }
            ]
            
        if 'meta_description' not in blog_plan:
            blog_plan['meta_description'] = f"Learn all about {keyword} in this comprehensive guide."
            
        if 'keywords' not in blog_plan:
            blog_plan['keywords'] = [keyword]
            
        if 'language' not in blog_plan:
            blog_plan['language'] = language
            
        if 'country' not in blog_plan:
            blog_plan['country'] = country
            
        if 'categories' not in blog_plan:
            blog_plan['categories'] = available_categories or []
        
        return {
            'status': 'success',
            'task_id': task_id,
            'message': 'Blog plan generated successfully',
            'data': blog_plan
        }
        
    except Exception as e:
        error_msg = f"Error in blog plan task {self.request.id if hasattr(self, 'request') else 'unknown'}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        return {
            'status': 'error',
            'task_id': task_id if 'task_id' in locals() else 'unknown',
            'message': error_msg,
            'data': None
        }

from asgiref.sync import async_to_sync

def inject_images_into_content(content: str, images: list) -> str:
    """
    Inject images into the HTML content.
    - 1st image after the 1st heading (h1-h6)
    - 2nd image after the 15th heading (h1-h6)
    """
    if not content or not images:
        return content
        
    try:
        # Find all headings (h1-h6)
        # Split keeping the delimiters (headings)
        parts = re.split(r'(<h[1-6][^>]*>.*?</h[1-6]>)', content, flags=re.IGNORECASE | re.DOTALL)
        
        new_content = []
        heading_count = 0
        
        for i, part in enumerate(parts):
            new_content.append(part)
            
            # Headings are at odd indices (1, 3, 5...)
            if i % 2 == 1:
                heading_count += 1
                
                # Inject 2nd image (index 1) after 15th heading
                # We skip images[0] as it is used for the featured image
                # We also skip injecting at heading 1 as per user request
                if heading_count == 15 and len(images) > 1:
                    img_url = images[1]
                    new_content.append(f'\n<figure class="wp-block-image"><img src="{img_url}" alt="Blog Image" /></figure>\n')
                    
        return "".join(new_content)
    except Exception as e:
        logger.error(f"Error injecting images: {str(e)}")
        return content

@shared_task(bind=True, name='autopublish.content_generator.tasks.generate_keyword_content')
def generate_keyword_content(self, *args, **kwargs):
    """
    Task for generating keyword content based on structured data from fetch_keyword_content_prereqs.
    
    Expected input structure:
    {
        'keyword': str,
        'language': str,
        'country': str,
        'blog_plan': dict,
        'category': {'name': str, 'id': str},
        'image_urls': [str, str],
        'scraped_data': [dict, ...],
        'available_categories': list
    }
    """
    task_id = self.request.id if hasattr(self, 'request') else 'unknown'
    logger.info(f"Starting content generation task {task_id}")
    
    try:
        # Get structured data from previous task
        if args and isinstance(args[0], dict):
            data = args[0].copy()
            data.update(kwargs)
        else:
            data = kwargs
        
        # Log incoming data structure
        logger.info(f"Received data keys: {list(data.keys())}")
        
        # Extract structured data
        keyword = data.get('keyword', '')
        language = data.get('language', 'en')
        country = data.get('country', 'us')
        blog_plan = data.get('blog_plan', {})
        category_info = data.get('category', {})
        image_urls = data.get('image_urls', [])
        scraped_data = data.get('scraped_data', [])
        
        logger.info(f"Processing keyword: {keyword}")
        logger.info(f"Category: {category_info.get('name')} (ID: {category_info.get('id')})")
        logger.info(f"Images: {len(image_urls)}, Scraped items: {len(scraped_data)}")
        
        # Get title from blog plan
        title = blog_plan.get('title', keyword)
        logger.info(f"Using title: {title}")
        
        # Create an async function to handle the async code
        async def generate_content():
            return await content_generator.generate_blog_content(
                keyword=title,
                language=language,
                blog_plan=blog_plan,
                category_names=[category_info.get('name')] if category_info.get('name') else [],
                scraped_articles=scraped_data,
                custom_length_prompt="",
                target_word_count=2000,
                max_expansion_attempts=2,
                backlinks=None
            )

        # Run the async function synchronously
        result = async_to_sync(generate_content)()
        
        if not result or 'content' not in result:
            raise ValueError("No content generated")
        
        # Extract the actual title from the generated result
        generated_title = result.get('title', title)
        if generated_title and generated_title != 'Unknown':
            title = generated_title
            logger.info(f"Using generated title: {title}")
        else:
            logger.warning(f"No title in generated result, using fallback: {title}")
        
        # Use image_urls from structured data
        featured_image = image_urls[0] if image_urls else None
        logger.info(f"Using {len(image_urls)} images, featured: {featured_image}")
        
        # Extract meta_description from blog_plan or result
        meta_description = result.get('meta_description') or blog_plan.get('meta_description', '')
        if not meta_description:
            meta_description = f"Learn about {title}. Comprehensive guide and information."
            logger.info(f"Generated fallback meta_description")
        
        # Build the final result with all necessary data
        result.update({
            'task_status': 'success',
            'task_id': task_id,
            'title': title,
            'meta_description': meta_description,
            'meta_title': title,
            'og_title': title,
            'og_description': meta_description,
            'twitter_title': title,
            'twitter_description': meta_description,
            'language': language,
            'country': country,
            'category': category_info,  # Pass the full category info with name and id
            'image_urls': image_urls,
            'featured_image': featured_image,
            'scraped_data': scraped_data,
            'blog_plan': blog_plan
        })
        
        logger.info(f"Content generation complete: {title}")
        logger.info(f"Category: {category_info.get('name')} (ID: {category_info.get('id')})")
        logger.info(f"Featured image: {featured_image}")
        
        return result
        
    except Exception as e:
        error_msg = f"Error in content generation: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        return {
            'status': 'error',
            'task_id': self.request.id if hasattr(self, 'request') else 'unknown',
            'message': error_msg,
            'error': str(e)
        }

@shared_task(bind=True, name='autopublish.content_generator.tasks.prepare_payload')
def prepare_payload(self, *args, **kwargs):
    """
    Prepare and validate the payload for blog post creation.
    
    This task can be called in two ways:
    1. With post_data as a keyword argument: prepare_payload(post_data={...})
    2. With post_data as the first positional argument: prepare_payload({...})
    
    Args:
        self: The task instance (automatically provided by bind=True)
        post_data: Dictionary containing post data (can be in args[0] or kwargs['post_data'])
        
    Returns:
        dict: Prepared and validated payload
    """
    try:
        task_id = self.request.id if hasattr(self, 'request') else 'unknown'
        logger.info(f"Starting payload preparation task {task_id}")
        
        # Get post_data from either args[0] or kwargs['post_data']
        post_data = {}
        if args and isinstance(args[0], dict):
            post_data = args[0]
        elif 'post_data' in kwargs and isinstance(kwargs['post_data'], dict):
            post_data = kwargs['post_data']
        
        # If post_data is a string, try to parse it as JSON
        if isinstance(post_data, str):
            import json
            try:
                post_data = json.loads(post_data)
            except (json.JSONDecodeError, TypeError):
                post_data = {}
        
        # Ensure post_data is a dictionary
        if not isinstance(post_data, dict):
            post_data = {}
        
        # Get the title and generate a slug if not provided
        title = post_data.get('title', 'Untitled Post')
        if 'slug' not in post_data:
            post_data['slug'] = generate_slug(title)
        
        # Set default values for required fields if not provided
        # Note: 'status' is NOT set here - it should come from the task chain
        defaults = {
            'visibility': 'public',
            'publishedAt': None,
            'createdAt': datetime.utcnow().isoformat(),
            'updatedAt': datetime.utcnow().isoformat(),
            'meta': {
                'og_type': 'article',
                'twitter_card': 'summary_large_image',
                'feature_image_alt': title,
                'feature_image_caption': ''
            },
            'tags': [],
            'authors': []
        }
        
        # Apply defaults to post_data
        for key, value in defaults.items():
            post_data.setdefault(key, value)
        
        # Ensure meta is a dictionary and apply meta defaults
        if not isinstance(post_data.get('meta'), dict):
            post_data['meta'] = {}
            
        meta_defaults = {
            'og_title': post_data.get('ogTitle', title),
            'og_description': post_data.get('ogDescription', post_data.get('meta_description', '')),
            'twitter_title': post_data.get('twitterTitle', title),
            'twitter_description': post_data.get('twitterDescription', post_data.get('meta_description', '')),
            'feature_image': post_data.get('metaImage')
        }
        
        for key, value in meta_defaults.items():
            if key not in post_data['meta'] and value is not None:
                post_data['meta'][key] = value
        
        # Clean up the payload by removing None values
        def remove_none(d):
            if not isinstance(d, dict):
                return d
            return {k: remove_none(v) for k, v in d.items() if v is not None}
        
        # Preserve categories and other important fields
        # Extract status - ignore task_status, only use valid post statuses
        current_status = post_data.pop('status', None)
        # Filter out task statuses like 'success', only keep valid post statuses
        valid_post_statuses = ['draft', 'publish', 'pending', 'scheduled']
        if current_status not in valid_post_statuses:
            logger.info(f"Invalid post status '{current_status}' found, defaulting to 'publish'")
            current_status = 'publish'  # Default to publish if invalid or missing
        else:
            logger.info(f"Valid post status found: '{current_status}'")
        
        # Extract category information
        category_info = post_data.pop('category', {})
        category_id = None
        category_name = None
        
        if isinstance(category_info, dict):
            category_id = category_info.get('id')
            category_name = category_info.get('name')
            logger.info(f"Extracted category: {category_name} (ID: {category_id})")
        
        preserved_fields = {
            'status': current_status,
            'title': post_data.pop('title', None),
            'content': post_data.pop('content', None),
            'image_urls': post_data.pop('image_urls', []),
            'featured_image': post_data.pop('featured_image', None),
            'blog_plan': post_data.pop('blog_plan', {}),
            'scraped_data': post_data.pop('scraped_data', []),
            'task_status': post_data.pop('task_status', None),
            'category_id': category_id,
            'category_name': category_name
        }
        
        # Merge kwargs into preserved_fields
        preserved_fields.update({k: v for k, v in kwargs.items() if k not in preserved_fields})
        
        logger.info(f"Category for WordPress: {category_name} (ID: {category_id})")
        
        post_data = remove_none(post_data)
        
        # Add back preserved fields
        for field, value in preserved_fields.items():
            if value is not None and value != '':
                post_data[field] = value
        
        # Set categories as a list with the category ID
        if category_id:
            post_data['categories'] = [int(category_id)]
            logger.info(f"Set categories to: {post_data['categories']}")
        else:
            post_data['categories'] = [1]  # Default to Uncategorized
            logger.info("No category ID found, using default (Uncategorized)")
            
        # Inject images into content if available
        image_urls = post_data.get('image_urls', [])
        content = post_data.get('content')
        
        if image_urls and content:
            logger.info(f"Injecting {len(image_urls)} images into content in prepare_payload")
            post_data['content'] = inject_images_into_content(content, image_urls)
        elif image_urls:
            logger.warning("Have images but no content to inject into")
        else:
            logger.info("No images to inject")

        
        logger.info(f"Successfully prepared payload for post: {title}")
        logger.info(f"Post status: {post_data.get('status', 'publish')}")
        logger.info(f"Categories: {post_data.get('categories', [])}")
        
        return {
            'status': 'success',
            'task_id': task_id,
            'message': 'Payload prepared successfully',
            'data': post_data
        }
        
    except Exception as e:
        error_msg = f"Error in prepare_payload task {self.request.id if hasattr(self, 'request') else 'unknown'}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        if hasattr(self, 'retry'):
            raise self.retry(exc=e, countdown=60, max_retries=3)
        
        return {
            'status': 'error',
            'task_id': self.request.id if hasattr(self, 'request') else 'unknown',
            'message': error_msg,
            'error': str(e)
        }


@shared_task(bind=True, name='autopublish.content_generator.tasks.rephrase_content_task')
def rephrase_content_task(self, data):
    """
    Task to rephrase content using the ContentGenerator.
    
    Args:
        data (dict): Dictionary containing:
            - content: Original content (required)
            - title: Original title (optional)
            - language: Target language (default: 'en')
            - target_word_count: Target word count (default: 1000)
            - images: List of images/image links
            - backlinks: List of backlinks
            - video_links: Video links
            
    Returns:
        dict: Rephrased content result
    """
    task_id = self.request.id if hasattr(self, 'request') else 'unknown'
    logger.info(f"Starting rephrase task {task_id}")
    
    try:
        # Import here to avoid potential circular imports
        from .views import rephrase_news_content
        
        # Run async function in a new event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # rephrase_news_content handles the logic
            result = loop.run_until_complete(rephrase_news_content(data))
            return result
        finally:
            loop.close()
            
    except Exception as e:
        error_msg = f"Error in rephrase task {task_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        return {
            'status': 'error',
            'error': str(e)
        }

