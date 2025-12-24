import asyncio
import logging
import re
import json
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List

from celery import shared_task, signature, group, chord
from celery.utils.log import get_task_logger
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.utils.text import slugify
import requests

from .models import BlogPostPayload, BlogPlan

logger = get_task_logger(__name__)

def generate_slug(title: str) -> str:
    """Generate a URL-friendly slug from a title string."""
    if not title:
        raise ValueError("Title cannot be empty")
    slug = title.lower().strip()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug)
    slug = re.sub(r'[\s-]+', '-', slug)
    slug = slug.strip('-')
    return slug

def inject_backlinks_into_content(content: str, scraped_data: list, keyword: str) -> str:
    """Inject natural-looking backlinks into the content."""
    if not content or not scraped_data:
        return content
    
    import html
    try:
        # Step 1: Extract high-quality links from scraped data
        links = []
        seen_urls = set()
        
        for item in scraped_data:
            url = None
            anchor = None
            
            if isinstance(item, dict):
                url = item.get('url') or item.get('link') or item.get('source_url')
                anchor = item.get('title') or item.get('name') or item.get('anchor')
                # Fallback for anchor if missing
                if not anchor:
                    snippet = item.get('snippet') or item.get('content', '')
                    if snippet:
                        words = [w for w in str(snippet).split() if len(w) > 2]
                        anchor = ' '.join(words[:6]).strip('., ')
            elif isinstance(item, str):
                url = item
                anchor = f"Read more about {keyword}"
            
            if not url or not isinstance(url, str) or not url.startswith('http'):
                continue
                
            if url in seen_urls:
                continue
            
            if not anchor or len(str(anchor)) < 5:
                anchor = f"Related article on {keyword}"
                
            links.append({'url': url, 'anchor': str(anchor)})
            seen_urls.add(url)
            
            if len(links) >= 5:
                break

        if not links:
            return content

        # Step 2: Determine injection count (min 2, max 3 as requested)
        # Split by paragraphs and clean up
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        num_p = len(paragraphs)
        
        if num_p < 2:
            # If only one big block, try splitting by single newlines
            paragraphs = [p.strip() for p in content.split('\n') if p.strip()]
            num_p = len(paragraphs)

        target_count = 3 if num_p >= 6 else 2
        target_count = min(target_count, len(links))
        
        if target_count < 1:
            return content

        # Step 3: Inject naturally between paragraphs
        # We'll space them out starting after the first paragraph
        for i in range(target_count):
            # Calculate position: skip first paragraph, then space out
            if num_p > target_count:
                pos = 1 + (i * (num_p - 1)) // target_count
            else:
                pos = num_p # Just append if not enough paragraphs
                
            link = links[i]
            safe_url = html.escape(link['url'])
            safe_anchor = html.escape(link['anchor'])
            
            # Create a natural "Related" style block
            prefix = "Related:" if i % 2 == 0 else "Read also:"
            backlink_html = f'<p><strong>{prefix}</strong> <a href="{safe_url}" target="_blank" rel="noopener nofollow">{safe_anchor}</a></p>'
            
            # Insert into paragraphs list (adjusting for previous insertions)
            paragraphs.insert(min(pos + i, len(paragraphs)), backlink_html)

        return '\n\n'.join(paragraphs)
        
    except Exception as e:
        logger.error(f"Error injecting backlinks: {str(e)}", exc_info=True)
        return content

def inject_video_into_content(content: str, video_link: str) -> str:
    """Inject video HTML before the last heading in the content."""
    if not content or not video_link:
        return content
    
    try:
        # Split content on headings while keeping them
        parts = re.split(r'(<h[1-6][^>]*>.*?</h[1-6]>)', content, flags=re.IGNORECASE | re.DOTALL)
        logger.info(f"Video Link: {video_link}")
        if len(parts) < 2:  # No headings found
            return content
            
        # Find the last heading's position
        last_heading_idx = len(parts) - 2  # Last heading is at second-to-last position
        while last_heading_idx >= 0 and not parts[last_heading_idx].startswith('<h'):
            last_heading_idx -= 1
            
        if last_heading_idx < 0:  # No valid heading found
            return content
            
        # Create video HTML
        video_html = f'''
        <div class="video-container" style="margin: 20px 0; text-align: center;">
            <iframe width="560" height="315" 
                    src="{video_link}" 
                    frameborder="0" 
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
                    allowfullscreen>
            </iframe>
        </div>
        '''
        
        # Insert video before the last heading
        parts.insert(last_heading_idx, video_html)
        return ''.join(parts)
        
    except Exception as e:
        logger.error(f"Error injecting video: {str(e)}")
        return content
        
