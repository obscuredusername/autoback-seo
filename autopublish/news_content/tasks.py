import os
import sys
import traceback
import json
import asyncio
from datetime import datetime
from celery import Celery
from celery.utils.log import get_task_logger
from django.apps import apps
from django.utils.text import slugify

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'autopublish.settings')

# Get the Celery app from the Django project
from autopublish.celery import app

# Set up logging
logger = get_task_logger(__name__)

# Import the new scraper task
from scraper.tasks import scrape_news_task
from content_generator.views import rephrase_news_content


@app.task(bind=True, name="process_news_task")
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

        # Prepare categories for scraping
        processed_categories = []
        for items in categories:
            processed_categories.append({
                'name': items.get('name', 'business'),
                'num': items.get('num', 2)
            })
            
        logger.info(f"[DEBUG] Calling scrape_news_task with categories: {processed_categories}")
        
        # Call the scraper task synchronously since we are already in a task
        # We use the task function directly or via apply(). 
        # Since scrape_news_task is a shared_task, we can call it.
        # However, scrape_news_task returns a dict, so we can just use it.
        
        # Note: scrape_news_task is an async wrapper around the view. 
        # We can call it using .apply() to execute it in the current process if needed, 
        # or just call the function if it wasn't a celery task. 
        # Since it is a celery task, let's use .apply() to run it synchronously here 
        # or .delay() and wait for result (but waiting in a task is bad practice).
        # Better yet, let's just use the logic the user asked for:
        
        # The user asked to "call the task by sending the proper request format".
        # And they provided code that uses NewsByCategoryView directly via RequestFactory.
        # But I created scrape_news_task in scraper/tasks.py which does exactly that.
        # So I will call that task.
        
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
            category_name = item["name"]
            if category_name not in categories_data:
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
                    
                    # Import tasks
                    from celery import group
                    from scraper.tasks import process_and_save_images
                    from content_generator.tasks import rephrase_content_task
                    from keyword_content.tasks import process_blog_plan_scraped_data_and_images, save_blog_post
                    
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
                    
                    if not rephrased_result or rephrased_result.get('status') == 'error':
                        logger.error(f"Rephrasing failed for article: {category_item.get('title')}")
                        continue

                    # 2. Prepare Payload for process_blog_plan_scraped_data_and_images
                    # We map the rephrased result to what looks like a 'blog_plan'
                    # Use the category ID from the item if available, otherwise fall back to name
                    category_id = item.get('id', item['name'])
                    payload_base = {
                        'title': rephrased_result.get('title'),
                        'content': rephrased_result.get('rephrased_content'),
                        'categories': [category_id],
                        'category': str(category_id),  # Ensure it's a string for consistency
                        'status': 'publish',  # Will be changed to 'scheduled' later
                        'language': language,
                        'meta_description': rephrased_result.get('rephrased_content', '')[:160],
                        # Pass through other metadata
                        'original_url': category_item.get('url'),
                        'source': source_name,
                        'image_urls': rephrased_result.get('image_urls', []),
                        'domain_link': domain_link
                    }
                    
                    # 3. Combine Data (Images + Content)
                    # process_blog_plan_scraped_data_and_images expects [blog_plan_data, images_data]
                    # We call it synchronously (it's a task, but we can execute the function if we import it, 
                    # but here we use apply() to keep it as a task call)
                    with allow_join_result():
                        combined_payload = process_blog_plan_scraped_data_and_images.apply(
                            args=[[payload_base, image_result]]
                        ).get()
                    
                    # 4. Save to database for scheduled publishing
                    from keyword_content.tasks import save_blog_post
                    
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
                            args=[combined_payload],
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