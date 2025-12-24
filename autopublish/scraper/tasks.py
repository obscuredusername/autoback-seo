import asyncio
import logging
from celery import shared_task
from celery.utils.log import get_task_logger

from scraper.service import ScrapingService as ScraperService

logger = get_task_logger(__name__)

@shared_task(bind=True, name='autopublish.scraper.tasks.process_and_save_images')
def process_and_save_images(self, query: str, max_results: int = 5, language: str = 'en', country: str = 'us') -> dict:
    """Task to search for images, process them, and save to S3."""
    try:
        scraper = ScraperService()
        image_links = scraper.image_links(query=query, max_results=max_results)
        if not image_links:
            return {'success': False, 'processed_images': [], 'error': 'No images found'}
        
        processed_urls = []
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            async def process_image(link):
                try:
                    return await scraper.save_and_process_image(link, query)
                except: 
                    return None
            
            for i in range(0, len(image_links), 5):
                batch = image_links[i:i+5]
                tasks = [process_image(link) for link in batch]
                results = loop.run_until_complete(asyncio.gather(*tasks))
                processed_urls.extend([url for url in results if url])
                if len(processed_urls) >= 2: 
                    break
            
            return {'success': True, 'processed_images': processed_urls[:2]}
        finally:
            loop.close()
    except Exception as e:
        return {'success': False, 'error': str(e)}

@shared_task(bind=True, name="autopublish.scraper.tasks.process_scraping_task")
def process_scraping_task(self, *args, **kwargs):
    """Task for handling keyword scraping operations."""
    task_id = self.request.id if hasattr(self, 'request') else 'unknown'
    try:
        keyword = kwargs.get('keyword', '')
        max_results = int(kwargs.get('max_results', 5))
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            scraper_service = ScraperService()
            scraped_data = loop.run_until_complete(scraper_service.keyword_scraping(keyword=keyword, max_results=max_results))
            return {'status': 'success', 'data': scraped_data}
        finally:
            loop.close()
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

@shared_task(bind=True, name='autopublish.scraper.tasks.scrape_news_task')
def scrape_news_task(self, categories, country='us', language='en', vendor='google'):
    """Task to scrape news."""
    try:
        service = ScraperService()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            formatted_categories = []
            for cat in categories:
                if isinstance(cat, str): 
                    formatted_categories.append({'name': cat, 'num': 5})
                else: 
                    formatted_categories.append(cat)
            result = loop.run_until_complete(service.fetch_news(categories=formatted_categories, country=country, language=language, vendor=vendor))
            return result
        finally:
            loop.close()
    except Exception as e:
        return {'status': 'error', 'error': str(e)}