def inject_images_into_content(content: str, images: list) -> str:
    """Inject images into the HTML content."""
    if not content or not images:
        return content
    try:
        parts = re.split(r'(<h[1-6][^>]*>.*?</h[1-6]>)', content, flags=re.IGNORECASE | re.DOTALL)
        new_content = []
        heading_count = 0
        for i, part in enumerate(parts):
            new_content.append(part)
            if i % 2 == 1:
                heading_count += 1
                if heading_count == 15 and len(images) > 1:
                    img_url = images[1]
                    new_content.append(f'\n<figure class="wp-block-image"><img src="{img_url}" alt="Blog Image" /></figure>\n')
        return "".join(new_content)
    except Exception as e:
        logger.error(f"Error injecting images: {str(e)}")
        return content

@shared_task(bind=True, name='autopublish.content.tasks.prepare_payload')
def prepare_payload(self, *args, **kwargs):
    """Prepare and validate the payload for blog post creation."""
    try:
        task_id = getattr(self.request, 'id', 'unknown')
        post_data = args[0] if args and isinstance(args[0], dict) else kwargs.get('post_data', {})
        # Process post data
        if isinstance(post_data, str):
            post_data = json.loads(post_data) if post_data.strip() else {}
        
        # Prepare category info
        category = post_data.get('category', {})
        category_id = category.get('id') if isinstance(category, dict) else int(category) if str(category).isdigit() else None
        category_name = category.get('name') if isinstance(category, dict) else str(category) if not str(category).isdigit() else 'Uncategorized'
        
        # Prepare final data
        video_link = post_data.get('video_link') or kwargs.get('video_link', '')
        logger.info(f"Video Link in prepare_payload: {video_link}")
        
        final_data = {
            'title': post_data.get('title', 'Untitled Post'),
            'content': post_data.get('content', ''),
            'excerpt': post_data.get('excerpt', ''),
            'featured_image': post_data.get('featured_image'),
            'category_id': category_id or 1,
            'category_name': category_name or 'Uncategorized',
            'video_link': video_link,
            'status': post_data.get('status', 'publish'),
            'language': post_data.get('language', 'en'),
            'domain_link': kwargs.get('domain_link') or post_data.get('domain_link', ''),
            'image_urls': post_data.get('image_urls', []),
            'scraped_data': post_data.get('scraped_data', [])
        }
        
        # Process content
        content = final_data['content']
        if content:
            if final_data['image_urls']:
                content = inject_images_into_content(content, final_data['image_urls'])
            if final_data['video_link']:
                content = inject_video_into_content(content, final_data['video_link'])
            if final_data.get('scraped_data'):
                content = inject_backlinks_into_content(content, final_data['scraped_data'], final_data['title'])
            final_data['content'] = content

        return {
            'status': 'success',
            'task_id': task_id,
            'data': final_data
        }

    except Exception as e:
        logger.error(f"Error in prepare_payload: {str(e)}")
        return {
            'status': 'error',
            'message': str(e),
            'task_id': getattr(self, 'request', {}).get('id', 'unknown')
        }
        
