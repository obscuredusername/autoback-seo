import json
import os
import logging
import time
from datetime import datetime, timezone, datetime
from urllib.parse import urlparse, urlunparse
import asyncio
import aiohttp
import random
from bs4 import BeautifulSoup
from typing import List, Dict, Any, Optional, Union, Tuple
from .utils import retry
from .news_section import GoogleNewsScraper, YahooScraper, BingScraper, GNewsFetcher
from .base import WebContentScraper
logger = logging.getLogger(__name__)

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
        from .base import WebContentScraper
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
        
        # Initialize proxies
        self.proxies = self._initialize_proxies()
        self.current_proxy_index = 0
        self._ensure_output_dir()
        
        # Initialize news scrapers
        self.news_scrapers = {
            'google': GoogleNewsScraper(),
            'yahoo': YahooScraper(),
            'bing': BingScraper(),
            'gnews': GNewsFetcher()
        }
    
    def _initialize_proxies(self) -> List[str]:
        """
        Initialize and return a list of proxy servers from environment variables.
        
        Returns:
            List of proxy URLs
        """
        proxy_list = os.getenv('PROXY_LIST', '').split(',')
        # Remove any empty strings and strip whitespace
        return [p.strip() for p in proxy_list if p.strip()]

    def _get_next_proxy(self) -> Optional[str]:
        """
        Get the next proxy in rotation.
        
        Returns:
            str or None: The next proxy URL or None if no proxies are available
        """
        if not self.proxies:
            return None
            
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return proxy
        
    def _ensure_output_dir(self):
        """Ensure the output directory exists"""
        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)
    
    @retry(max_retries=3, initial_delay=1, max_delay=10, backoff_factor=2)
    async def _fetch_url_async(self, session: aiohttp.ClientSession, url: str, extract_selectors: dict = None, max_retries: int = 3) -> Optional[Dict[str, Any]]:
        """
        Asynchronously fetch and parse a single URL with proxy and retry support.
        
        Args:
            session: aiohttp ClientSession
            url: URL to scrape
            extract_selectors: Dictionary of CSS selectors for specific elements to extract
            max_retries: Maximum number of retry attempts with different proxies
            
        Returns:
            Dictionary containing scraped data or None if all retries fail
        """
        headers = {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
        }
        
        last_error = None
        
        for attempt in range(max_retries):
            proxy_url = self._get_next_proxy()
            proxy_auth = None
            
            # Parse proxy URL and set up auth
            if proxy_url:
                try:
                    # Parse the proxy URL
                    parsed = urlparse(proxy_url)
                    
                    # Extract components
                    proxy_host = parsed.hostname
                    proxy_port = parsed.port or 80
                    username = parsed.username
                    password = parsed.password
                    
                    # Reconstruct proxy URL without auth
                    proxy_url = f"http://{proxy_host}:{proxy_port}"
                    
                    # Set up auth if credentials are provided
                    if username and password:
                        proxy_auth = aiohttp.BasicAuth(username, password)
                        print(f"Using proxy with auth: {username}:***@{proxy_host}:{proxy_port}")
                    else:
                        print(f"Using proxy without auth: {proxy_url}")
                        
                except Exception as e:
                    print(f"Error parsing proxy URL {proxy_url}: {str(e)}")
                    proxy_url = None
            
            try:
                print(f"Attempt {attempt + 1}/{max_retries} fetching {url} with proxy {proxy_url}")
                
                # Prepare proxy string with auth if needed
                proxy_str = None
                if proxy_url:
                    if proxy_auth:
                        proxy_str = f"http://{proxy_auth.login}:{proxy_auth.password}@{proxy_url.split('//')[-1]}"
                    else:
                        proxy_str = proxy_url
                
                # Make the request
                async with session.get(
                    url,
                    headers=headers,
                    proxy=proxy_str,
                    timeout=aiohttp.ClientTimeout(total=30),
                    ssl=False,
                    allow_redirects=True
                ) as response:
                    if response.status == 200:
                        content = await response.text()
                        soup = BeautifulSoup(content, 'html.parser')
                        
                        # Extract title and content
                        title = soup.title.string if soup.title else "No title"
                        content_text = ' '.join([p.get_text() for p in soup.find_all('p')])
                        
                        result = {
                            'url': url,
                            'title': title,
                            'content': content_text,
                            'status': 'success'
                        }
                        
                        # Extract specific elements if selectors are provided
                        if extract_selectors:
                            extracted = {}
                            for key, selector in extract_selectors.items():
                                element = soup.select_one(selector)
                                if element:
                                    extracted[key] = element.get_text(strip=True)
                            if extracted:
                                result['extracted'] = extracted
                        
                        return result
                    else:
                        last_error = f"HTTP {response.status}"
                        print(f"Request failed with status {response.status}")
                        
                last_error = str(e)
                logger.warning(f"Attempt {attempt + 1}/{max_retries} failed for {url} with proxy {proxy_url}: {last_error}")
                if attempt < max_retries - 1:
                    # Add a small delay before retrying with next proxy
                    await asyncio.sleep(1)
                continue
            except Exception as e:
                last_error = str(e)
                logger.error(f"Unexpected error fetching {url}: {last_error}", exc_info=True)
                return None
        
        # If we get here, all retries failed
        logger.error(f"Failed to fetch {url} after {max_retries} attempts. Last error: {last_error}")
        return None

    @retry(max_retries=2, initial_delay=1, max_delay=5, backoff_factor=1.5)
    async def scrape_urls_async(self, urls: List[str], extract_selectors: dict = None) -> List[Dict[str, Any]]:
        """
        Asynchronously scrape multiple URLs in parallel with proxy support.
        
        Args:
            urls: List of URLs to scrape
            extract_selectors: Dictionary of CSS selectors for specific elements to extract
            
        Returns:
            List of dictionaries containing scraped data
        """
        if not urls:
            return []
            
        # Filter out invalid URLs
        valid_urls = [url for url in urls if url and not self._is_youtube_url(url)]
        
        # Create a semaphore to limit concurrency
        sem = asyncio.Semaphore(self.max_concurrent)
        
        async def fetch_with_semaphore(session, url):
            async with sem:
                return await self._fetch_url_async(session, url, extract_selectors)
        
        # Use a single session for all requests
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            tasks = [fetch_with_semaphore(session, url) for url in valid_urls]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
        # Filter out exceptions and failed requests
        return [r for r in results if isinstance(r, dict)]

    def _run_async_scrape(self, urls, extract_selectors):
        """Helper method to run async code from sync context"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(self.scrape_urls_async(urls, extract_selectors))
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    @retry(max_retries=2, initial_delay=1, max_delay=5, backoff_factor=1.5)
    def scrape_url(self, url, extract_selectors=None, timeout=30):
        """
        Synchronous wrapper for scraping a single URL.
        
        Args:
            url (str): The URL to scrape
            extract_selectors (dict): Dictionary of CSS selectors for specific elements to extract
            timeout (int): Request timeout in seconds
            
        Returns:
            dict: Dictionary containing scraped data or None if failed
        """
        if not url:
            return None
            
        try:
            # Check if we're in an event loop
            try:
                loop = asyncio.get_running_loop()
                # If we're in an event loop, create a task
                future = asyncio.create_task(self.scrape_urls_async([url], extract_selectors))
                results = asyncio.run_coroutine_threadsafe(future, loop).result()
                return results[0] if results else None
            except RuntimeError:
                # No event loop, run synchronously
                results = self._run_async_scrape([url], extract_selectors)
                return results[0] if results else None
        except Exception as e:
            logger.error(f"Error in scrape_url: {str(e)}")
            return None

         

    def _is_youtube_url(self, url):
        """Check if URL is from YouTube"""
        youtube_domains = ['youtube.com', 'youtu.be', 'youtube-nocookie.com']
        return any(domain in url.lower() for domain in youtube_domains)

    @retry(max_retries=3, initial_delay=1, max_delay=10, backoff_factor=2)
    def image_links(self, query, max_results=2):
        # Always limit to exactly 2 images
        links = self.scraper.bing_image_scraper(query, max_results=2)
        logger.info(f"Retrieved {len(links)} image links for query: {query}")
        return links
    
    @retry(max_retries=3, initial_delay=1, max_delay=10, backoff_factor=2)
    def video_links(self, query):
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
                # Download the image
                timeout = aiohttp.ClientTimeout(total=60)
                headers = {
                    'User-Agent': random.choice(self.user_agents)
                }
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(image_url, headers=headers, ssl=False) as response:
                        if response.status != 200:
                            logger.error(f"Failed to download image: {image_url} (Status: {response.status})")
                            return original_url
                        image_data = await response.read()
        
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
    
    def _get_unique_articles(self, links, existing_urls=None):
        """
        Filter out duplicate URLs and return unique ones
        
        Args:
            links: List of URLs to filter
            existing_urls: Set of already seen URLs (optional)
            
        Returns:
            tuple: (list of unique URLs, set of all seen URLs)
        """
        if existing_urls is None:
            existing_urls = set()
        
        unique_links = []
        for link in links:
            # Skip if URL is None, empty, or from YouTube
            if not link or self._is_youtube_url(link):
                continue
                
            # Normalize URL for comparison (remove query params, fragments, etc.)
            parsed = urlparse(link)
            clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            clean_url = clean_url.rstrip('/')
            
            if clean_url not in existing_urls:
                existing_urls.add(clean_url)
                unique_links.append(link)
        
        return unique_links, existing_urls
        
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
                
                # Handle different vendors with their specific implementations
                if current_vendor == 'gnews':
                    result = await self._fetch_gnews(
                        scraper, 
                        categories, 
                        country, 
                        language,
                        max_articles_per_category
                    )
                elif current_vendor == 'yahoo':
                    result = await self._fetch_yahoo(
                        scraper, 
                        categories, 
                        country, 
                        language,
                        max_articles_per_category
                    )
                else:
                    # For other scrapers that use the standard interface
                    result = await self._fetch_bing(
                        scraper, 
                        categories, 
                        country, 
                        language,
                        max_articles_per_category
                    )
                
                # Ensure the result has the expected structure
                if 'success' not in result:
                    result['success'] = True
                if 'vendor' not in result:
                    result['vendor'] = current_vendor
                if 'categories' not in result:
                    result['categories'] = {}
                if 'total_articles' not in result:
                    result['total_articles'] = sum(len(articles) for articles in result.get('categories', {}).values())
                
                # If we got results, return them
                if result.get('total_articles', 0) > 0:
                    # Add metadata about the original request and any fallbacks used
                    result['original_vendor'] = original_vendor
                    if current_vendor != original_vendor:
                        result['fallback_used'] = current_vendor
                    return result
                
                logger.info(f"No results from {current_vendor}, trying next available source...")
                
            except Exception as e:
                last_error = e
                logger.warning(f"Error fetching from {current_vendor}: {str(e)}")
                continue
        
        # If we get here, all vendors failed or returned no results
        error_msg = f"Failed to fetch news from any source. Last error: {str(last_error) if last_error else 'No results from any vendor'}"
        logger.error(error_msg)
        return {
            'success': False,
            'error': error_msg,
            'categories': {cat['name']: [] for cat in categories},
            'total_articles': 0,
            'vendor': original_vendor,
            'original_vendor': original_vendor
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
            logger.error(f"Error fetching news from Yahoo: {str(e)}", exc_info=True)
            # Return empty result structure on error
            return {
                'success': False,
                'categories': {cat['name']: [] for cat in categories},
                'total_articles': 0,
                'vendor': 'yahoo',
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
            unique_links, _ = self._get_unique_articles(search_results)
            
            if not unique_links:
                return {
                    'success': False,
                    'error': 'No valid articles found after filtering',
                    'articles': [],
                    'total_found': 0,
                    'total_scraped': 0
                }
            
            logger.info(f"Found {len(unique_links)} unique articles")
            
            # Scrape up to max_results articles
            articles = []
            scraped_count = 0
            
            for url in unique_links[:max_results]:
                try:
                    logger.info(f"Scraping article {scraped_count + 1}/{min(max_results, len(unique_links))}: {url}")
                    
                    # Scrape the article
                    article_data = self.scrape_url(url=url)
                    
                    if article_data:
                        # Add metadata
                        article_data['source_url'] = url
                        article_data['query'] = query
                        article_data['language'] = language
                        article_data['country'] = country
                        
                        articles.append(article_data)
                        scraped_count += 1
                        
                        # Add a small delay between requests
                        time.sleep(1)
                        
                except Exception as e:
                    logger.warning(f"Error scraping article {url}: {str(e)}")
                    continue
            
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
    
    def _save_to_file(self, data, filename):
        """
        Save scraped data to a JSON file.
        
        Args:
            data: Data to save
            filename: Output filename
            
        Returns:
            str: Path to the saved file, or None if failed
        """
        try:
            filepath = os.path.join(self.output_dir, filename)
            # Commented out file writing as per request
            # with open(filepath, 'w', encoding='utf-8') as f:
            #     json.dump(data, f, ensure_ascii=False, indent=2)
            return None  # Return None since we're not saving files anymore
        except Exception as e:
            logger.error(f"Error saving to file: {str(e)}")
            return None
    
    def _save_to_json(self, data, filepath):
        """Save data to a JSON file."""
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

            return {
                'success': True,
                'articles': scraped_data,
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
