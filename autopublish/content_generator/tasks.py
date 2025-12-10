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
    
    async def generate_plan():
        try:
            # Generate the blog plan using the content_generator instance
            return await content_generator.generate_blog_plan(
                keyword=keyword,
                language=language,
                available_categories=available_categories
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
    Task for generating keyword content based on a blog plan.
    
    This task can be called with either:
    - A dict containing blog plan data as the first argument
    - Or with keyword arguments containing the blog plan
    
    The input should contain all necessary information for content generation,
    including blog_plan, scraped_data, and image_results.
    """
    task_id = self.request.id if hasattr(self, 'request') else 'unknown'
    logger.info(f"Starting content generation task {task_id}")
    
    try:
        # Get parameters from args or kwargs
        # In a chain, the previous task's result comes in args[0]
        # Additional parameters come in kwargs
        if args and isinstance(args[0], dict):
            # If first arg is a dict, use that as our base data
            data = args[0].copy()  # Make a copy to avoid modifying the original
            # Merge in any additional kwargs
            data.update(kwargs)
        else:
            # Otherwise use kwargs
            data = kwargs
        
        # DEBUG: Log the incoming data structure
        logger.info(f"DEBUG: Incoming data keys: {list(data.keys()) if isinstance(data, dict) else 'not a dict'}")
        if isinstance(data, dict):
            if 'data' in data:
                logger.info(f"DEBUG: data['data'] keys: {list(data['data'].keys()) if isinstance(data['data'], dict) else 'not a dict'}")
            if 'blog_plan' in data:
                logger.info(f"DEBUG: data['blog_plan'] keys: {list(data['blog_plan'].keys()) if isinstance(data['blog_plan'], dict) else 'not a dict'}")
                if isinstance(data['blog_plan'], dict) and 'data' in data['blog_plan']:
                    logger.info(f"DEBUG: data['blog_plan']['data'] keys: {list(data['blog_plan']['data'].keys()) if isinstance(data['blog_plan']['data'], dict) else 'not a dict'}")
        
        # If we have a 'data' key, use that as our main data
        if 'data' in data and isinstance(data['data'], dict):
            # But preserve any top-level keys that aren't in data['data']
            top_level_extras = {k: v for k, v in data.items() if k != 'data'}
            data = data['data']
            data.update(top_level_extras)  # Merge back the extras
        
        # Extract data with proper fallbacks
        blog_plan = data.get('blog_plan', {})
        logger.info(f"DEBUG: blog_plan keys: {list(blog_plan.keys()) if isinstance(blog_plan, dict) else 'not a dict'}")
        scraped_data = data.get('scraped_data', {})
        logger.info(f"DEBUG: scraped_data keys: {list(scraped_data.keys()) if isinstance(scraped_data, dict) else 'not a dict'}")
        image_results = data.get('image_results', {})
        logger.info(f"DEBUG: image_results keys: {list(image_results.keys()) if isinstance(image_results, dict) else 'not a dict'}")
        
        # If we have a nested blog_plan, extract it
        if not blog_plan and 'blog_plan' in data.get('data', {}):
            blog_plan = data['data']['blog_plan']
        
        # Get language and country with proper fallbacks
        language = data.get('language')
        country = data.get('country')
        
        if not language or not country:
            if isinstance(blog_plan, dict):
                language = blog_plan.get('language', 'en')
                country = blog_plan.get('country', 'us')
            else:
                language = 'en'
                country = 'us'
        
        # Get title with proper fallback - check multiple levels of nesting
        title = 'Unknown'
        
        # First, try to get from top-level data
        if isinstance(data, dict) and data.get('title') and data.get('title') != 'Unknown':
            title = data['title']
            logger.info(f"Found title in top-level data: {title}")
        # Then try blog_plan at top level
        elif isinstance(blog_plan, dict) and blog_plan.get('title') and blog_plan.get('title') != 'Unknown':
            title = blog_plan['title']
            logger.info(f"Found title in blog_plan: {title}")
        # Then try blog_plan['data'] (nested structure from process_blog_plan_and_scraped_data)
        elif isinstance(blog_plan, dict) and 'data' in blog_plan and isinstance(blog_plan['data'], dict):
            if blog_plan['data'].get('title') and blog_plan['data'].get('title') != 'Unknown':
                title = blog_plan['data']['title']
                logger.info(f"Found title in blog_plan['data']: {title}")
        
        if title == 'Unknown':
            logger.warning("Could not find title in any expected location, using 'Unknown'")
        
        logger.info(f"Processing content generation for: {title}")
        
        # Log what we found
        if scraped_data and isinstance(scraped_data, (list, dict)):
            item_count = len(scraped_data) if hasattr(scraped_data, '__len__') else 1
            logger.info(f"Using scraped data with {item_count} items")
            
        if image_results and isinstance(image_results, (list, dict)):
            img_count = len(image_results) if hasattr(image_results, '__len__') else 1
            logger.info(f"Using {img_count} processed images")
        
        # Get categories from blog plan - check nested structure
        categories = []
        category = None
        available_categories = None
        
        # Try to get category from top-level blog_plan
        if isinstance(blog_plan, dict):
            if 'category' in blog_plan:
                category = blog_plan['category']
                categories = [category]
            elif 'categories' in blog_plan and isinstance(blog_plan['categories'], list):
                categories = blog_plan['categories']
            
            # Also check nested blog_plan['data']
            if 'data' in blog_plan and isinstance(blog_plan['data'], dict):
                blog_plan_data = blog_plan['data']
                if not category and 'category' in blog_plan_data:
                    category = blog_plan_data['category']
                    categories = [category]
                elif not categories and 'categories' in blog_plan_data and isinstance(blog_plan_data['categories'], list):
                    categories = blog_plan_data['categories']
            
            # Get available_categories for passing through
            available_categories = blog_plan.get('available_categories') or (
                blog_plan.get('data', {}).get('available_categories') if isinstance(blog_plan.get('data'), dict) else None
            )
        
        
        logger.info(f"Extracted category: {category}, categories: {categories}")
        
        # Map category names to IDs if available_categories is present
        mapped_categories = []
        if available_categories and isinstance(available_categories, list):
            # Create a lookup map: name -> id
            cat_map = {}
            for cat in available_categories:
                if isinstance(cat, dict) and 'name' in cat and 'id' in cat:
                    cat_map[cat['name'].lower()] = cat['id']
                elif isinstance(cat, dict) and 'name' in cat:
                    # Handle case where id might be missing or different key
                    cat_id = cat.get('id') or cat.get('term_id')
                    if cat_id:
                        cat_map[cat['name'].lower()] = cat_id
            
            logger.info(f"Category mapping available for {len(cat_map)} categories")
            
            # Map the extracted categories
            current_cats = categories if isinstance(categories, list) else [categories] if categories else []
            if category and category not in current_cats:
                current_cats.append(category)
                
            for cat_name in current_cats:
                if isinstance(cat_name, str):
                    cat_id = cat_map.get(cat_name.lower())
                    if cat_id:
                        mapped_categories.append({'id': cat_id, 'name': cat_name})
                        logger.info(f"Mapped category '{cat_name}' to ID {cat_id}")
                    else:
                        logger.warning(f"Could not find ID for category '{cat_name}'")
                elif isinstance(cat_name, dict) and 'id' in cat_name:
                    mapped_categories.append(cat_name)
        
        # If we successfully mapped categories, update the categories list
        if mapped_categories:
            categories = mapped_categories
            logger.info(f"Updated categories with IDs: {categories}")

        # Create an async function to handle the async code
        async def generate_content():
            return await content_generator.generate_blog_content(
                keyword=title,
                language=language,
                blog_plan=blog_plan,
                category_names=categories,
                scraped_articles=scraped_data,
                # Optional parameters with defaults
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
        # The generate_blog_content should return a title in the result
        generated_title = result.get('title', title)
        if generated_title and generated_title != 'Unknown':
            title = generated_title
            logger.info(f"Using generated title: {title}")
        else:
            logger.warning(f"No title in generated result, using fallback: {title}")
            
        # Get image URLs from blog plan and processed images
        image_urls = []
        featured_image = None
        
        # First, try to get from processed_images (these are the actual uploaded images)
        processed_images = blog_plan.get('processed_images', []) or image_results.get('processed_images', [])
        if processed_images and isinstance(processed_images, list):
            image_urls = processed_images
            featured_image = processed_images[0] if processed_images else None
            logger.info(f"Found {len(processed_images)} processed images, using first as featured image")
        
        # Fallback to image_prompts if no processed images
        if not image_urls and 'image_prompts' in blog_plan and isinstance(blog_plan['image_prompts'], list):
            image_urls = [img.get('url') for img in blog_plan['image_prompts'] if img.get('url')]
            featured_image = image_urls[0] if image_urls else None
            logger.info(f"Using {len(image_urls)} images from blog plan image_prompts")
        
        # Extract meta_description from blog_plan or result
        meta_description = result.get('meta_description') or blog_plan.get('meta_description', '')
        if not meta_description:
            # Generate a simple meta description from the title
            meta_description = f"Learn about {title}. Comprehensive guide and information."
            logger.info(f"Generated fallback meta_description")
        else:
            logger.info(f"Using meta_description from blog plan: {meta_description[:50]}...")
            
        # Add metadata to the result
        result.update({
            'task_status': 'success',  # Renamed from 'status' to avoid overwriting post status
            'task_id': task_id,
            'title': title,  # Use the extracted/generated title
            'meta_description': meta_description,  # Add meta description
            'meta_title': title,  # Use title as meta_title
            'og_title': title,  # OpenGraph title
            'og_description': meta_description,  # OpenGraph description
            'twitter_title': title,  # Twitter title
            'twitter_description': meta_description,  # Twitter description
            'language': language,
            'country': country,
            'category': category,  # Use extracted category
            'available_categories': available_categories,  # Use extracted available_categories
            'categories': categories,  # Include the categories list
            'category_ids': [cat['id'] for cat in categories if isinstance(cat, dict) and 'id' in cat],
            'image_urls': image_urls,
            'featured_image': featured_image,  # Set the featured image
            # Pass through important data for next steps
            'blog_plan': blog_plan,
            'image_results': image_results,
            'processed_images': processed_images
        })
        
        logger.info(f"Result metadata: featured_image={featured_image}, meta_description={meta_description[:50] if meta_description else 'None'}...")
        
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
        
        preserved_fields = {
            'available_categories': post_data.pop('available_categories', None),
            'category': post_data.pop('category', None),
            'categories': post_data.pop('categories', []),
            'status': current_status,  # Use the validated status
            'title': post_data.pop('title', None), # Preserve title
            'content': post_data.pop('content', None), # Preserve content
            'processed_images': post_data.pop('processed_images', []), # Preserve images
            'image_results': post_data.pop('image_results', {}), # Preserve image results
            'blog_plan': post_data.pop('blog_plan', {}), # Preserve blog plan
            'task_status': post_data.pop('task_status', None)  # Remove task_status from final payload
        }
        
        logger.info(f"DEBUG prepare_payload: Preserved categories = {preserved_fields.get('categories')}")
        logger.info(f"DEBUG prepare_payload: Preserved category = {preserved_fields.get('category')}")
        logger.info(f"DEBUG prepare_payload: Preserved available_categories = {preserved_fields.get('available_categories')}")
        
        post_data = remove_none(post_data)
        
        # Add back preserved fields if they exist
        for field, value in preserved_fields.items():
            if value is not None and value != '':
                post_data[field] = value
        
        # Ensure we have at least one category
        if not post_data.get('categories') and post_data.get('category'):
            post_data['categories'] = [post_data['category']]
            
        # Inject images into content if available
        # Check for processed_images in preserved fields
        processed_images = preserved_fields.get('processed_images', [])
        if not processed_images and preserved_fields.get('image_results'):
            processed_images = preserved_fields['image_results'].get('processed_images', [])
            
        # Also check if we have a blog_plan with processed_images
        if not processed_images and preserved_fields.get('blog_plan'):
            processed_images = preserved_fields['blog_plan'].get('processed_images', [])
            
        content = post_data.get('content')
        if processed_images and content:
            logger.info(f"Injecting {len(processed_images)} images into content in prepare_payload")
            post_data['content'] = inject_images_into_content(content, processed_images)
        elif processed_images:
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