@shared_task(bind=True, name="autopublish.content.tasks.process_keyword_task")
def process_keyword_task(self, request_body):
    """Main task to orchestrate keyword content generation."""
    try:
        if isinstance(request_body, str): 
            request_body = json.loads(request_body)
        tasks = []
        for keyword_data in request_body.get('keywords', []):
            keyword = keyword_data['text']
            scheduled_time = keyword_data.get('scheduled_time')
            language = request_body.get('language', 'en')
            country = request_body.get('country', 'us')
            available_categories = request_body.get('available_categories', [])
            min_words = request_body.get('min_words', 2000)
            logger.info(f"ℹ️ Available categories: {min_words}")
            task_chain = (
                signature('autopublish.content.tasks.fetch_keyword_content_prereqs',
                    kwargs={'keyword': keyword, 'language': language, 'country': country, 'available_categories': available_categories, 'scheduled_time': scheduled_time}
                ) | 
                chord([
                    signature('autopublish.content_generator.tasks.get_blog_plan',
                        kwargs={'keyword': keyword, 'language': language, 'country': country, 'available_categories': available_categories}, immutable=True),
                    signature('autopublish.scraper.tasks.process_scraping_task',
                        kwargs={'keyword': keyword, 'language': language, 'country': country, 'max_results': 5}, immutable=True),
                    signature('autopublish.scraper.tasks.process_and_save_images',
                        kwargs={'query': keyword, 'max_results': 5, 'language': language, 'country': country}, immutable=True)
                ],
                signature('autopublish.content.tasks.process_parallel_results',
                    kwargs={
                        'keyword': keyword, 
                        'language': language, 
                        'country': country, 
                        'video_link': request_body.get('video_link'),
                        'available_categories': available_categories, 
                        'scheduled_time': scheduled_time,
                        'min_words': min_words
                    }
                )) |
                signature('autopublish.content_generator.tasks.generate_keyword_content', 
                    kwargs={
                        'target_word_count': min_words,
                        'min_words': min_words  # Pass it again to be safe
                    }) |
                signature('autopublish.content.tasks.prepare_payload',
                    kwargs={'user_email': request_body.get('user_email'), 'domain_link': request_body.get('domain_link'), 'video_link': request_body.get('video_link')}) |
                signature('autopublish.content.tasks.save_blog_post',
                    kwargs={'user_email': request_body.get('user_email'), 'status': 'publish', 'scheduled_time': scheduled_time})
            )
            tasks.append(task_chain)
        group(tasks).apply_async()
    except Exception as e:
        logger.error(f"Error in process_keyword_task: {str(e)}", exc_info=True)

@shared_task(bind=True, name="autopublish.content.tasks.fetch_keyword_content_prereqs")
def fetch_keyword_content_prereqs(self, keyword: str, language: str = "en", country: str = "us", available_categories: list = None, scheduled_time: str = None):
    """Prepare prerequisites for keyword content."""
    try:
        blog_plan_record = BlogPlan.objects.create(
            keyword=keyword, language=language, country=country,
            available_categories=available_categories or [], status='processing'
        )
        return {
            'keyword': keyword, 'language': language, 'country': country,
            'plan_id': str(blog_plan_record.id), 'available_categories': available_categories,
            'scheduled_time': scheduled_time
        }
    except Exception as e:
        raise self.retry(exc=e, countdown=60)

@shared_task(bind=True, name='autopublish.content.tasks.process_parallel_results')
def process_parallel_results(self, results, **kwargs):
    """Process parallel task results."""
    try:
        keyword = kwargs.get('keyword', '')
        available_categories = kwargs.get('available_categories', [])
        
        blog_plan_result = results[0] if len(results) > 0 else {}
        scraped_data_result = results[1] if len(results) > 1 else {}
        images_result = results[2] if len(results) > 2 else {}
        
        blog_plan_data = blog_plan_result.get('data', blog_plan_result)
        scraped_data_info = scraped_data_result.get('data', scraped_data_result)
        selected_category = blog_plan_data.get('category', 'Uncategorized')
        
        # Simple category matching
        category_id = '1'
        category_name = 'Uncategorized'
        if available_categories and len(available_categories) == 2:
            names, mapping = available_categories
            if selected_category in mapping:
                category_name = selected_category
                category_id = mapping[selected_category]
        
        processed_images = images_result.get('processed_images', [])
        
        return {
            'keyword': keyword,
            'language': kwargs.get('language', 'en'),
            'country': kwargs.get('country', 'us'),
            'blog_plan': blog_plan_data,
            'category': {'name': category_name, 'id': category_id},
            'image_urls': processed_images,
            'scraped_data': scraped_data_info.get('results', []),
            'video_link': scraped_data_info.get('video_link', ''),
            'available_categories': available_categories,
            'scheduled_time': kwargs.get('scheduled_time'),
            'min_words': kwargs.get('min_words', 2000),  # Forward min_words with default 2000
            'target_word_count': kwargs.get('min_words', 2000)  # Also include as target_word_count for compatibility
        }
    except Exception as e:
        logger.error(f"Error in process_parallel_results: {str(e)}")
        raise

