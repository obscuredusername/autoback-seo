import os
import logging
import asyncio
import aiohttp
import random
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union, Tuple, Callable, Coroutine
from .utils import retry
from .base import WebContentScraper

logger = logging.getLogger(__name__)

from .news_section import BingScraper, YahooScraper, GoogleNewsScraper, GNewsFetcher



class ScrapingService:
    """
    Service class for handling web scraping operations.
    Provides methods for general URL scraping and news-specific scraping.
    Supports both synchronous and asynchronous operations.
    """
    
    def __init__(self, max_concurrent: int = 5, timeout: int = 30):
        """
        Initialize the scraping service.
        
        Args:
            max_concurrent: Maximum number of concurrent requests for async operations
            timeout: Request timeout in seconds
        """
        self.scraper = WebContentScraper()
        self.output_dir = "scraped_data"
        self.max_concurrent = max_concurrent
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.59',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        
        # Initialize news scrapers
        self.news_scrapers = {
            'google': GoogleNewsScraper(),
            'bing': BingScraper(),
            'yahoo': YahooScraper(),
            'gnews': GNewsFetcher()
        }
        
        self._ensure_output_dir()
        
    def _ensure_output_dir(self):
        """Ensure the output directory exists"""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

    def image_links(self, query: str, max_results: int = 10) -> List[str]:
        """Delegate image search to the base scraper."""
        return self.scraper.bing_image_scraper(query, max_results=max_results)

    def video_links(self, query: str) -> str:
        """Delegate video search to the base scraper."""
        return self.scraper.scrape_youtube_video(query)



    


    async def save_and_process_image(self, image_url: str, keyword: str) -> str:
        """
        Save image to S3 in WebP format with 65% quality, add text watermark,
        and return the public URL. If saving fails, returns the original image URL.
        
        Args:
            image_url: URL of the image to download
            keyword: Keyword used for generating the filename
            
        Returns:
            str: S3 public URL of the saved image, or the original URL if saving fails
        """
        from PIL import Image, ImageDraw, ImageFont, ImageEnhance
        import io
        import aiohttp
        import re
        import tempfile
        import uuid
        import boto3
        from botocore.exceptions import ClientError, NoCredentialsError
        
        logger = logging.getLogger(__name__)
        original_url = image_url
        logger.info(f"Processing image: {image_url}")

        # Generate a safe filename
        base_name = re.sub(r'[^a-zA-Z0-9]', '', str(keyword).replace(' ', ''))[:20]
        filename = f"{base_name}_{str(uuid.uuid4())[:8]}.webp"  # Add UUID for uniqueness
        
        # S3 Configuration
        # S3 Configuration
        aws_access_key_id = os.getenv('AWS_ACCESS_KEY_ID')
        aws_secret_access_key = os.getenv('AWS_SECRET_ACCESS_KEY')
        region_name = os.getenv('AWS_S3_REGION_NAME', 'eu-north-1')
        bucket_name = os.getenv('AWS_STORAGE_BUCKET_NAME', 'autopublisher-crm')

        try:
            if aws_access_key_id and aws_secret_access_key:
                s3_client = boto3.client(
                    's3',
                    aws_access_key_id=aws_access_key_id,
                    aws_secret_access_key=aws_secret_access_key,
                    region_name=region_name
                )
            else:
                # Fallback to default credentials chain (e.g. ~/.aws/credentials, IAM role)
                s3_client = boto3.client('s3', region_name=region_name)
        except Exception as e:
            logger.error(f"Failed to initialize S3 client: {str(e)}")
            return original_url
        
        temp_path = None
        watermarked_path = None
        
        try:
            # If the URL is already an S3 URL, return it
            if image_url.startswith(f'https://{bucket_name}.s3.'):
                return image_url
                
            # If the URL is a local file path, read it
            if image_url.startswith('file://'):
                with open(image_url.replace('file://', ''), 'rb') as f:
                    image_data = f.read()
            else:
                # Download the image with retry logic
                timeout = aiohttp.ClientTimeout(total=60)
                headers = {
                    'User-Agent': random.choice(self.user_agents)
                }
                
                max_retries = 3
                retry_delay = 2
                image_data = None
                
                for attempt in range(max_retries):
                    try:
                        async with aiohttp.ClientSession(timeout=timeout) as session:
                            async with session.get(image_url, headers=headers, ssl=False) as response:
                                if response.status != 200:
                                    logger.error(f"Failed to download image: {image_url} (Status: {response.status})")
                                    return original_url
                                image_data = await response.read()
                                break  # Success, exit retry loop
                    except (aiohttp.ClientConnectorError, aiohttp.ClientError, ConnectionResetError) as e:
                        logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {image_url}: {str(e)}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2  # Exponential backoff
                        else:
                            logger.error(f"All retry attempts failed for {image_url}")
                            return original_url
                
                if not image_data:
                    logger.error(f"Failed to download image after {max_retries} attempts: {image_url}")
                    return original_url
        
            # Process the image
            with Image.open(io.BytesIO(image_data)) as img:
                # Convert to RGB if necessary (for PNG with transparency)
                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    background.paste(img, mask=img.split()[-1])
                    img = background
                
                # Save to a temporary file
                with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as temp_file:
                    temp_path = temp_file.name
                    img.save(temp_path, format='WEBP', quality=65, method=6)
                
                # Apply text watermark
                watermark_text = "Extifixpro"  # Your watermark text
                
                try:
                    with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as watermarked_temp_file:
                        watermarked_path = watermarked_temp_file.name
                    
                    # Create a transparent layer for the watermark
                    watermark = Image.new('RGBA', img.size, (0, 0, 0, 0))
                    draw = ImageDraw.Draw(watermark)
                    
                    # Calculate font size based on image dimensions
                    width, height = img.size
                    font_size = int(min(width, height) * 0.05)  # 5% of the smallest dimension
                    if font_size < 12:  # Minimum font size
                        font_size = 12
                        
                    try:
                        # Try to use a nice font if available, fallback to default
                        try:
                            font = ImageFont.truetype("arial.ttf", font_size)
                        except:
                            font = ImageFont.load_default()
                    except:
                        font = ImageFont.load_default()
                    
                    # Calculate text size
                    text_bbox = draw.textbbox((0, 0), watermark_text, font=font)
                    text_width = text_bbox[2] - text_bbox[0]
                    text_height = text_bbox[3] - text_bbox[1]
                    
                    # Calculate spacing based on text size
                    spacing = int(max(text_width, text_height) * 2.5)  # Increased spacing
                    
                    # Draw the watermark text in a grid
                    for x in range(-width, width * 2, spacing):
                        for y in range(-height, height * 2, spacing):
                            # Offset every other row for diagonal pattern
                            if (x // spacing) % 2 == 0:
                                y_offset = y
                            else:
                                y_offset = y + spacing // 2
                            
                            # Draw semi-transparent text
                            draw.text(
                                (x, y_offset),
                                watermark_text,
                                font=font,
                                fill=(255, 255, 255, 128)  # White with 50% opacity
                            )
                    
                    # Save the watermarked image
                    watermarked = Image.alpha_composite(img.convert('RGBA'), watermark)
                    watermarked = watermarked.convert('RGB')  # Convert back to RGB for JPEG
                    watermarked.save(watermarked_path, 'JPEG', quality=85, optimize=True)
                    
                    # Update temp_path to point to the watermarked image
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                    temp_path = watermarked_path

                except Exception as e:
                    logger.error(f"Error applying watermark: {str(e)}")
                    if watermarked_path and os.path.exists(watermarked_path):
                        os.unlink(watermarked_path)
                        watermarked_path = None
                    # Continue with the unwatermarked image
                
                # Upload to S3
                try:
                    with open(temp_path, 'rb') as file_data:
                        # Upload the file without any ACL settings
                        s3_client.upload_fileobj(
                            file_data,
                            bucket_name,
                            filename,
                            ExtraArgs={
                                'ContentType': 'image/webp'
                            }
                        )
                        
                        # Generate the public URL using virtual-hosted-style URL
                        s3_url = f"https://{bucket_name}.s3.eu-north-1.amazonaws.com/{filename}"
                    logger.info(f"Successfully uploaded image to S3: {s3_url}")
                    return s3_url
                    
                except (ClientError, NoCredentialsError) as e:
                    logger.error(f"Error uploading to S3: {str(e)}")
                    return original_url
                
        except Exception as e:
            logger.error(f"Unexpected error processing image: {str(e)}", exc_info=True)
            return original_url
            
        finally:
            # Clean up temp files
            try:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
                if watermarked_path and os.path.exists(watermarked_path):
                    os.unlink(watermarked_path)
            except Exception as e:
                logger.error(f"Error cleaning up temp files: {str(e)}")
    
    async def fetch_news(
        self,
        categories: List[Dict[str, Any]],
        country: str = 'us',
        language: str = 'en',
        vendor: str = 'google',
        max_articles_per_category: int = 5
    ) -> Dict[str, Any]:
        """
        Fetch news articles from the specified vendor with fallback to other vendors if needed.
        
        Args:
            categories: List of dictionaries with 'name' (category name) and 'num' (number of articles)
            country: Country code for news localization (default: 'us')
            language: Language code for news content (default: 'en')
            vendor: Primary news vendor to try first ('google', 'yahoo', 'bing', or 'gnews')
            max_articles_per_category: Maximum number of articles per category (default: 5)
            
        Returns:
            Dictionary containing articles organized by category and total count:
            {
                'categories': {
                    'category1': [
                        {'title': '...', 'content': '...', 'url': '...'},
                        ...
                    ],
                    'category2': [...],
                    ...
                },
                'total_articles': int,
                'vendor': str,
                'original_vendor': str,  # The original vendor that was requested
                'fallback_used': str     # If a fallback was used, which one
            }
        """
        logger.info(f"Fetching news from {vendor} for categories: {[c['name'] for c in categories]}")
        
        # Normalize vendor name
        original_vendor = vendor.lower()
        vendor = original_vendor
        
        # Get the appropriate scraper
        if vendor not in self.news_scrapers:
            raise ValueError(f"Unsupported news vendor: {vendor}. Supported vendors are: {', '.join(self.news_scrapers.keys())}")
        
        # Always use GNewsFetcher for google vendor
        if vendor == 'google':
            vendor = 'gnews'
        
        # List of vendors to try in order, starting with the requested one
        vendors_to_try = [vendor]
        
        # If the primary vendor is yahoo, set up fallbacks
        if vendor == 'yahoo':
            vendors_to_try.extend(['gnews', 'bing'])  # Add fallback vendors in order of preference
        
        last_error = None
        
        # Try each vendor in order until we get results
        for current_vendor in vendors_to_try:
            try:
                logger.info(f"Trying to fetch from {current_vendor}...")
                
                # Get the appropriate scraper for the current vendor
                scraper = self.news_scrapers[current_vendor]
                
                # Call the appropriate method based on scraper type
                if hasattr(scraper, 'fetch_news'):
                    # For standard scrapers with fetch_news method
                    result = await scraper.fetch_news(
                        categories=categories,
                        country=country,
                        language=language,
                        max_articles=max_articles_per_category
                    )
                elif hasattr(scraper, 'fetch_by_category'):
                    # For GNewsFetcher
                    category_results = await scraper.fetch_by_category(
                        categories=categories,
                        country=country,
                        language=language,
                        max_articles_per_category=max_articles_per_category
                    )
                    # Convert to the expected format
                    result = {
                        'categories': category_results.get('categories', {}),
                        'total_articles': category_results.get('total_articles', 0),
                        'vendor': current_vendor,
                        'success': True
                    }
                else:
                    raise ValueError(f"Scraper for {current_vendor} doesn't have a supported fetch method")
                
                # Ensure the result has the expected structure
                if 'success' not in result:
                    result['success'] = True
                if 'vendor' not in result:
                    result['vendor'] = current_vendor
                if 'categories' not in result:
                    result['categories'] = {}
                if 'total_articles' not in result:
                    result['total_articles'] = sum(len(articles) for articles in result['categories'].values())
                
                # Add original vendor and fallback info
                result['original_vendor'] = original_vendor
                if current_vendor != original_vendor:
                    result['fallback_used'] = current_vendor
                
                logger.info(f"Successfully fetched {result['total_articles']} articles from {current_vendor}")
                return result
                
            except Exception as e:
                last_error = str(e)
                logger.warning(f"Failed to fetch from {current_vendor}: {last_error}")
                if current_vendor != vendors_to_try[-1]:  # If not the last vendor to try
                    logger.info(f"Trying next vendor...")
                    continue
                
                # If we get here, all vendors failed
                logger.error(f"All vendors failed. Last error: {last_error}")
                return {
                    'success': False,
                    'error': f"All vendors failed. Last error: {last_error}",
                    'vendor': original_vendor,
                    'categories': {},
                    'total_articles': 0
                }
            
    async def _fetch_gnews(
        self, 
        gnews_fetcher, 
        categories: List[Dict[str, Any]],
        country: str,
        language: str,
        max_articles_per_category: int
    ) -> Dict[str, Any]:
        """Helper method to fetch news using GNewsFetcher which has a different interface."""
        try:
            # Prepare categories for GNewsFetcher
            gnews_categories = [
                {'name': cat['name'], 'count': cat.get('num', max_articles_per_category)}
                for cat in categories
            ]
            
            # Fetch news from GNews - ensure we await the coroutine
            result = await gnews_fetcher.fetch_by_category(
                categories=gnews_categories,
                country=country,
                language=language,
                max_articles_per_category=max_articles_per_category
            )
            
            # Format the result to match the expected structure
            formatted_result = {
                'success': True,
                'categories': {},
                'total_articles': 0,
                'vendor': 'gnews'
            }
            
            if result and isinstance(result, dict):
                # Convert the GNews format to our standard format
                for category, articles in result.items():
                    if isinstance(articles, list):
                        category_articles = []
                        for article in articles:
                            if not isinstance(article, dict):
                                continue
                                
                            title = article.get('title', '')
                            if not title:
                                continue
                                
                            # Get image and video links using the article title as query
                            image_links = []
                            video_links = []
                            
                            try:
                                # Get up to 10 image links
                                image_links = self.image_links(title, max_results=10)
                                if not isinstance(image_links, list):
                                    image_links = []
                                    
                                # Get 1 video link
                                video_link = self.video_links(title)
                                if video_link and isinstance(video_link, str):
                                    video_links = video_link  # Store as a single string instead of a list
                            except Exception as e:
                                logger.error(f"Error fetching media for article '{title}': {str(e)}")
                            
                            # Build article data with media links
                            article_data = {
                                'title': title,
                                'content': article.get('description', article.get('content', '')),
                                'url': article.get('url', ''),
                                'published_at': article.get('publishedAt', ''),
                                'source': article.get('source', {}).get('name', ''),
                                'image_url': article.get('urlToImage', ''),
                                'search_query': title,
                                'status': 'success',
                                'content_type': 'html',
                                'image_links': image_links[:10],  # Ensure max 10 images
                                'video_links': video_links,
                                'backlinks': [],
                                'scheduled_time': datetime.now(timezone.utc).isoformat(),
                                'category_id': f"temp_{category}"
                            }
                            category_articles.append(article_data)
                        
                        formatted_result['categories'][category] = category_articles
                        formatted_result['total_articles'] += len(formatted_result['categories'][category])
            
            return formatted_result
        except Exception as e:
            logger.error(f"Error fetching news from GNews: {str(e)}", exc_info=True)
            # Return empty result structure on error
            return {
                'success': False,
                'categories': {cat['name']: [] for cat in categories},
                'total_articles': 0,
                'vendor': 'gnews',
                'error': str(e)
            }
            
    async def _fetch_yahoo(
        self, 
        yahoo_scraper, 
        categories: List[Dict[str, Any]],
        country: str,
        language: str,
        max_articles_per_category: int
    ) -> Dict[str, Any]:
        """Helper method to fetch news from Yahoo with enhanced media support."""
        try:
            # Prepare categories for YahooScraper
            yahoo_categories = [
                {'name': cat['name'], 'num': cat.get('num', max_articles_per_category)}
                for cat in categories
            ]
            
            # Fetch news from Yahoo
            result = await yahoo_scraper.fetch_news(
                categories=yahoo_categories,
                country=country,
                language=language,
                max_articles=max_articles_per_category
            )
            
            # Format the result to include image and video links
            formatted_result = {
                'success': True,
                'categories': {},
                'total_articles': 0,
                'vendor': 'yahoo'
            }
            
            if result and 'categories' in result:
                # Process each category's articles
                for category, articles in result['categories'].items():
                    if isinstance(articles, list):
                        category_articles = []
                        for article in articles:
                            if not isinstance(article, dict):
                                continue
                                
                            title = article.get('title', '')
                            if not title:
                                continue
                                
                            # Get image and video links using the article title as query
                            image_links = []
                            video_links = []
                            
                            try:
                                # Get up to 10 image links
                                image_links = self.image_links(title, max_results=10)
                                if not isinstance(image_links, list):
                                    image_links = []
                                    
                                # Get 1 video link
                                video_links = self.video_links(title) or ''
                            except Exception as e:
                                logger.error(f"Error fetching media for article '{title}': {str(e)}")
                                video_links = ''
                            
                            # Build article data with media links
                            article_data = {
                                'title': title,
                                'content': article.get('content', ''),
                                'url': article.get('url', ''),
                                'published_at': article.get('scraped_at', datetime.now(timezone.utc).isoformat()),
                                'source': 'Yahoo News',
                                'image_url': article.get('image_url', ''),
                                'search_query': title,
                                'status': 'success',
                                'content_type': 'html',
                                'image_links': image_links[:10],  # Ensure max 10 images
                                'video_links': video_links,  # This is now a string
                                'backlinks': [],
                                'scheduled_time': datetime.now(timezone.utc).isoformat(),
                                'category_id': f"yahoo_{category}"
                            }
                            category_articles.append(article_data)
                        
                        formatted_result['categories'][category] = category_articles
                        formatted_result['total_articles'] += len(category_articles)
            
            return formatted_result
            
        except Exception as e:
            logger.error(f"Error in Yahoo fetch: {str(e)}", exc_info=True)
            return {
                'success': False,
                'categories': {cat['name']: [] for cat in categories},
                'total_articles': 0,
                'vendor': 'yahoo',
                'error': str(e)
            }


    async def _fetch_bing(
        self, 
        bing_scraper, 
        categories: List[Dict[str, Any]],
        country: str,
        language: str,
        max_articles_per_category: int
    ) -> Dict[str, Any]:
        """Helper method to fetch news from Yahoo with enhanced media support."""
        try:
            # Prepare categories for YahooScraper
            yahoo_categories = [
                {'name': cat['name'], 'num': cat.get('num', max_articles_per_category)}
                for cat in categories
            ]
            
            # Fetch news from Bing
            result = await bing_scraper.fetch_news(
                categories=yahoo_categories,
                country=country,
                language=language,
                max_articles=max_articles_per_category
            )
            
            # Format the result to include image and video links
            formatted_result = {
                'success': True,
                'categories': {},
                'total_articles': 0,
                'vendor': 'bing'
            }
            
            if result and 'categories' in result:
                # Process each category's articles
                for category, articles in result['categories'].items():
                    if isinstance(articles, list):
                        category_articles = []
                        for article in articles:
                            if not isinstance(article, dict):
                                continue
                                
                            title = article.get('title', '')
                            if not title:
                                continue
                                
                            # Get image and video links using the article title as query
                            image_links = []
                            video_links = []
                            
                            try:
                                # Get up to 10 image links
                                image_links = self.image_links(title, max_results=10)
                                if not isinstance(image_links, list):
                                    image_links = []
                                    
                                # Get 1 video link
                                video_links = self.video_links(title) or ''
                            except Exception as e:
                                logger.error(f"Error fetching media for article '{title}': {str(e)}")
                                video_links = ''
                            
                            # Build article data with media links
                            article_data = {
                                'title': title,
                                'content': article.get('content', ''),
                                'url': article.get('url', ''),
                                'published_at': article.get('scraped_at', datetime.now(timezone.utc).isoformat()),
                                'source': 'Bing News',
                                'image_url': article.get('image_url', ''),
                                'search_query': title,
                                'status': 'success',
                                'content_type': 'html',
                                'image_links': image_links[:10],  # Ensure max 10 images
                                'video_links': video_links,  # This is now a string
                                'backlinks': [],
                                'scheduled_time': datetime.now(timezone.utc).isoformat(),
                                'category_id': f"bing_{category}"
                            }
                            category_articles.append(article_data)
                        
                        formatted_result['categories'][category] = category_articles
                        formatted_result['total_articles'] += len(category_articles)
            
            return formatted_result
            
        except Exception as e:
            logger.error(f"Error in Bing fetch: {str(e)}", exc_info=True)
            return {
                'success': False,
                'categories': {cat['name']: [] for cat in categories},
                'total_articles': 0,
                'vendor': 'bing',
                'error': str(e)
            }

    @retry(max_retries=2, initial_delay=1, max_delay=5, backoff_factor=1.5)
    def scrape_news(self, query, source='google', max_results=5, language='en', country='us'):
        """
        Search and scrape news articles.
        
        Args:
            query (str): Search query
            source (str): News source (google, bing, etc.)
            max_results (int): Maximum number of articles to return (will fetch twice this number)
            language (str): Language code (e.g., 'en')
            country (str): Country/Region code (e.g., 'us')
            
        Returns:
            dict: {
                'success': bool,
                'articles': list of article data,
                'total_found': int,
                'total_scraped': int
            }
        """
        try:
            logger.info(f"Searching for news: {query} (lang: {language}, region: {country})")
            
            # First, get more results than needed to account for filtering
            search_count = min(max_results * 2, 20)  # Get more results to account for filtering
            
            logger.info(f"Searching for news articles with query: {query}")
            search_results = self.scraper.search_duckduckgo(
                keyword=query,
                country_code=country,
                language=language,
                max_results=search_count
            )
            
            if not search_results:
                logger.warning("No search results found")
                return {
                    'success': False,
                    'error': 'No search results found',
                    'articles': [],
                    'total_found': 0,
                    'total_scraped': 0
                }
            
            # Filter out YouTube and duplicate URLs
            unique_links = self.scraper.get_unique_links(search_results, count=len(search_results))
            
            if not unique_links:
                return {
                    'success': False,
                    'error': 'No valid articles found after filtering',
                    'articles': [],
                    'total_found': 0,
                    'total_scraped': 0
                }
            
            logger.info(f"Found {len(unique_links)} unique articles")
            
            # Scrape up to max_results articles using the base scraper's multiple URL method
            target_urls = unique_links[:max_results]
            scraped_results = self.scraper.scrape_multiple_urls(
                urls=target_urls,
                target_count=max_results,
                delay=1,
                min_length=100
            )
            
            # Add metadata to each successful result
            articles = []
            for article_data in scraped_results:
                if article_data:
                    # Find the original URL for this article
                    url = article_data.get('url')
                    article_data['source_url'] = url
                    article_data['query'] = query
                    article_data['language'] = language
                    article_data['country'] = country
                    articles.append(article_data)
            
            scraped_count = len(articles)
            
            return {
                'success': True,
                'articles': articles,
                'total_found': len(unique_links),
                'total_scraped': scraped_count
            }
            
        except Exception as e:
            logger.error(f"Error in scrape_news: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'articles': [],
                'total_found': 0,
                'total_scraped': 0
            }
    
    
    def _save_to_json(self, data, filepath):
        """
        Save data to a JSON file.
        
        Args:
            data: Data to save
            filepath: Path to save the file
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Commented out file writing as per request
            # with open(filepath, 'w', encoding='utf-8') as f:
            #     json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("File writing to disk is disabled")
            return False  # Return False since we didn't save the file
        except Exception as e:
            logger.error(f"Error saving to JSON file {filepath}: {str(e)}")
            return False

    async def keyword_scraping(self, keyword, max_results=5, language='en', country='us'):
        try:
            # Check if search_with_fallback is a coroutine function
            if asyncio.iscoroutinefunction(self.scraper.search_with_fallback):
                search_results = await self.scraper.search_with_fallback(
                    keyword=keyword,
                    country_code=country,
                    language=language,
                    max_results=max_results
                )
            else:
                # If it's not a coroutine, run it in a thread
                loop = asyncio.get_running_loop()
                search_results = await loop.run_in_executor(
                    None,
                    lambda: self.scraper.search_with_fallback(
                        keyword=keyword,
                        country_code=country,
                        language=language,
                        max_results=max_results
                    )
                )

            # Check if scrape_multiple_urls is a coroutine function
            if asyncio.iscoroutinefunction(self.scraper.scrape_multiple_urls):
                scraped_data = await self.scraper.scrape_multiple_urls(
                    urls=search_results,
                    target_count=max_results,
                    delay=2,
                    min_length=100
                )
            else:
                # If it's not a coroutine, run it in a thread
                loop = asyncio.get_running_loop()
                scraped_data = await loop.run_in_executor(
                    None,
                    lambda: self.scraper.scrape_multiple_urls(
                        urls=search_results,
                        target_count=max_results,
                        delay=2,
                        min_length=100
                    )
                )
            if asyncio.iscoroutinefunction(self.video_links):
                video_link = await self.video_links(keyword)
            else:
                loop = asyncio.get_running_loop()
                video_link = await loop.run_in_executor(
                    None, self.video_links, keyword
                )

            return {
                'success': True,
                'results': scraped_data,
                'video_link': video_link,
                'total_found': len(search_results) if search_results else 0,
                'total_scraped': len(scraped_data) if scraped_data else 0
            }

        except Exception as e:
            logger.error(f"Error in keyword_scraping: {str(e)}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'articles': [],
                'total_found': 0,
                'total_scraped': 0
            }
