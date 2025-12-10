from celery import shared_task
from celery.utils.log import get_task_logger
from django.db import transaction
import asyncio
import logging
from .service import ScrapingService as ScraperService

logger = get_task_logger(__name__)

@shared_task(bind=True, name='autopublish.scraper.tasks.process_and_save_images')
def process_and_save_images(self, query: str, max_results: int = 5, language: str = 'en', country: str = 'us') -> dict:
    """
    Task to search for images, process them with watermarks, and save to S3.
    
    Args:
        query: Search query for images
        max_results: Maximum number of images to process (default: 5)
        language: Language code (default: 'en')
        country: Country code (default: 'us')
        
    Returns:
        dict: {
            'success': bool,
            'query': str,
            'processed_images': list[str],  # List of S3 URLs
            'total_processed': int,
            'error': str (if any)
        }
    """
    try:
        logger.info(f"Starting image processing task for query: {query}")
        scraper = ScraperService()
        
        # Get image links
        image_links = scraper.image_links(query=query, max_results=max_results)
        
        if not image_links or not isinstance(image_links, list) or len(image_links) == 0:
            logger.warning(f"No image links found for query: {query}")
            return {
                'success': False,
                'query': query,
                'processed_images': [],
                'total_processed': 0,
                'error': 'No image links found'
            }
        
        processed_urls = []
        
        # Create a new event loop for the async operations
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Process images concurrently until we get 2 successful ones
            async def process_image(link):
                try:
                    s3_url = await scraper.save_and_process_image(link, query)
                    if s3_url != link:  # Only add if processing was successful
                        return s3_url
                    return None
                except Exception as e:
                    logger.error(f"Error processing image {link}: {str(e)}", exc_info=True)
                    return None
            
            # Process images in batches until we get 2 successful ones or run out of images
            batch_size = 5  # Process 5 at a time
            for i in range(0, len(image_links), batch_size):
                batch = image_links[i:i + batch_size]
                tasks = [process_image(link) for link in batch]
                results = loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
                
                # Add successful results
                processed_urls.extend([url for url in results if url and isinstance(url, str)])
                
                # If we have 2 successful images, we're done
                if len(processed_urls) >= 2:
                    processed_urls = processed_urls[:2]  # Take only first 2
                    break
            
            return {
                'success': True,
                'query': query,
                'processed_images': processed_urls,
                'total_processed': len(processed_urls),
                'error': None
            }
            
        except Exception as e:
            logger.error(f"Error in image processing task: {str(e)}", exc_info=True)
            return {
                'success': False,
                'query': query,
                'processed_images': processed_urls,
                'total_processed': len(processed_urls),
                'error': f"Processing error: {str(e)}"
            }
        finally:
            loop.close()
            
    except Exception as e:
        logger.error(f"Unexpected error in process_and_save_images task: {str(e)}", exc_info=True)
        return {
            'success': False,
            'query': query,
            'processed_images': [],
            'total_processed': 0,
            'error': f"Unexpected error: {str(e)}"
        }


@shared_task(bind=True, name="autopublish.scraper.tasks.process_scraping_task")
def process_scraping_task(self, *args, **kwargs):
    """
    Task for handling keyword scraping operations.
    
    Args:
        self: The task instance (automatically provided by bind=True)
        *args: Positional arguments for the task
        **kwargs: Keyword arguments for the task
            - keyword: The keyword to search for
            - language: Language code (default: 'en')
            - country: Country code (default: 'us')
            - max_results: Maximum number of results to return (default: 5)
            
    Returns:
        dict: Result of the scraping operation with serializable data
    """
    task_id = self.request.id if hasattr(self, 'request') else 'unknown'
    logger = get_task_logger(__name__)
    
    try:
        keyword = kwargs.get('keyword', '')
        language = kwargs.get('language', 'en')
        country = kwargs.get('country', 'us')
        max_results = int(kwargs.get('max_results', 5))
        
        logger.info(f"Starting scraping task {task_id} for keyword: {keyword}")
        
        # Create a new event loop for this task
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            # Get the scraper service and run the async function
            scraper_service = ScraperService()
            scraped_data = loop.run_until_complete(
                scraper_service.keyword_scraping(
                    keyword=keyword,
                    max_results=max_results,
                    language=language,
                    country=country
                )
            )
            
            # Ensure all data is serializable
            results = []
            for item in scraped_data.get('results', []):
                # Convert any non-serializable objects to strings
                serialized_item = {}
                for key, value in item.items():
                    try:
                        # Try to serialize the value
                        import json
                        json.dumps({key: value})
                        serialized_item[key] = value
                    except (TypeError, OverflowError):
                        # If not serializable, convert to string
                        serialized_item[key] = str(value)
                results.append(serialized_item)
            
            return {
                'status': 'success',
                'task_id': task_id,
                'message': f'Successfully scraped {len(results)} results for {keyword}',
                'data': {
                    'keyword': keyword,
                    'language': language,
                    'country': country,
                    'results': results,
                    'total_scraped': len(results)
                }
            }
            
        finally:
            # Always clean up the event loop
            loop.close()
            
    except Exception as e:
        error_msg = f"Error in scraping task {task_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        
        # Return error response instead of raising to prevent retries for now
        return {
            'status': 'error',
            'task_id': task_id,
            'message': error_msg,
            'data': None
        }