@shared_task(bind=True, name="autopublish.content.tasks.save_blog_post")
def save_blog_post(self, payload, user_email=None, status='draft', scheduled_time=None):
    """Save post to database with proper metadata."""
    try:
        # Extract payload data
        if isinstance(payload, dict) and 'data' in payload: 
            payload = payload['data']
        
        title = payload.get('title', 'Untitled Post')
        content = payload.get('content', '')
        meta_description = payload.get('meta_description', '')
        focus_keyword = payload.get('focus_keyword', '')
        
        # Set meta_keywords to focus_keyword if not already set
        meta_keywords = payload.get('meta_keywords', focus_keyword)
        
        # Parse scheduled time
        scheduled_at = None
        if scheduled_time or payload.get('scheduled_time'):
            st = scheduled_time or payload.get('scheduled_time')
            try:
                if isinstance(st, str):
                    scheduled_at = datetime.fromisoformat(st.replace('Z', '+00:00'))
                elif isinstance(st, datetime):
                    scheduled_at = st
            except Exception as e:
                logger.warning(f"Failed to parse scheduled_time: {st}, error: {e}")
        
        # Determine status - ONLY draft or scheduled (never publishing)
        post_status = 'scheduled' if scheduled_at else 'draft'
        
        # Extract and clean category ID
        category_id = None
        if payload.get('category_id'):
            try:
                category_id = int(payload['category_id'])
            except (ValueError, TypeError):
                logger.warning(f"Invalid category_id: {payload.get('category_id')}")
        elif payload.get('category'):
            # Handle category dict or string
            cat = payload['category']
            if isinstance(cat, dict):
                try:
                    category_id = int(cat.get('id'))
                except (ValueError, TypeError):
                    logger.warning(f"Invalid category id in dict: {cat.get('id')}")
            elif isinstance(cat, (int, str)):
                try:
                    category_id = int(cat)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid category value: {cat}")
        
        # Get domain_link (canonical_url)
        domain_link = payload.get('domain_link') or payload.get('canonical_url')
        
        # Extract featured image (first image from image_urls)
        featured_image = None
        if payload.get('featured_image'):
            featured_image = payload['featured_image']
        elif payload.get('image_urls') and len(payload['image_urls']) > 0:
            # Get first image from image_urls array
            featured_image = payload['image_urls'][0]
        
        # Create/update post with ALL metadata
        post, created = BlogPostPayload.objects.update_or_create(
            title=title,
            defaults={
                # Core content
                'content': content,
                'excerpt': meta_description[:300] if meta_description else '',  # Use meta_description as excerpt
                'slug': payload.get('slug', slugify(title)),
                'status': post_status,
                
                # Timestamps
                'scheduled_at': scheduled_at,
                
                # Author/Profile
                'author_id': 1,  # Default author
                
                # SEO fields
                'meta_title': title,  # Use title as meta_title
                'meta_description': meta_description,
                'meta_keywords': meta_keywords,  # Save the meta_keywords
                'og_title': payload.get('og_title', title),
                'og_description': payload.get('og_description', meta_description),
                'twitter_title': payload.get('twitter_title', title),
                'twitter_description': payload.get('twitter_description', meta_description),
                'word_count': len(content.split()) if content else 0,
                'focus_keyword': focus_keyword,
                'meta_image': payload.get('featured_image'),
                'language': payload.get('language', 'en') or payload.get('source_url'),
                'source_name': payload.get('source') or payload.get('source_name'),
                'canonical_url': domain_link,  # Properly save domain_link
                
                # Source tracking (for news posts)
                'source_url': payload.get('original_url') or payload.get('source_url'),
            }
        )
        
        # Set categories as a clean list with single category ID
        if category_id:
            post.categories = [category_id]
            post.save(update_fields=['categories'])
        
        logger.info(f"✅ Saved post: {title} (ID: {post.id}, Status: {post_status}, Category: {category_id})")
        
        return {'success': True, 'post_id': post.id, 'status': post_status}
        
    except Exception as e:
        logger.error(f"Error in save_blog_post: {str(e)}", exc_info=True)
        raise self.retry(exc=e, countdown=60)

