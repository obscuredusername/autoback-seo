import json
import traceback
from django.http import HttpRequest
from celery.utils.log import get_task_logger
from asgiref.sync import sync_to_async
from .content_utils import get_target_path
from bson import ObjectId
from django.utils import timezone
from scraper.views import NewsByCategoryView
from content_generator.views import rephrase_news_content
# Initialize logger
logger = get_task_logger(__name__)

import asyncio
from datetime import timedelta, datetime
from django.utils import timezone
from django.utils.timezone import make_aware, get_current_timezone as django_timezone
from django.apps import apps
from django.utils.text import slugify
from django.db import transaction
from .content_utils import get_target_path
from bson import ObjectId

class CeleryNews:
    def __init__(self, request_body, request=None):
        self.logger = logger
        self.request = request
        self.raw_request_body = request_body
        self.data = None
        self.categories = None
        self.language = None
        self.country = None
        self.vendor = None
        self.times = None
        self.error = None
        self._parse_request()

    def _parse_request(self):
        try:
            if isinstance(self.raw_request_body, str):
                try:
                    self.data = json.loads(self.raw_request_body)
                    if not isinstance(self.data, dict):
                        raise ValueError("Parsed JSON is not a dictionary")
                except json.JSONDecodeError as e:
                    self.error = f"Invalid JSON format: {str(e)}"
                    self.data = None
            else:
                self.data = dict(self.raw_request_body) if hasattr(self.raw_request_body, 'items') else self.raw_request_body
                if not isinstance(self.data, dict):
                    self.error = 'Request body must be a JSON object'
                    self.data = None
            if self.data:
                self.categories = self.data.get('categories')
                self.language = self.data.get('language', 'en')
                self.country = self.data.get('country', 'us')
                self.vendor = self.data.get('vendor', 'google')
                self.times = self.data.get('times', [])
        except Exception as e:
            self.error = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
            self.data = None

    async def process(self):
        self.logger.info(f"[DEBUG] CeleryNews.process - Raw request body: {self.raw_request_body}")
        if self.error:
            self.logger.error(self.error)
            return {
                'status': 'error',
                'error': self.error,
                'count': 0,
                'articles_processed': 0,
                'results': []
            }
        processed_categories = []
        for items in self.categories:
            processed_categories.append({
                'name': items.get('name', 'business'),
                'num': items.get('num', 2)
            })
        request_data = {
                'categories': processed_categories,
                'country': self.country,
                'language': self.language,  # Always scrape in English
                'vendor': self.vendor,
                'target_language': self.language,
            }
        scrape_news = NewsByCategoryView()
        self.logger.info(f"[DEBUG] CeleryNews.process - Prepared request data: {json.dumps(request_data, indent=2)}")
        try:
            from django.test import RequestFactory
            factory = RequestFactory()
            fake_request = factory.post(
                '/scraper/news/category/',
                data=json.dumps(request_data),
                content_type='application/json'
            )
            scraped_data = await scrape_news.post(fake_request)
            # Handle JsonResponse or dict
            if hasattr(scraped_data, 'data'):
                scraped_data_content = scraped_data.data
            elif hasattr(scraped_data, 'content'):
                scraped_data_content = json.loads(scraped_data.content.decode('utf-8'))
            else:
                scraped_data_content = scraped_data
            self.logger.info(f"[DEBUG] CeleryNews.process - Scraped data: {json.dumps(scraped_data_content, indent=2)}")
            logger.info(f"[DEBUG] CeleryNews.process - Categories: {self.categories}")
            
            # Handle both old and new response formats
            if 'categories' in scraped_data_content:
                # New format: {'categories': {'entertainment': [...], ...}}
                categories_data = scraped_data_content['categories']
            else:
                # Old format: {'entertainment': [...], ...}
                categories_data = scraped_data_content
                
            for item in self.categories:
                category_name = item["name"]
                if category_name not in categories_data:
                    self.logger.warning(f"Category '{category_name}' not found in response. Available categories: {list(categories_data.keys())}")
                    continue
                    
                category_specific_scraped = categories_data[category_name]
                index = 0
                times = item.get("times", [])
                logger.info(f"[DEBUG] CeleryNews.process - category_specific_scraped: {json.dumps(category_specific_scraped, indent=2)}")
                for category_item in category_specific_scraped:
                   source = category_item.get('source', {})
                   if isinstance(source, dict):
                       source_name = source.get('name', '')
                   else:
                       source_name = source
                   article_data = {
                       'url': category_item.get('url'),
                       'published_at': category_item.get('publishedAt'),
                       'source': source_name,
                       'categoryId': item.get('id', None),
                       'scheduledAt': times[index] if index < len(times) else None,
                       'category': item["name"],
                       'language': self.language,
                       'country': self.country,
                       'vendor': self.vendor,
                   }
                   prompt_data = {
                        'title': category_item.get('title'),
                        'content': category_item.get('content'),
                        'category': self.categories,
                        'tone': 'professional',
                        'source': source_name,
                        'image_links': category_item.get('image_links', ''),
                        'backlinks': category_item.get('backlinks', ''),
                        'video_links': category_item.get('video_links', ''),      # For backward compatibility
                    }
                   rephrased = await rephrase_news_content(prompt_data)
                   article_data['content'] = rephrased['rephrased_content']
                   article_data['title'] = rephrased['title']
                   article_data['image_links'] = rephrased.get('image_links', '')
                   
                   try:
                       # Lazy load models to avoid AppRegistryNotReady
                       NewsPost = apps.get_model('news_content', 'NewsPost')
                       NewsCategory = apps.get_model('news_content', 'NewsCategory')
                       
                       # Generate slug from title
                       base_slug = slugify(rephrased['title'])
                       slug = base_slug
                       counter = 1
                       
                       # Check if slug exists and find a unique one
                       while await sync_to_async(NewsPost.objects.filter(slug=slug).exists)():
                           slug = f"{base_slug}-{counter}"
                           counter += 1
                       
                       # Get or create category
                       category, _ = await sync_to_async(NewsCategory.objects.get_or_create)(
                           name=item["name"],
                           defaults={'slug': slugify(item["name"])}
                       )
                       
                       # Create news post
                       news_post = NewsPost(
                           title=article_data['title'],
                           content=article_data['content'],
                           excerpt=article_data['content'][:200] + '...',
                           slug=slug,
                           status='scheduled',
                           publishedAt=None,
                           scheduledAt=datetime.fromisoformat(article_data['scheduledAt'].replace('Z', '+00:00')) 
                                           if isinstance(article_data['scheduledAt'], str) 
                                           else article_data['scheduledAt'],
                           authorId=1,  # Default author ID, you might want to get this from request
                           categoryIds=[article_data['categoryId']],  # Convert to ObjectId if needed
                           metaTitle=article_data['title'][:60],
                           metaDescription=article_data['content'][:160],
                           metaKeywords=', '.join(item.get('keywords', [])),
                           metaImage=article_data.get('image_links', [''])[0] if article_data.get('image_links') else '',
                           ogTitle=article_data['title'],
                           ogDescription=article_data['content'][:300],
                           ogType='article',
                           twitterCard='summary_large_image',
                           twitterDescription=article_data['content'][:200],
                           focusKeyword=item.get('keywords', [''])[0] if item.get('keywords') else '',
                           language=self.language,
                           word_count=len(article_data['content'].split()),
                           readingTime=max(1, len(article_data['content'].split()) // 200),
                           content_type='article',
                           image_urls=rephrased.get('image_urls', []),
                           metadata=json.dumps(article_data),
                           lastError=None,
                           canonicalUrl=category_item.get('url', ''),
                           featured=False,
                           target_path=self.data.get('target_path') or await get_target_path(self.request, article_data),  # Use target_path from request or fallback to get_target_path
                           )
                       
                       # Log the payload before saving
                       self.logger.info("Saving news post with payload:")
                       log_data = {
                           'title': news_post.title,
                           'slug': news_post.slug,
                           'status': news_post.status,
                           'target_path': news_post.target_path,
                           'language': news_post.language,
                           'scheduledAt': news_post.scheduledAt.isoformat() if hasattr(news_post.scheduledAt, 'isoformat') else str(news_post.scheduledAt),
                           'categoryIds': news_post.categoryIds,
                           'word_count': news_post.word_count,
                           'readingTime': news_post.readingTime
                       }
                       self.logger.info(json.dumps(log_data, indent=2, default=str))
                       
                       # Save to database
                       await sync_to_async(news_post.save)()
                       
                       # Get the ID after saving
                       news_post_id = str(news_post._id) if hasattr(news_post, '_id') else None
                       
                       if not news_post_id and hasattr(news_post, 'id'):
                           news_post_id = str(news_post.id)
                       
                       # Log success
                       self.logger.info(f"✅ Saved NewsPost with ID: {news_post_id}, categoryIds: {news_post.categoryIds}")
                       
                       # Store the ID in article_data for reference
                       if news_post_id:
                           article_data['id'] = news_post_id
                       self.logger.info(f"Successfully saved article with ID: {article_data['id']}")
                       
                   except Exception as e:
                       error_msg = f"Error saving article to database: {str(e)}\n{traceback.format_exc()}"
                       self.logger.error(error_msg)
                       article_data['save_error'] = error_msg
                   logger.info(f"Iteration : {index}")  
                   index = index + 1
                   logger.info(f"[DEBUG] CeleryNews.process - Rephrased content: {json.dumps(rephrased, indent=2)}")
                   logger.info(f"[DEBUG] CeleryNews.process - article data: {json.dumps(article_data)}")
                   # Add article_data to results list
                   if 'results' not in locals():
                       results = []
                   results.append(article_data)
        except Exception as e:
            error_msg = f"Error during scraping: {str(e)}\n{traceback.format_exc()}"
            self.logger.error(error_msg)
            return {
                'status': 'error',
                'error': error_msg,
                'count': 0,
                'articles_processed': 0,
                'results': []
            }
        return {
            'status': 'ok',
            'categories': self.categories,
            'language': self.language,
            'country': self.country,
            'vendor': self.vendor,
            'times': self.times,
            'results': results if 'results' in locals() else []
        }

def process_news_task_impl(request_body, request=None):
    """Implementation of the news processing task using CeleryNews class."""
    logger.info(f"[DEBUG] process_news_task_impl - Raw request body: {request_body}")
    try:
        celery_news = CeleryNews(request_body, request)
        # If you want to run the async process method synchronously:
        loop = asyncio.get_event_loop() if asyncio.get_event_loop().is_running() else asyncio.new_event_loop()
        if loop.is_running():
            # If already running (e.g. in an async context), use create_task
            result = loop.create_task(celery_news.process())
        else:
            result = loop.run_until_complete(celery_news.process())
        return result
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return {
            'status': 'error',
            'error': error_msg,
            'count': 0,
            'articles_processed': 0,
            'results': []
        }