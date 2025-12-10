import logging
import json
import asyncio
import time
from django.views import View
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from asgiref.sync import sync_to_async
from .service import ScrapingService
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

class AsyncViewMixin:
    """Mixin to handle async operations in Django views"""
    @classmethod
    def as_view(cls, **initkwargs):
        view = super().as_view(**initkwargs)
        view._is_coroutine = asyncio.coroutines._is_coroutine
        return view

class BaseScraperView(AsyncViewMixin, View):
    """Base view for all scraper endpoints"""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service = ScrapingService()
    
    def get_json_payload(self, request):
        """Extract and validate JSON payload from request"""
        try:
            return json.loads(request.body)
        except json.JSONDecodeError:
            return None


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(require_http_methods(["POST"]), name='dispatch')
class KeywordSearchView(BaseScraperView):
    """
    Handle general keyword-based search requests asynchronously.
    
    Expected JSON payload:
    {
        "query": "search query",  # Required: search query
        "max_results": 5,         # Optional: max results to return (default: 5)
        "language": "en",         # Optional: language code (default: 'en')
        "country": "us"           # Optional: country code (default: 'us')
    }
    """
    async def post(self, request, *args, **kwargs):
        data = self.get_json_payload(request)
        if not data:
            return JsonResponse(
                {'success': False, 'error': 'Invalid JSON payload'},
                status=400
            )
        
        query = data.get('query')
        if not query:
            return JsonResponse(
                {'success': False, 'error': 'Search query is required'},
                status=400
            )
        
        try:
            # Get parameters with defaults
            max_results = min(int(data.get('max_results', 5)), 10)  # Cap at 10 results
            language = data.get('language', 'en')
            country = data.get('country', 'us')
            
            logger.info(f"Keyword search: {query} (lang: {language}, country: {country})")
            
            # Calculate how many results to fetch (2x requested to account for failures)
            fetch_count = max(10, max_results * 2)
            
            # Use search with fallback mechanism
            search_results = await sync_to_async(self.service.scraper.search_with_fallback)(
                keyword=query,
                country_code=country,
                language=language,
                max_results=fetch_count
            )
            
            if not search_results:
                return JsonResponse({
                    'success': False,
                    'error': 'No search results found',
                    'query': query
                }, status=404)
            
            # Filter out Google News URLs and invalid URLs
            valid_urls = [
                url for url in search_results 
                if url and 'news.google.com' not in url 
                and not any(domain in url.lower() 
                for domain in ['youtube.com', 'youtu.be', 'youtube-nocookie.com'])
            ]
            
            max_attempts = 5
            attempt = 0
            image_links = []
            video_links = []
            
            while attempt < max_attempts and (not image_links or not video_links):
                attempt += 1
                try:
                    if not image_links:
                        image_links = self.service.image_links(query, max_results=10) or []
                        logger.info(f"Attempt {attempt}: Found {len(image_links)} image links for query: {query}")
                    
                    if not video_links:
                        video_links = self.service.video_links(query) or []
                        logger.info(f"Attempt {attempt}: Found {len(video_links)} video links for query: {query}")
                    
                    # If we got both, we can break early
                    if image_links and video_links:
                        break
                        
                    # If we're on the last attempt and still missing one, use empty lists
                    if attempt == max_attempts:
                        logger.warning(f"Reached max attempts ({max_attempts}). Proceeding with available links.")
                        break
                        
                    # Wait a bit before retrying
                    time.sleep(1)
                    
                except Exception as e:
                    logger.error(f"Attempt {attempt} failed: {str(e)}")
                    if attempt == max_attempts:
                        logger.error("Max retry attempts reached. Proceeding with empty links.")
                        image_links = image_links or []
                        video_links = video_links or []
                    time.sleep(1)  # Brief pause before retry
            
            
            scraped_results = []
            if valid_urls:
                # Try to get at least max_results * 1.5 or all valid URLs, whichever is smaller
                target_urls = valid_urls[:min(len(valid_urls), int(max_results * 1.5))]
                results = await self.service.scrape_urls_async(target_urls)
                
                # Filter out None results and take only max_results
                scraped_results = []
                for result in results:
                    if not result:
                        continue
                    
                    scraped_results.append({
                        'url': result.get('url', ''),
                        'title': result.get('title', ''),
                        'content': result.get('content', ''),
                        'image_links': image_links,
                        'video_links': video_links,
                        'excerpt': (result.get('content', '')[:200] + '...') if result.get('content') else ''
                    })
                    
                    if len(scraped_results) >= max_results:
                        break
            
            if not scraped_results:
                return JsonResponse({
                    'success': False,
                    'error': 'No valid content could be scraped from the search results',
                    'query': query
                }, status=404)
            
            return JsonResponse({
                'success': True,
                'query': query,
                'results': scraped_results,
                'total_results': len(scraped_results)
            })
            
        except Exception as e:
            logger.error(f"Error in keyword search: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': 'An error occurred while processing your request',
                'details': str(e)
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(require_http_methods(["POST"]), name='dispatch')
class NewsByCategoryView(BaseScraperView):
    """
    Handle news scraping requests by category asynchronously.
    
    Expected JSON payload:
    {
        "categories": {           # Dictionary of categories and counts
            "technology": 3,      # Category name and number of articles
            "business": 2,
            "science": 2
        },
        "country": "us",         # Optional: country code (default: 'us')
        "language": "en",        # Optional: language code (default: 'en')
        "vendor": "google"       # Optional: 'google' or 'yahoo' (default: 'google')
    }
    """
    
    async def post(self, request, *args, **kwargs):
        # Log the raw request body for debugging
        print("\n=== DEBUG: Raw request body ===")
        print(request.body.decode('utf-8', errors='replace'))
        
        data = self.get_json_payload(request)
        if not data:
            print("\n=== DEBUG: Invalid JSON payload ===")
            return JsonResponse(
                {'success': False, 'error': 'Invalid JSON payload'},
                status=400
            )
        
        print("\n=== DEBUG: Parsed request data ===")
        print(f"Data type: {type(data)}")
        print(f"Data content: {data}")
        
        categories = data.get('categories')
        print(f"\n=== DEBUG: Categories data ===")
        print(f"Categories type: {type(categories)}")
        print(f"Categories content: {categories}")
        
        # Convert categories to the expected format
        formatted_categories = []
        if isinstance(categories, dict):
            # Convert from {category: count} to [{'name': category, 'num': count}]
            formatted_categories = [
                {'name': name, 'num': count}
                for name, count in categories.items()
            ]
        elif isinstance(categories, list):
            # Ensure each category has 'name' and 'num' keys
            formatted_categories = []
            for cat in categories:
                if isinstance(cat, dict) and 'name' in cat:
                    formatted_cat = {'name': cat['name']}
                    # Use 'num' if provided, otherwise use 'count', otherwise default to 1
                    if 'num' in cat:
                        formatted_cat['num'] = cat['num']
                    elif 'count' in cat:
                        formatted_cat['num'] = cat['count']
                    else:
                        formatted_cat['num'] = 1
                    formatted_categories.append(formatted_cat)
        
        if not formatted_categories:
            print("\n=== DEBUG: No valid categories found ===")
            return JsonResponse(
                {'success': False, 'error': 'No valid categories provided'},
                status=400
            )
            
        print("\n=== DEBUG: Formatted categories ===")
        print(formatted_categories)
        
        # Log the categories being processed
        print("\n=== DEBUG: Processing categories ===")
        logger.info(f"Categories: {categories}")
        try:
            # Get parameters with defaults
            country = data.get('country', 'us')
            language = data.get('language', 'en')
            vendor = data.get('vendor', 'google').lower()
            if vendor not in ['google', 'yahoo', 'bing']:
                return JsonResponse(
                    {'success': False, 'error': 'Invalid vendor. Must be "google", "yahoo", or "bing"'},
                    status=400
                )
            
            # Convert categories to the format expected by fetch_news: {category_name: count}
            news_results = await self.service.fetch_news(
                categories=formatted_categories,
                country=country,
                language=language,
                vendor=vendor,
                max_articles_per_category=10  # The max_articles_per_category is just a fallback - individual category 'num' will take precedence
            )
            
            if not news_results.get('success'):
                return JsonResponse({
                    'success': False,
                    'error': news_results.get('error', 'Failed to fetch news')
                }, status=500)
            
            return JsonResponse(news_results)
            
        except Exception as e:
            logger.exception("Error in NewsByCategoryView")
            return JsonResponse(
                {'success': False, 'error': 'An error occurred while processing your request'},
                status=500
            )


class ImageSearchView(BaseScraperView):
    """Handle image search requests.
    
    Expected JSON payload:
    {
        "query": "search query",  # Required: search query
        "max_results": 10        # Optional: max results to return (default: 10)
    }
    """
    
    @method_decorator(csrf_exempt)
    async def post(self, request, *args, **kwargs):
        """Handle POST request for image search"""
        data = self.get_json_payload(request)
        if not data:
            return JsonResponse(
                {'success': False, 'error': 'Invalid JSON payload'},
                status=400
            )
            
        query = data.get('query')
        if not query or not isinstance(query, str):
            return JsonResponse(
                {'success': False, 'error': 'Query parameter is required and must be a string'},
                status=400
            )
            
        max_results = data.get('max_results', 10)
        try:
            max_results = int(max_results)
            if max_results <= 0 or max_results > 50:  # Enforce a reasonable limit
                max_results = 10
        except (ValueError, TypeError):
            max_results = 10
            
        try:
            # Call the service method to get image links
            image_links = await sync_to_async(self.service.image_links)(
                query=query,
                max_results=max_results
            )
            
            return JsonResponse({
                'success': True,
                'query': query,
                'count': len(image_links) if image_links else 0,
                'results': image_links or []
            })
            
        except Exception as e:
            logger.exception(f"Error in ImageSearchView: {str(e)}")
            return JsonResponse(
                {'success': False, 'error': str(e)},
                status=500
            )