@shared_task(bind=True, name="autopublish.content.tasks.save_to_wp")
def save_to_wp(self, post_id, status='publish'):
    """Publish to WordPress."""
    try:
        post = BlogPostPayload.objects.get(id=post_id)
        post.status = 'publishing'
        post.save()
        
        domain_link = post.canonical_url
        if not domain_link: 
            raise ValueError("No domain link")
        if not domain_link.startswith('http'): 
            domain_link = f'https://{domain_link}'
        
        api_url = f'{domain_link.rstrip("/")}/wp-json/thirdparty/v1/create-post'
        wp_payload = {
            'title': post.title,
            'content': post.content,
            'status': status,
            'categories': post.categories,
            'slug': post.slug,
            'featured_image': post.meta_image  # Include featured image URL
        }
        response = requests.post(api_url, json=wp_payload, timeout=30)
        if response.status_code == 200:
            post.status = 'published'
            post.published_at = timezone.now()
            post.save()
            return {'success': True}
        else:
            raise Exception(f"WP Error: {response.text}")
    except Exception as e:
        raise self.retry(exc=e, countdown=60)

@shared_task(bind=True, name="autopublish.content.tasks.publish_scheduled_posts")
def publish_scheduled_posts(self):
    """Beat task to publish scheduled posts."""
    now = timezone.now()
    posts = BlogPostPayload.objects.filter(status='scheduled', scheduled_at__lte=now)
    for post in posts:
        save_to_wp.delay(post.id)
    return {'count': posts.count()}

@shared_task(bind=True, name='autopublish.content.tasks.process_blog_plan_scraped_data_and_images')
def process_blog_plan_scraped_data_and_images(self, results, **kwargs):
    """Process the results from blog plan generation, keyword scraping, and image processing."""
    try:
        logger.info("Processing blog plan, scraped data, and images")
        if not results or len(results) != 2:
            raise ValueError(f"Expected 2 results, got {len(results) if results else 0}")
        
        blog_plan_data = results[0]
        images_data = results[1]
        
        if isinstance(blog_plan_data, dict):
            processed_images = images_data.get('processed_images', [])
            blog_plan_data['processed_images'] = processed_images
            blog_plan_data['image_urls'] = processed_images
            if processed_images:
                blog_plan_data['featured_image'] = processed_images[0]
        
        return blog_plan_data
    except Exception as e:
        logger.error(f"Error in process_blog_plan_scraped_data_and_images: {str(e)}")
        return results[0] if results else {}

@shared_task(bind=True, name="autopublish.content.tasks.process_scheduled_posts")
def process_scheduled_posts(self):
    """Celery beat task to process scheduled posts."""
    logger.info("⏰ Starting scheduled posts processing...")
    
    try:
        now = timezone.now()
        scheduled_posts = BlogPostPayload.objects.filter(
            status='scheduled',
            scheduled_at__lte=now
        )
        
        logger.info(f"Found {scheduled_posts.count()} posts to process")
        scheduled_count = 0
        
        for post in scheduled_posts:
            try:
                logger.info(f"📤 Scheduling post {post.id} ({post.title}) for WordPress publishing")
                save_to_wp.apply_async(
                    args=[post.id],
                    kwargs={'status': 'publish'}
                )
                scheduled_count += 1
                logger.info(f"✅ Successfully scheduled post {post.id} for publishing")
            except Exception as e:
                logger.error(f"❌ Error scheduling post {post.id}: {str(e)}", exc_info=True)
                post.status = 'failed'
                post.last_error = str(e)
                post.save(update_fields=['status', 'last_error'])
                
        logger.info(f"✅ Finished scheduling {scheduled_count} posts for publishing")
        return {"scheduled": scheduled_count, "status": "completed"}
    except Exception as e:
        logger.error(f"❌ Error in process_scheduled_posts: {str(e)}", exc_info=True)
        raise


@shared_task(bind=True, name="autopublish.content.tasks.process_news_task")
def process_news_task(self, request_body):
    """
    Celery task to process news asynchronously.
    Uses scrape_news_task to fetch news and then processes it.
    """
    logger.info(f"[TASK] Starting process_news_task with data: {request_body}")
    
    try:
        # Parse request body
        if isinstance(request_body, str):
            try:
                data = json.loads(request_body)
            except json.JSONDecodeError as e:
                return {"success": False, "error": f"Invalid JSON format: {str(e)}"}
        else:
            data = dict(request_body) if hasattr(request_body, 'items') else request_body

        categories = data.get('categories', [])
        language = data.get('language', 'en')
        country = data.get('country', 'us')
        vendor = data.get('vendor', 'google')
        times = data.get('times', [])
        target_path_from_request = data.get('target_path')
        domain_link = data.get('domain_link')
        logger.info(f"[DEBUG] Domain Link: {domain_link}")
        logger.info(f"[DEBUG] Categories Input: {categories}")

        # Prepare categories for scraping
        processed_categories = []
        for items in categories:
            # Handle if items is just a string (category name)
            if isinstance(items, str):
                processed_categories.append({
                    'name': items,
                    'num': 2
                })
            elif isinstance(items, dict):
                processed_categories.append({
                    'name': items.get('name', 'business'),
                    'num': items.get('num', 2)
                })
            
        logger.info(f"[DEBUG] Calling scrape_news_task with categories: {processed_categories}")
        
        # Import scraper task
        from scraper.tasks import scrape_news_task
        
        scraped_data_content = scrape_news_task(
            categories=processed_categories,
            country=country,
            language=language,
            vendor=vendor
        )
        
        logger.info(f"[DEBUG] Scraped data received: {json.dumps(scraped_data_content, indent=2)}")
        
        # Handle response format
        if 'categories' in scraped_data_content:
            categories_data = scraped_data_content['categories']
        else:
            categories_data = scraped_data_content

        results = []
        
        # Process each category
        for item in categories:
            # Normalize item to dict
            if isinstance(item, str):
                item = {'name': item, 'id': None}
                
            category_name = item.get("name")
            if not category_name or category_name not in categories_data:
                logger.warning(f"Category '{category_name}' not found in response. Available: {list(categories_data.keys())}")
                continue
                
            category_specific_scraped = categories_data[category_name]
            index = 0
            category_times = item.get("times", [])
            
            # Create an async loop for any async calls if needed (though we use celery sync calls mostly)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                for category_item in category_specific_scraped:
                    source = category_item.get('source', {})
                    source_name = source.get('name', '') if isinstance(source, dict) else source
                    
                    # Debug: Log the scraped article data
                    logger.info(f"🔍 Processing article: {category_item.get('title')}")
                    logger.info(f"🔍 Article has content: {bool(category_item.get('content'))}")
                    logger.info(f"🔍 Content length: {len(category_item.get('content', ''))} chars")
                    
                    # Prepare data for rephrasing
                    prompt_data = {
                        'title': category_item.get('title'),
                        'content': category_item.get('content'),
                        'category': categories,
                        'tone': 'professional',
                        'source': source_name,
                        'image_links': category_item.get('image_links', ''),
                        'backlinks': category_item.get('backlinks', ''),
                        'video_links': category_item.get('video_links', ''),
                        'language': language
                    }
                    
                    logger.info(f"📤 Sending to rephrase task - Title: {prompt_data['title']}, Content length: {len(prompt_data.get('content', ''))}")
                    
                    # Import tasks
                    from celery import group
                    from scraper.tasks import process_and_save_images
                    from content_generator.tasks import rephrase_content_task
                    
                    # 1. Parallel Execution: Image Generation & Content Rephrasing
                    logger.info(f"Starting parallel tasks for article: {category_item.get('title')}")
                    
                    image_task = process_and_save_images.s(
                        query=category_item.get('title'),
                        max_results=3,
                        language=language,
                        country=country
                    )
                    
                    rephrase_task = rephrase_content_task.s(prompt_data)
                    
                    workflow = group(image_task, rephrase_task)
                    
                    # Use allow_join_result to safely wait for results
                    from celery.result import allow_join_result
                    
                    with allow_join_result():
                        results_list = workflow.apply_async().get()
                    
                    image_result = results_list[0]
                    rephrased_result = results_list[1]
                    
                    # Debug logging for rephrased result
                    logger.info(f"📝 Rephrased result for '{category_item.get('title')}': {rephrased_result}")
                    
                    if not rephrased_result or rephrased_result.get('status') == 'error':
                        logger.error(f"❌ Rephrasing failed for article: {category_item.get('title')}")
                        logger.error(f"❌ Rephrased result: {rephrased_result}")
                        logger.error(f"❌ Error details: {rephrased_result.get('error') if rephrased_result else 'No result returned'}")
                        continue

                    # 2. Prepare Payload for process_blog_plan_scraped_data_and_images
                    # We map the rephrased result to what looks like a 'blog_plan'
                    # Use the category ID from the item if available, otherwise fall back to name
                    category_id = item.get('id')
                    # Ensure category_id is a valid integer string or None
                    if category_id:
                        try:
                            int(category_id) # Check if it's convertible to int
                            category_id = str(category_id)
                        except (ValueError, TypeError):
                            logger.warning(f"Invalid category ID in input: {category_id}, ignoring.")
                            category_id = None
                    
                    payload_base = {
                        'title': rephrased_result.get('title'),
                        'content': rephrased_result.get('rephrased_content'),
                        'categories': [category_id] if category_id else [],
                        'category': category_id,
                        'status': 'publish',  # Will be changed to 'scheduled' later
                        'language': language,
                        'meta_description': rephrased_result.get('rephrased_content', '')[:160],
                        # Pass through other metadata
                        'original_url': category_item.get('url'),
                        'source': source_name,
                        'image_urls': rephrased_result.get('image_urls', []),
                        'domain_link': domain_link,
                        'scraped_data': category_specific_scraped
                    }
                    
                    # 3. Combine Data (Images + Content)
                    # process_blog_plan_scraped_data_and_images expects [blog_plan_data, images_data]
                    # We call it synchronously (it's a task, but we can execute the function if we import it, 
                    # but here we use apply() to keep it as a task call)
                    with allow_join_result():
                        combined_payload = process_blog_plan_scraped_data_and_images.apply(
                            args=[[payload_base, image_result]]
                        ).get()
                    
                    # 4. Prepare Payload (Inject Images)
                    # This ensures images are injected into the content, just like in keyword workflow
                    with allow_join_result():
                        prepared_payload = prepare_payload.apply(
                            args=[combined_payload],
                            kwargs={
                                'user_email': data.get('user_email'),
                                'domain_link': domain_link
                            }
                        ).get()
                    
                    # 5. Save to database for scheduled publishing
                    
                    # Add scheduled time (immediate or scheduled)
                    if index < len(category_times):
                        scheduled_time_str = category_times[index]
                        try:
                            # Parse ISO format string to datetime
                            scheduled_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
                        except ValueError:
                            logger.warning(f"Invalid time format: {scheduled_time_str}, using current time")
                            scheduled_time = datetime.utcnow()
                    else:
                        scheduled_time = datetime.utcnow()
                    
                    # Save the article to database
                    with allow_join_result():
                        save_result = save_blog_post.apply(
                            args=[prepared_payload],
                            kwargs={
                                'status': 'scheduled',  # Will be published by the beat task
                                'scheduled_time': scheduled_time.isoformat()
                            }
                        ).get()
                    
                    # Add to results list
                    article_data = {
                        'title': payload_base['title'],
                        'url': category_item.get('url'),
                        'post_id': save_result.get('post_id'),
                        'status': 'scheduled',
                        'scheduled_at': scheduled_time.isoformat(),
                        'publish_status': 'scheduled'  # Will be updated by the scheduled task
                    }
                    results.append(article_data)
                    index += 1
                    
            finally:
                loop.close()

        return {
            'status': 'ok',
            'categories': categories,
            'language': language,
            'country': country,
            'vendor': vendor,
            'times': times,
            'results': results
        }

    except Exception as e:
        error_msg = f"Error in process_news_task: {str(e)}\n{traceback.format_exc()}"
        logger.error(f"[TASK] {error_msg}")
        return {"success": False, "error": error_msg}
