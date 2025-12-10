import logging
import json
import os
import asyncio
import random
import ssl
import time
from urllib.parse import urlparse
import re
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timedelta
from urllib.parse import urlparse, urljoin, quote_plus

from bs4 import BeautifulSoup
import aiohttp
from django.conf import settings

from .base import WebContentScraper
from .utils import YahooLink
from .news_section import GoogleNewsScraper, BingScraper
from .service import GNewsFetcher

# Configure logger
logger = logging.getLogger(__name__)
class NewsService:
    """Service for fetching and processing news from various sources."""
    
    def __init__(self):
        self.scraper = WebContentScraper()
        # Initialize proxy list (can be populated from environment variables)
        self.proxies = self._initialize_proxies()
        self.current_proxy_index = 0
        # Initialize user agents for rotation
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (iPad; CPU OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
        ]
        # Initialize news scrapers
        self.scrapers = {
            'google': GoogleNewsScraper(),
            'bing': BingScraper(),
            'gnews': GNewsFetcher()
        }
    
    async def fetch_news(
        self,
        categories: List[Dict[str, Any]],
        country: str = 'us',
        language: str = 'en',
        vendor: str = 'google',
        max_articles_per_category: int = 5
    ) -> Dict[str, Any]:
        """
        Fetch news articles from specified categories using the specified vendor.
        
        Args:
            categories: List of dictionaries with 'name' (category) and 'count' (number of articles)
            country: Country code (e.g., 'us', 'uk')
            language: Language code (e.g., 'en', 'es')
            vendor: News vendor ('google', 'bing', or 'gnews')
            max_articles_per_category: Maximum articles per category
            
        Returns:
            Dictionary containing fetched articles and metadata
        """
        vendor = vendor.lower()
        if vendor not in self.scrapers:
            raise ValueError(f"Unsupported vendor: {vendor}. Supported vendors are: {', '.join(self.scrapers.keys())}")
        
        results = {
            'success': True,
            'vendor': vendor,
            'categories': {},
            'total_articles': 0,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        try:
            # Get the appropriate scraper
            scraper = self.scrapers[vendor]
            
            # Call the appropriate method based on scraper type
            if hasattr(scraper, 'fetch_news'):
                # For GoogleNewsScraper and BingScraper
                results = await scraper.fetch_news(
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
                results['categories'] = category_results
                results['total_articles'] = sum(len(articles) for articles in category_results.values())
            else:
                raise ValueError(f"Scraper {vendor} has no supported fetch method")
            
            # Ensure categories is a dictionary
            if isinstance(results['categories'], list):
                results['categories'] = {cat: results['categories'] for cat in categories}
            
            # Ensure all requested categories are in the results
            for category in categories:
                cat_name = category.get('name')
                if cat_name not in results['categories']:
                    results['categories'][cat_name] = []
            
        except Exception as e:
            logger.error(f"Error fetching news from {vendor}: {str(e)}", exc_info=True)
            results.update({
                'success': False,
                'error': str(e)
            })
        
        logger.info(f"Fetched {results.get('total_articles', 0)} articles from {vendor}")
        return results
    
    async def fetch_images(self, query: str, max_results: int = 5) -> List[str]:
        """
        Fetch image URLs using Bing Image Search.
        
        Args:
            query: Search query for images
            max_results: Maximum number of image URLs to return (default: 5)
            
        Returns:
            List of image URLs
        """
        try:
            # Use the existing bing_image_scraper from WebContentScraper
            image_urls = await asyncio.get_event_loop().run_in_executor(
                None,  # Uses the default ThreadPoolExecutor
                lambda: self.scraper.bing_image_scraper(query, max_results)
            )
            
            # Ensure we return a list of strings
            if not image_urls:
                return []
                
            # Make sure we have a list of strings
            if isinstance(image_urls, list):
                return [str(url) for url in image_urls if url and isinstance(url, str)]
                
            return []
            
        except Exception as e:
            logger.error(f"Error in fetch_images: {str(e)}", exc_info=True)
            return []
            
    async def _scrape_articles(self, service, urls: List[str], category: str, max_retries: int = 2) -> List[Dict[str, Any]]:
        """
        Scrape multiple articles asynchronously with improved error handling and retries.
        
        Args:
            service: The scraping service instance
            urls: List of article URLs to scrape
            category: Category name for the articles
            max_retries: Maximum number of retry attempts for failed requests
            
        Returns:
            List of successfully scraped articles with content
        """
        if not urls:
            return []
            
        # Filter and clean URLs
        valid_urls = []
        seen_domains = set()
        
        for url in urls:
            if not url:
                continue
                
            try:
                # Clean and normalize URL
                url = url.strip()
                if not url.startswith(('http://', 'https://')):
                    url = 'https://' + url
                
                # Parse URL to get domain
                parsed = urlparse(url)
                domain = parsed.netloc.lower()
                
                # Skip unwanted domains and patterns
                blacklist = [
                    'youtube.com', 'youtu.be', 'google.', 'bing.', 'duckduckgo.com',
                    'facebook.com', 'twitter.com', 'instagram.com', 'linkedin.com',
                    'pinterest.com', 'reddit.com', 'quora.com', 'tiktok.com',
                    'amazon.', 'ebay.', 'wikipedia.org', 'imdb.com', 'yelp.com',
                    'tripadvisor.com', 'webmd.com', 'healthline.com', 'mayoclinic.org',
                    'pcmag.com', 'science.org'  # Known to give 403
                ]
                
                if any(black in domain for black in blacklist):
                    continue
                    
                # Check for common non-article paths
                path = parsed.path.lower()
                if any(x in path for x in ['/search', '/login', '/signin', '/register', '/signup']):
                    continue
                    
                # Check for common file extensions
                if any(path.endswith(ext) for ext in ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']):
                    continue
                
                # Skip duplicates
                if domain in seen_domains:
                    continue
                    
                valid_urls.append(url)
                seen_domains.add(domain)
                
            except Exception as e:
                logger.warning(f"Error processing URL {url}: {str(e)}")
                continue
        
        if not valid_urls:
            logger.warning("No valid URLs to scrape after filtering")
            return []
            
        # Scrape articles with retries
        all_articles = []
        failed_urls = []
        
        # First attempt
        logger.info(f"Attempting to scrape {len(valid_urls)} URLs for category: {category}")
        articles = await service.scrape_urls_async(valid_urls)
        
        # Process results and identify failed URLs
        for url, article in zip(valid_urls, articles):
            if article and article.get('content'):
                article['category'] = category
                all_articles.append(article)
                logger.debug(f"Successfully scraped: {url}")
            else:
                failed_urls.append(url)
                logger.warning(f"Failed to scrape (attempt 1): {url}")
        
        # If we have enough articles, return early
        if len(all_articles) >= len(valid_urls) * 0.5:  # If we got at least 50% success
            logger.info(f"Successfully scraped {len(all_articles)}/{len(valid_urls)} articles")
            return all_articles
        
        # Retry failed URLs with exponential backoff
        for attempt in range(max_retries):
            if not failed_urls:
                break
                
            # Wait before retry (exponential backoff with jitter)
            wait_time = (2 ** attempt) + random.random()
            logger.info(f"Waiting {wait_time:.2f}s before retry {attempt + 1} for {len(failed_urls)} URLs")
            await asyncio.sleep(wait_time)
            
            # Only retry a subset of failed URLs to be more efficient
            retry_batch = failed_urls[:10]  # Limit to 10 URLs per retry batch
            logger.info(f"Retry attempt {attempt + 1} for {len(retry_batch)} URLs")
            
            retry_articles = await service.scrape_urls_async(retry_batch)
            
            # Process retry results
            new_failed = []
            for url, article in zip(retry_batch, retry_articles):
                if article and article.get('content'):
                    article['category'] = category
                    all_articles.append(article)
                    logger.info(f"Successfully scraped on retry {attempt + 1}: {url}")
                else:
                    new_failed.append(url)
                    logger.warning(f"Failed to scrape (attempt {attempt + 2}): {url}")
            
            # Update failed URLs for next iteration
            failed_urls = new_failed + failed_urls[len(retry_batch):]
        
        # Log final results
        success_count = len(all_articles)
        failure_count = len(failed_urls)
        total = success_count + failure_count
        
        if success_count > 0:
            logger.info(f"Successfully scraped {success_count}/{total} articles ({success_count/total:.0%} success rate)")
        if failure_count > 0:
            logger.warning(f"Failed to scrape {failure_count}/{total} articles")
        
        return all_articles

    async def _fetch_article_content(self, url: str, session: aiohttp.ClientSession, timeout: int = 20) -> Dict[str, Any]:
        """
        Fetch and parse the full content of a single article with multiple images.
        
        Args:
            url: Article URL
            session: aiohttp ClientSession for connection pooling
            timeout: Request timeout in seconds
            
        Returns:
            Dictionary with article content, multiple images, and metadata
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Referer': 'https://www.google.com/',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0',
                'TE': 'Trailers'
            }
            
            async with session.get(url, headers=headers, timeout=timeout, ssl=False) as response:
                if response.status != 200:
                    logger.warning(f"Failed to fetch {url}: HTTP {response.status}")
                    return None
                
                content_type = response.headers.get('Content-Type', '').lower()
                if 'application/json' in content_type:
                    try:
                        data = await response.json()
                        return {
                            'url': url,
                            'content': str(data)[:10000],  # Increased limit for JSON content
                            'status': 'success',
                            'content_type': 'json',
                            'images': []
                        }
                    except Exception as e:
                        logger.warning(f"Error parsing JSON from {url}: {str(e)}")
                        return None
                
                # Handle HTML content
                html = await response.text(encoding='utf-8', errors='replace')
                
                # Parse HTML with BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                
                # Extract title
                title = soup.title.string if soup.title else ''
                
                # Extract meta description
                meta_desc = ''
                meta_desc_tag = soup.find('meta', attrs={'name': 'description'}) or \
                              soup.find('meta', attrs={'property': 'og:description'}) or \
                              soup.find('meta', attrs={'name': 'twitter:description'})
                if meta_desc_tag:
                    meta_desc = meta_desc_tag.get('content', '').strip()
                
                # Extract main content - try to find article body
                article_content = ''
                article_selectors = [
                    'article',
                    'main',
                    '.article',
                    '.post-content',
                    '.entry-content',
                    '.article-content',
                    '.post-body',
                    '.story-content',
                    'div[itemprop="articleBody"]',
                    'div.content',
                    'div.article-body',
                    'div.article-text',
                    'div.article__content',
                    'div.article-content',
                    'div.article-body-content',
                    'div.article__body',
                    'div.article__content',
                    'div.article__text',
                    'div.article-body-text',
                    'div.article__body-text',
                    'div.article-container',
                    'div.article-wrapper',
                    'div.article-inner',
                    'div.article-main',
                    'div.article-section',
                    'div.article-wrapper',
                    'div.article-page',
                    'div.article-container',
                    'div.article-content-wrapper',
                    'div.article-content-container',
                    'div.article-text-content',
                    'div.article-content-body',
                    'div.article-content-text',
                    'div.article-content-wrapper',
                    'div.article-body-wrapper',
                    'div.article-text-wrapper',
                    'div.article-content-wrapper',
                    'div.article-content-container',
                    'div.article-content-inner',
                    'div.article-content-outer',
                    'div.article-content-main',
                    'div.article-content-article',
                    'div.article-content-section',
                    'div.article-content-article-body',
                    'div.article-content-article-text',
                    'div.article-content-article-content',
                    'div.article-content-article-wrapper',
                    'div.article-content-article-container',
                    'div.article-content-article-inner',
                    'div.article-content-article-outer',
                    'div.article-content-article-main',
                    'div.article-content-article-section',
                ]
                
                # Try to find article content using selectors
                article_element = None
                for selector in article_selectors:
                    article_element = soup.select_one(selector)
                    if article_element:
                        break
                
                # If no specific article element found, use the whole body
                if not article_element:
                    article_element = soup.body or soup
                
                # Remove unwanted elements
                for element in article_element.select('script, style, noscript, iframe, nav, footer, header, aside, .ad, .advertisement, .social-share, .related-posts, .comments, .newsletter, .newsletter-form, .newsletter-signup, .newsletter-subscribe, .newsletter-widget, .newsletter-container, .newsletter-wrapper, .newsletter-content, .newsletter-box, .newsletter-block, .newsletter-section, .newsletter-area, .newsletter-form-wrapper, .newsletter-form-container, .newsletter-signup-form, .newsletter-subscribe-form, .newsletter-form-inner, .newsletter-form-outer, .newsletter-form-content, .newsletter-form-box, .newsletter-form-block, .newsletter-form-section, .newsletter-form-area'):
                    element.decompose()
                
                # Get text content
                text = article_element.get_text(separator='\n', strip=True)
                
                # Clean up text
                lines = (line.strip() for line in text.splitlines())
                chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
                text = '\n'.join(chunk for chunk in chunks if chunk)
                
                # Combine title, meta description, and main content
                content = f"{title}\n\n{meta_desc}\n\n{text}"
                
                # Clean and limit content (increased limit to 15000 chars)
                content = '\n'.join(line.strip() for line in content.split('\n') if line.strip())
                content = content[:15000]
                
                # Extract multiple images
                images = []
                
                # Try to get Open Graph/Twitter images first
                og_image = soup.find('meta', property='og:image') or soup.find('meta', attrs={'name': 'og:image'})
                if og_image and og_image.get('content'):
                    images.append(og_image['content'])
                
                twitter_image = soup.find('meta', attrs={'name': 'twitter:image'}) or \
                              soup.find('meta', attrs={'property': 'twitter:image'})
                if twitter_image and twitter_image.get('content') and twitter_image['content'] not in images:
                    images.append(twitter_image['content'])
                
                # Get all images from article content
                for img in article_element.find_all('img', src=True):
                    img_url = img['src']
                    # Convert relative URLs to absolute
                    if img_url.startswith('//'):
                        img_url = f'https:{img_url}'
                    elif img_url.startswith('/'):
                        img_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}{img_url}"
                    
                    # Filter out tracking pixels and small images
                    if img_url not in images and 'pixel' not in img_url.lower() and 'icon' not in img_url.lower():
                        # Check image dimensions if available
                        width = int(img.get('width', 0) or 0)
                        height = int(img.get('height', 0) or 0)
                        if width >= 100 and height >= 100:
                            images.append(img_url)
                
                # If no images found, try to get any image from the page
                if not images:
                    for img in soup.find_all('img', src=True):
                        img_url = img['src']
                        if img_url.startswith('//'):
                            img_url = f'https:{img_url}'
                        elif img_url.startswith('/'):
                            img_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}{img_url}"
                        
                        if img_url not in images and 'pixel' not in img_url.lower() and 'icon' not in img_url.lower():
                            images.append(img_url)
                            if len(images) >= 5:  # Limit to 5 images
                                break
                
                # Ensure we have at least the main image from GNews if available
                main_image = None
                if hasattr(self, 'current_article') and self.current_article and 'image_url' in self.current_article:
                    main_image = self.current_article['image_url']
                    if main_image and main_image not in images:
                        images.insert(0, main_image)
                
                # Limit to 5 images max
                images = images[:5]
                
                # Extract backlinks (hrefs) from article content
                backlinks = []
                base_domain = f"{urlparse(url).scheme}://{urlparse(url).netloc}"
                
                # Get all links from the article content
                for link in article_element.find_all('a', href=True):
                    href = link['href']
                    
                    # Skip empty, anchor, and javascript links
                    if not href or href.startswith('#') or href.lower().startswith('javascript:'):
                        continue
                    
                    # Convert relative URLs to absolute
                    if href.startswith('//'):
                        href = f'https:{href}'
                    elif href.startswith('/'):
                        href = f"{base_domain}{href}"
                    
                    # Skip mailto: and other non-http(s) links
                    if not href.lower().startswith(('http://', 'https://')):
                        continue
                    
                    # Clean up the URL - remove tracking parameters and fragments
                    href = href.split('?')[0].split('#')[0].rstrip('/')
                    
                    # Skip links to the same domain (internal links)
                    if urlparse(href).netloc == urlparse(url).netloc:
                        continue
                    
                    # Add to backlinks if not already present and not too long
                    if href not in backlinks and len(href) < 500:
                        backlinks.append(href)
                    
                    # Limit to 10 backlinks max
                    if len(backlinks) >= 10:
                        break
                
                # If no external links found, include some internal ones (up to 5)
                if not backlinks:
                    for link in article_element.find_all('a', href=True):
                        href = link['href']
                        
                        # Skip empty, anchor, and javascript links
                        if not href or href.startswith('#') or href.lower().startswith('javascript:'):
                            continue
                        
                        # Convert relative URLs to absolute
                        if href.startswith('//'):
                            href = f'https:{href}'
                        elif href.startswith('/'):
                            href = f"{base_domain}{href}"
                        
                        # Clean up the URL
                        href = href.split('?')[0].split('#')[0].rstrip('/')
                        
                        # Only include internal links that aren't too long
                        if (href.startswith(base_domain) and 
                            href not in backlinks and 
                            len(href) < 500):
                            backlinks.append(href)
                        
                        if len(backlinks) >= 5:
                            break
                
                # Initialize video_links as None (no video)
                video_links = None
                
                # Get images from Bing Image Search based on the article title
                image_links = []
                if title and len(title.strip()) > 5:  # Only search if we have a meaningful title
                    try:
                        # Use the first 50 characters of the title as the search query
                        search_query = title[:50].strip()
                        image_links = await self.fetch_images(search_query, max_results=5)
                        logger.info(f"Fetched {len(image_links)} images for article: {title[:50]}...")
                    except Exception as e:
                        logger.warning(f"Error fetching images for article: {str(e)}", exc_info=True)
                
                # If no images found from Bing, fall back to the original images
                if not image_links:
                    image_links = list(images)  # Use the original images list
                
                # Search for videos related to the article title if available
                if title and len(title.strip()) > 5:  # Only search if we have a meaningful title
                    try:
                        # Use the scraper to search for YouTube videos
                        video_url = await asyncio.to_thread(
                            self.scraper.scrape_youtube_video,
                            title[:100]  # Limit title length for search
                        )
                        if video_url:
                            video_links = video_url  # Store as a single URL string
                    except Exception as e:
                        logger.warning(f"Error searching for videos: {str(e)}")
                        video_links = None  # Ensure video_links is None on error
                
                return {
                    'url': url,
                    'content': content,
                    'status': 'success',
                    'content_type': 'html',
                    'title': title[:300] if title else '',
                    'image_links': image_links,  # Single list of all image URLs
                    'video_links': video_links,  # Single video URL or None
                    'backlinks': backlinks  # Simple list of URLs
                }
                
        except Exception as e:
            logger.warning(f"Error fetching {url}: {str(e)}")
            return None

    async def _scrape_articles_concurrently(self, articles: List[Dict[str, Any]], max_workers: int = 5) -> List[Dict[str, Any]]:
        """
        Scrape article contents concurrently using aiohttp with improved error handling.
        
        Args:
            articles: List of article dictionaries with at least 'url' key
            max_workers: Maximum number of concurrent requests (reduced to prevent rate limiting)
            
        Returns:
            List of articles with scraped content
        """
        if not articles:
            return []
            
        connector = aiohttp.TCPConnector(
            limit=max_workers,
            force_close=True,
            enable_cleanup_closed=True,
            ssl=False
        )
        timeout = aiohttp.ClientTimeout(total=30, sock_connect=10)
        
        async with aiohttp.ClientSession(
            connector=connector,
            timeout=timeout,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        ) as session:
            tasks = []
            for article in articles:
                if 'url' in article and article.get('url'):
                    tasks.append(self._fetch_article_content(article['url'], session))
                else:
                    tasks.append(None)
            
            # Process results with error handling
            processed_articles = []
            for i, task in enumerate(asyncio.as_completed(tasks)):
                try:
                    result = await task
                    if result and isinstance(result, dict) and 'content' in result:
                        articles[i].update(result)
                        processed_articles.append(articles[i])
                except Exception as e:
                    logger.warning(f"Error processing article {i}: {str(e)}")
                    continue
                
                # Add a small delay between requests to be nice to servers
                if i < len(tasks) - 1:  # Don't sleep after the last request
                    await asyncio.sleep(0.5)
            
            return processed_articles

    async def _fetch_gnews_articles(self, query: str, category: str, count: int, language: str = 'en', country: str = 'us') -> List[Dict[str, Any]]:
        """
        Fetch news article metadata using GNews API (first phase).
        
        Args:
            query: Search query or category
            category: News category
            count: Number of articles to fetch
            language: Language code (default: 'en')
            country: Country code (default: 'us')
            
        Returns:
            List of article dictionaries with metadata
        """
        params = {
            'token': GNEWS_API_KEY,
            'lang': language,
            'country': country.lower(),
            'max': min(count * 2, 100),  # Fetch more to account for potential filtering
            'q': query
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(GNEWS_API_URL, params=params) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"GNews API error: {response.status} - {error_text}")
                        return []
                        
                    data = await response.json()
                    articles = data.get('articles', [])
                    
                    # Process and format article metadata
                    processed_articles = []
                    for article in articles:
                        try:
                            # Skip articles without required fields
                            if not all(key in article for key in ['title', 'url']):
                                continue
                                
                            # Basic article metadata
                            processed = {
                                'title': article.get('title', '').strip(),
                                'url': article.get('url', '').strip(),
                                'published_at': article.get('publishedAt', ''),
                                'source': article.get('source', {}).get('name', '').strip(),
                                'image_url': article.get('image', '').strip(),
                                'category': category,
                                'search_query': query
                            }
                            
                            # Remove any empty values
                            processed = {k: v for k, v in processed.items() if v}
                            processed_articles.append(processed)
                            
                            # Stop if we have enough articles
                            if len(processed_articles) >= count:
                                break
                                
                        except Exception as e:
                            logger.warning(f"Error processing article metadata: {str(e)}")
                            continue
                    
                    # Now fetch article contents concurrently
                    if processed_articles:
                        processed_articles = await self._scrape_articles_concurrently(processed_articles)
                    
                    # Save the response to a JSON file
                    response_data = {
                        'query': query,
                        'category': category,
                        'articles': processed_articles,
                        'timestamp': datetime.utcnow().isoformat(),
                        'params': params
                    }
                    self._save_to_json(response_data, f"gnews_{category}_{query}")
                    
                    return processed_articles
                    
        except Exception as e:
            logger.error(f"Error in _fetch_gnews_articles: {str(e)}", exc_info=True)
            return []

    def _save_to_json(self, data: Dict[str, Any], filename_prefix: str = 'gnews_response') -> str:
        """
        Log data that would be saved to a JSON file (file saving is disabled).
        
        Args:
            data: Data that would be saved
            filename_prefix: Prefix for the output file (not used for file operations)
            
        Returns:
            Empty string as no file is saved
        """
        try:
            # Log that we're skipping file save
            logger.info(f"Skipping file save for {filename_prefix} (data saving disabled)")
            
            # Log data size for debugging
            data_size = len(json.dumps(data))
            logger.debug(f"Data size: {data_size} bytes")
            
            return ""
            
        except Exception as e:
            logger.error(f"Error processing data: {str(e)}")
            return ""

    async def _fetch_google_news(
        self,
        categories: List[Dict[str, Any]],
        country: str,
        language: str,
        results: Dict[str, Any],
        max_articles: int
    ) -> None:
        """
        Fetch news articles using GNews API.
        
        This method uses the GNewsFetcher class to fetch articles for each category.
        """
        try:
            # Use the GNewsFetcher to fetch articles for all categories
            category_articles = await self.gnews_fetcher.fetch_by_category(
                categories=categories,
                country=country,
                language=language,
                max_articles_per_category=max_articles
            )
            
            # Process each category's articles to add any additional metadata
            for category_name, articles in category_articles.items():
                if not articles:
                    logger.warning(f"No articles found for category: {category_name}")
                    results[category_name] = []
                    continue
                    
                # Find the category data to get additional metadata like times and IDs
                category_data = next((c for c in categories if c.get('name') == category_name), {})
                
                # Process each article to add metadata
                processed_articles = []
                for idx, article in enumerate(articles):
                    # Add scheduled_time if available in category_data
                    if 'times' in category_data and idx < len(category_data['times']):
                        article['scheduled_time'] = category_data['times'][idx]
                        logger.debug(f"Added scheduled_time {article['scheduled_time']} to article {article['url']}")
                    
                    # Add category_id if available in category_data
                    if 'id' in category_data:
                        article['category_id'] = category_data['id']
                        logger.debug(f"Added category_id {category_data['id']} to article {article['url']}")
                    
                    processed_articles.append(article)
                
                # Store the processed articles in results
                results[category_name] = processed_articles
                logger.info(f"Successfully processed {len(processed_articles)} articles for category: {category_name}")
                
        except Exception as e:
            logger.error(f"Error in _fetch_google_news: {str(e)}", exc_info=True)
            # Ensure all requested categories have at least an empty list in results
            for category in categories:
                category_name = category.get('name')
                if category_name and category_name not in results:
                    results[category_name] = []
    
    async def _make_request(self, session: aiohttp.ClientSession, url: str, headers: dict = None, 
                          timeout: int = 30, max_retries: int = 3, use_proxy: bool = True) -> Optional[str]:
        """
        Helper method to make HTTP requests with error handling, retries, and rate limiting protection.
        Implements exponential backoff, proxy rotation, and user agent rotation to avoid detection.
        
        Args:
            session: aiohttp ClientSession to use for the request
            url: URL to fetch
            headers: Optional headers to include in the request
            timeout: Request timeout in seconds
            max_retries: Maximum number of retry attempts
            use_proxy: Whether to use proxy rotation
            
        Returns:
            Response content as string or None if all retries failed
        """
        if headers is None:
            headers = {}
            
        # Get domain for rate limiting
        domain = self._get_domain(url)
        
        # Get appropriate delay for this domain
        delay = self._domain_delays.get(domain, self._domain_delays['default'])
        
        # Add jitter to delay (between 0.8x and 1.2x)
        jittered_delay = delay * random.uniform(0.8, 1.2)
        
        # Apply delay if we've made a request to this domain recently
        await self._throttle_requests(domain, jittered_delay)
        
        # Default headers with rotating user agent
        default_headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'same-origin',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache',
            'Referer': 'https://www.google.com/',
            'TE': 'trailers',
            'User-Agent': self._get_random_user_agent()
        }
        
        # Rotate user agents to reduce detection
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 Edg/91.0.864.59',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.107 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36 OPR/77.0.4054.277',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (iPad; CPU OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
            'Mozilla/5.0 (Linux; Android 10; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/80.0.3987.162 Mobile Safari/537.36',
        ]
        
        # Update with any provided headers
        headers = {**default_headers, **headers}
        
        # Configure connection pooling with increased header size limit
        conn = aiohttp.TCPConnector(
            limit_per_host=5,  # Increased from 3 to 5 for better concurrency
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
            force_close=False,
            limit=20,  # Total connection pool size
            use_dns_cache=True,
            # Increase max header size to handle large headers from Yahoo
            limit_request_headers=32768,  # 32KB max header size
            limit_response_headers=32768,  # 32KB max header size
            ssl=False  # Disable SSL verification
        )
        
        # Configure timeout
        timeout = aiohttp.ClientTimeout(
            total=timeout * 2,
            connect=10,
            sock_connect=10,
            sock_read=20,
        )
        
        # Add jitter to avoid thundering herd
        jitter = random.uniform(0.5, 1.5)
        
        # Throttle requests to the same domain
        await self._throttle_requests(url, min_delay=2.0)  # At least 2s between requests to same domain
        
        # Track request start time for timeout handling
        start_time = time.time()
        
        async with aiohttp.ClientSession(connector=conn, timeout=timeout) as client_session:
            for attempt in range(max_retries):
                try:
                    # Rotate user agent for each attempt
                    headers['User-Agent'] = random.choice(user_agents)
                    
                    # Add cache-busting parameter
                    cache_buster = int(time.time() * 1000)  # More precise cache buster
                    parsed_url = urlparse(url)
                    if parsed_url.query:
                        request_url = f"{url}&_={cache_buster}"
                    else:
                        request_url = f"{url}?_={cache_buster}"
                    
                    # Log the request
                    safe_headers = {k: v for k, v in headers.items() 
                                  if k.lower() not in ['authorization', 'cookie', 'x-api-key']}
                    logger.debug(f"Request attempt {attempt + 1}/{max_retries}: {request_url}")
                    
                    # Make the request with increased header size limit
                    async with client_session.get(
                        request_url, 
                        headers=headers, 
                        allow_redirects=True,
                        ssl=False,  # Disable SSL verification
                        read_bufsize=32768,  # 32KB read buffer
                        max_line_size=32768,  # 32KB max line size
                        max_field_size=32768  # 32KB max field size
                    ) as response:
                        # Handle rate limiting with exponential backoff
                        if response.status == 429:  # Too Many Requests
                            retry_after = int(response.headers.get('Retry-After', 5))
                            wait_time = min(retry_after * (2 ** attempt), 120)  # Cap at 120s
                            logger.warning(f"Rate limited. Waiting {wait_time}s before retry {attempt + 1}/{max_retries}")
                            
                            # Update circuit breaker
                            if attempt >= max_retries // 2:  # If we've failed multiple times
                                self._circuit_breaker['open'] = True
                                self._circuit_breaker['last_failure'] = time.time()
                                logger.error(f"Circuit breaker tripped after multiple rate limits for {url}")
                                return None
                                
                            await asyncio.sleep(wait_time)
                            continue
                            
                        # Handle other error statuses
                        if response.status >= 400:
                            logger.warning(f"HTTP {response.status} for {url}")
                            
                            # Update circuit breaker for server errors
                            if response.status >= 500 and attempt >= 2:
                                self._circuit_breaker['open'] = True
                                self._circuit_breaker['last_failure'] = time.time()
                                logger.error(f"Circuit breaker tripped due to server error {response.status}")
                                return None
                                
                            # Retry with backoff
                            backoff = min(5 * (2 ** attempt), 60)
                            logger.info(f"Retrying in {backoff}s...")
                            await asyncio.sleep(backoff)
                            continue
                            
                        # Read and validate response with error handling for large headers
                        try:
                            content = await response.text()
                        except aiohttp.ClientPayloadError as e:
                            if 'too big' in str(e).lower() or 'header' in str(e).lower():
                                logger.warning(f"Header too large, retrying with simplified headers: {str(e)}")
                                # Try again with minimal headers
                                minimal_headers = {
                                    'User-Agent': headers['User-Agent'],
                                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                                    'Accept-Language': 'en-US,en;q=0.5',
                                    'DNT': '1',
                                    'Connection': 'keep-alive',
                                }
                                async with client_session.get(
                                    request_url,
                                    headers=minimal_headers,
                                    allow_redirects=True,
                                    ssl=False,
                                    read_bufsize=65536,  # 64KB read buffer
                                    max_line_size=65536,  # 64KB max line size
                                    max_field_size=65536  # 64KB max field size
                                ) as retry_response:
                                    content = await retry_response.text()
                            else:
                                raise
                        
                        # Check for captcha or block pages
                        if any(blocked in content.lower() for blocked in ['captcha', 'access denied', 'blocked', 'cloudflare']):
                            logger.warning(f"Detected block/captcha page for {url}")
                            
                            # Try to bypass with different headers
                            if 'cf-ray' in response.headers:
                                logger.info("Cloudflare detected, trying to bypass...")
                                headers.update({
                                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                                    'Accept-Encoding': 'gzip, deflate, br',
                                    'Accept-Language': 'en-US,en;q=0.5',
                                    'Cache-Control': 'no-cache',
                                    'Pragma': 'no-cache',
                                    'Upgrade-Insecure-Requests': '1',
                                })
                                continue
                            
                            return None
                            
                        if not content or len(content) < 100:  # Basic content validation
                            logger.warning(f"Empty or too short response from {url}")
                            continue
                            
                        # Cache the successful response
                        self._request_cache[cache_key] = (time.time(), content)
                        
                        # Clean up old cache entries (older than 1 hour)
                        current_time = time.time()
                        self._request_cache = {
                            k: v for k, v in self._request_cache.items() 
                            if current_time - v[0] < 3600
                        }
                            
                        return content
                        
                except asyncio.TimeoutError:
                    elapsed = time.time() - start_time
                    logger.error(f"Timeout after {elapsed:.2f}s while fetching {url}")
                    
                    # Update circuit breaker for timeouts
                    if attempt >= max_retries // 2:
                        self._circuit_breaker['open'] = True
                        self._circuit_breaker['last_failure'] = time.time()
                        logger.error("Circuit breaker tripped due to timeout")
                        return None
                        
                except aiohttp.ClientError as e:
                    logger.error(f"Client error while fetching {url}: {str(e)}")
                    
                    # Update circuit breaker for client errors
                    if attempt >= max_retries // 2:
                        self._circuit_breaker['open'] = True
                        self._circuit_breaker['last_failure'] = time.time()
                        logger.error("Circuit breaker tripped due to client error")
                        return None
                        
                except Exception as e:
                    logger.error(f"Unexpected error while fetching {url}: {str(e)}", exc_info=True)
                    
                # Add exponential backoff with jitter between retries
                if attempt < max_retries - 1:
                    backoff = min(5 * (2 ** attempt), 60)  # Cap at 60s
                    jitter = random.uniform(0.8, 1.2)  # Add jitter
                    wait_time = backoff * jitter
                    logger.debug(f"Waiting {wait_time:.2f}s before retry {attempt + 2}/{max_retries}")
                    await asyncio.sleep(wait_time)
                
        # If we've exhausted all retries
        logger.error(f"Failed to fetch {url} after {max_retries} attempts")
        
        # Update circuit breaker
        self._circuit_breaker['open'] = True
        self._circuit_breaker['last_failure'] = time.time()
        logger.error("Circuit breaker tripped after all retries failed")
        
        return None

    def _initialize_proxies(self) -> list:
        """Initialize proxy list from environment variables or use defaults."""
        proxy_list = os.getenv('PROXY_LIST', '').split(',')
        proxies = [p.strip() for p in proxy_list if p.strip()]
        
        # Add some free proxy servers as fallback (use with caution)
        if not proxies:
            proxies = [
                'http://p.webshare.io:80',
                'http://p.webshare.io:8080',
                'http://p.webshare.io:3128',
            ]
        
        logger.info(f"Initialized {len(proxies)} proxies")
        return proxies
    
    def _get_next_proxy(self) -> Optional[dict]:
        """Get the next proxy in rotation."""
        if not self.proxies:
            return None
            
        proxy = self.proxies[self.current_proxy_index]
        self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxies)
        return {'http': proxy, 'https': proxy}
    
    def _get_random_user_agent(self) -> str:
        """Get a random user agent from the list."""
        return random.choice(self.user_agents)
    
    # Class-level circuit breaker state
    _circuit_breaker = {
        'open': False,
        'last_failure': 0,
        'reset_timeout': 60  # seconds to wait before retrying after circuit opens
    }
    
    # Request cache with TTL (5 minutes)
    _request_cache = {}
    _cache_ttl = 300  # 5 minutes
    
    # Last request timestamp per domain with jitter
    _last_request_time = {}
    
    # Domain-specific delays (in seconds)
    _domain_delays = {
        'yahoo.com': 2.0,
        'news.yahoo.com': 2.5,
        'default': 1.5
    }
    
    @classmethod
    def _get_domain(cls, url: str) -> str:
        """Extract domain from URL for rate limiting purposes."""
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        return domain if domain else 'default'
    
    @classmethod
    async def _throttle_requests(cls, url: str, min_delay: float = 1.0) -> None:
        """Ensure minimum delay between requests to the same domain."""
        domain = cls._get_domain(url)
        last_time = cls._last_request_time.get(domain, 0)
        now = time.time()
        
        # Calculate time to wait before next request
        elapsed = now - last_time
        if elapsed < min_delay:
            wait_time = min_delay - elapsed
            await asyncio.sleep(wait_time)
            
        # Update last request time
        cls._last_request_time[domain] = time.time()

    def _get_random_user_agent(self) -> str:
        """
        Get a random user agent string to use for requests.
        
        Returns:
            A random user agent string
        """
        user_agents = [
            # Chrome on Windows
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            
            # Firefox on Windows
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/117.0',
            'Mozilla/5.0 (Windows NT 10.0; WOW64; rv:109.0) Gecko/20100101 Firefox/117.0',
            
            # Chrome on macOS
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36',
            
            # Safari on macOS
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.5 Safari/605.1.15',
            
            # Firefox on macOS
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/117.0',
            
            # Linux
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/117.0'
        ]
        return random.choice(user_agents)
        
    def _get_yahoo_section_url(self, category: str, country: str = 'us') -> str:
        """
        Get the Yahoo News section URL for a given category and country.
        
        Args:
            category: News category (e.g., 'technology', 'business')
            country: Country code (e.g., 'us', 'uk')
            
        Returns:
            URL string or None if no matching section found
        """
        # Yahoo's URL structure is different for different sections
        # Some sections use /news/ prefix, others don't
        
        # Base URL for US
        if country.lower() == 'us':
            base_url = "https://news.yahoo.com"
        else:
            # For other countries, use country-specific subdomain
            base_url = f"https://{country.lower()}.news.yahoo.com"
    
        # Map categories to Yahoo News sections
        # Format: {'category': ('section_path', 'url_prefix')}
        section_map = {
            'technology': ('tech', 'news/technology/'),
            'business': ('business', 'business/'),
            'science': ('science', 'science/'),
            'health': ('health', 'health/'),
            'entertainment': ('entertainment', 'entertainment/'),
            'sports': ('sports', 'sports/'),
            'politics': ('politics', 'politics/'),
            'world': ('world', 'world/'),
            'us': ('us', 'us-news/'),
            'europe': ('europe', 'world/europe/'),
            'asia': ('asia', 'world/asia/'),
            'india': ('india', 'world/india/'),
            'middleeast': ('middle-east', 'world/middle-east/'),
            'latinamerica': ('latin-america', 'world/latin-america/')
        }
        
        # Get the section path and URL prefix
        section_info = section_map.get(category.lower())
        if not section_info:
            logger.warning(f"No section mapping found for category: {category}")
            return None
            
        section, url_prefix = section_info
        
        # Construct the final URL
        url = f"{base_url}/{url_prefix}"
        logger.info(f"Constructed Yahoo News URL: {url} for category: {category}, country: {country}")
        return url

    async def _scrape_yahoo_article_links(self, section_url: str, max_links: int = 5) -> List[str]:
        """
        Scrape article links from a Yahoo News section page with enhanced reliability.
        
        Args:
            section_url: URL of the Yahoo News section
            max_links: Maximum number of links to return
            
        Returns:
            List of article URLs
        """
        try:
            # Add random delay before making the request
            await asyncio.sleep(random.uniform(1.0, 3.0))
            
            # Get a random user agent
            user_agent = self._get_random_user_agent()
            
            # Configure headers to mimic a real browser
            headers = {
                'User-Agent': user_agent,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate, br',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache',
                'Referer': 'https://news.yahoo.com/',
                'Sec-Fetch-Dest': 'document',
                'Sec-Fetch-Mode': 'navigate',
                'Sec-Fetch-Site': 'same-origin',
                'Sec-Fetch-User': '?1'
            }
            
            logger.info(f"Fetching Yahoo News section: {section_url}")
            
            # Make the request directly with aiohttp for better control
            async with aiohttp.ClientSession() as session:
                try:
                    # First try with a direct request
                    async with session.get(section_url, headers=headers, timeout=30) as response:
                        if response.status != 200:
                            logger.error(f"Failed to fetch {section_url}: HTTP {response.status}")
                            return []
                        
                        html = await response.text()
                        
                        # Check if we got a captcha or block page
                        if any(x in html.lower() for x in ['captcha', 'challenge', 'access denied', 'blocked']):
                            logger.warning("Detected captcha or block page. Trying with different headers...")
                            
                            # Try with different headers
                            headers.update({
                                'Accept': 'text/html,application/xhtml+xml,application/xml',
                                'Accept-Language': 'en-US,en;q=0.9',
                                'User-Agent': self._get_random_user_agent()  # Get a different user agent
                            })
                            
                            async with session.get(section_url, headers=headers, timeout=30) as retry_response:
                                if retry_response.status != 200:
                                    logger.error(f"Retry failed for {section_url}: HTTP {retry_response.status}")
                                    return []
                                html = await retry_response.text()
                                
                except Exception as e:
                    logger.error(f"Error fetching {section_url}: {str(e)}")
                    return []
            
            soup = BeautifulSoup(html, 'html.parser')
            article_links = set()
            
            # Look for article containers - Yahoo's common patterns
            article_containers = []
            
            # Try different container patterns
            container_patterns = [
                # Modern Yahoo
                {'tag': 'div', 'attrs': {'data-test-locator': 'stream-item'}},
                {'tag': 'li', 'attrs': {'data-test-locator': 'stream-item'}},
                # Legacy Yahoo
                {'tag': 'div', 'class_': 'js-stream-content'},
                {'tag': 'div', 'class_': 'stream-item'},
                # Generic patterns
                {'tag': 'article'},
                {'tag': 'div', 'class_': 'news-item'},
                {'tag': 'div', 'class_': 'item'},
                {'tag': 'div', 'class_': 'story'},
                {'tag': 'div', 'class_': 'card'}
            ]
            
            for pattern in container_patterns:
                try:
                    containers = soup.find_all(**pattern)
                    if containers:
                        article_containers.extend(containers)
                        logger.debug(f"Found {len(containers)} containers with pattern: {pattern}")
                        if len(article_containers) >= max_links * 3:  # Don't need too many
                            break
                except Exception as e:
                    logger.debug(f"Error with container pattern {pattern}: {str(e)}")
            
            # If still no containers, try more generic approach
            if not article_containers:
                article_containers = soup.find_all(['article', 'div', 'li'])
            
            # Process each container to find article links
            for container in article_containers:
                try:
                    # Try to find a link in the container
                    link = None
                    
                    # Try different link patterns
                    link_patterns = [
                        {'name': 'a', 'href': True, 'class_': lambda x: x and 'js-content-viewer' in x},
                        {'name': 'a', 'href': True, 'class_': 'js-content-viewer'},
                        {'name': 'a', 'href': True, 'class_': 'js-stream-content'},
                        {'name': 'a', 'href': True, 'class_': 'js-content-builder'},
                        {'name': 'a', 'href': True, 'class_': 'js-content-builder'},
                        {'name': 'a', 'href': True}
                    ]
                    
                    for pattern in link_patterns:
                        try:
                            link = container.find(**pattern)
                            if link:
                                break
                        except:
                            continue
                    
                    if not link or not link.get('href'):
                        continue
                        
                    href = link['href'].strip()
                    if not href:
                        continue
                    
                    # Make relative URLs absolute
                    if href.startswith('//'):
                        href = f'https:{href}'
                    elif href.startswith('/'):
                        # Handle relative URLs based on the section URL
                        domain = '/'.join(section_url.split('/')[:3])  # Get https://domain.com
                        href = f"{domain}{href}"
                    
                    # Skip non-article URLs
                    if not ('news.yahoo.com' in href and ('/news/' in href or '/articles/' in href)):
                        continue
                        
                    # Skip video, live, and photo pages
                    if any(x in href.lower() for x in ['/video/', '/live/', '/photos/', '/slideshow/']):
                        continue
                    
                    # Clean up the URL
                    href = href.split('?')[0]  # Remove query parameters
                    href = href.split('#')[0]  # Remove fragments
                    
                    # Add to results if it looks like an article URL
                    if href and href not in article_links:
                        article_links.add(href)
                        if len(article_links) >= max_links * 2:  # Get extra to account for filtering
                            break
                            
                except Exception as e:
                    logger.debug(f"Error processing container: {str(e)}")
                    continue
            
            # If we didn't find enough links, try additional selectors
            if len(article_links) < max_links:
                additional_selectors = [
                    'a[href*="/news/"]',
                    'a[href*="/articles/"]',
                    'h3 a[href*="news.yahoo.com"]',
                    'h2 a[href*="news.yahoo.com"]',
                    'a[data-ylk*="headline"]',
                    'a[data-rapid_p*="headline"]',
                    'a[href*="article"]',
                    'a[class*="headline"]',
                    'a[class*="title"]',
                    'a[class*="link"]'
                ]
                
                for selector in additional_selectors:
                    try:
                        for link in soup.select(selector):
                            try:
                                href = link.get('href', '').strip()
                                if not href:
                                    continue
                                    
                                # Make relative URLs absolute
                                if href.startswith('//'):
                                    href = f'https:{href}'
                                elif href.startswith('/'):
                                    domain = '/'.join(section_url.split('/')[:3])
                                    href = f"{domain}{href}"
                                
                                # Skip if not a news article or already in our list
                                if ('news.yahoo.com' in href and 
                                    ('/news/' in href or '/articles/' in href) and 
                                    not any(x in href.lower() for x in ['/video/', '/live/', '/photos/']) and
                                    href not in article_links):
                                    
                                    # Clean up the URL
                                    href = href.split('?')[0]  # Remove query parameters
                                    href = href.split('#')[0]  # Remove fragments
                                    
                                    article_links.add(href)
                                    if len(article_links) >= max_links * 2:
                                        break
                            except Exception as e:
                                logger.debug(f"Error processing link with selector {selector}: {str(e)}")
                                continue
                                    
                        if len(article_links) >= max_links * 2:
                            break
                            
                    except Exception as e:
                        logger.debug(f"Error with selector '{selector}': {str(e)}")
                        continue
            
            # Convert set to list and limit to max_links
            links = list(article_links)[:max_links]
            
            # Log results
            if links:
                logger.info(f"Found {len(links)} article links for {section_url}")
                for i, link in enumerate(links[:3], 1):
                    logger.debug(f"Article link {i}: {link}")
            else:
                logger.warning(f"No article links found for {section_url}")
                # Log the first 500 chars of HTML for debugging
                logger.debug(f"First 500 chars of HTML: {html[:500]}...")
                
            return links
            
        except Exception as e:
            logger.error(f"Error in _scrape_yahoo_article_links: {str(e)}", exc_info=True)
            return []

    async def _fetch_yahoo_news(
        self,
        categories: List[str],
        country: str,
        language: str,
        results: Dict[str, Any],
        max_articles: int
    ) -> None:
        """
        Fetch news from Yahoo with enhanced reliability features:
        - Rotating user agents
        - Request delays with jitter
        - Proxy rotation
        - Better error handling and retries
        - Fallback to alternative sources
        
        Args:
            categories: Dictionary of category names to number of articles
            country: Country code for news localization
            language: Language code for news content
            results: Dictionary to store results
            max_articles: Maximum number of articles per category
        """
        logger.info("=== Starting Yahoo News Scraper ===")
        logger.info(f"Categories: {categories}")
        logger.info(f"Country: {country}, Language: {language}")
        
        # Add a random delay before starting to avoid detection
        initial_delay = random.uniform(1.0, 3.0)
        logger.debug(f"Initial delay: {initial_delay:.2f}s")
        await asyncio.sleep(initial_delay)
        
        for category in categories:
            try:
                logger.info(f"\n=== Processing category: {category} (target: {count} articles) ===")
                
                # Get the section URL for this category
                section_url = self._get_yahoo_section_url(category, country)
                if not section_url:
                    logger.error(f"Could not determine section URL for category: {category}")
                    results[category] = []
                    continue
                    
                logger.info(f"Section URL: {section_url}")
                
                # Scrape article links with retries
                max_retries = 2
                article_links = []
                
                for attempt in range(max_retries):
                    try:
                        logger.info(f"Attempt {attempt + 1}/{max_retries} to fetch article links...")
                        article_links = await self._scrape_yahoo_article_links(section_url, count * 2)  # Get extra links
                        if article_links:
                            logger.info(f"Found {len(article_links)} article links")
                            break
                        logger.warning(f"No article links found in attempt {attempt + 1}")
                    except Exception as e:
                        logger.error(f"Error in attempt {attempt + 1}: {str(e)}", exc_info=True)
                        if attempt == max_retries - 1:
                            logger.error(f"Failed to get article links after {max_retries} attempts")
                
                if not article_links:
                    logger.warning(f"No articles found for category: {category}")
                    results[category] = []
                    continue
                
                # Prepare article dictionaries for concurrent scraping
                article_dicts = [
                    {
                        'url': url,
                        'source_url': url,
                        'title': '',
                        'content': '',
                        'images': [],
                        'published_at': None,
                        'author': '',
                        'category': category,
                        'search_query': f"{category} news"
                    }
                    for url in article_links
                ]
                
                logger.info(f"Scraping {len(article_dicts)} articles concurrently...")
                
                # Use the concurrent scraper with 5 concurrent workers
                valid_articles = await self._scrape_articles_concurrently(article_dicts, max_workers=5)
                
                # Add category and search_query to each article
                for article in valid_articles:
                    article['category'] = category
                    article['search_query'] = f"{category} news"
                
                if valid_articles:
                    results[category] = valid_articles[:count]
                    results['total_articles'] = results.get('total_articles', 0) + len(valid_articles)
                    
                    # Log success
                    logger.info(f"Successfully scraped {len(valid_articles)}/{count} articles for category: {category}")
                    
                    # Save to JSON for debugging
                    response_data = {
                        'category': category,
                        'articles': valid_articles,
                        'timestamp': datetime.utcnow().isoformat(),
                        'count': len(valid_articles)
                    }
                    self._save_to_json(response_data, f"yahoo_{category}")
                else:
                    logger.warning(f"No valid articles found for category: {category}")
                    results[category] = []
                
            except Exception as e:
                logger.error(f"Error processing Yahoo category {category}: {str(e)}", exc_info=True)
                results[category] = []  # Ensure we return an empty list on error
        
        logger.info("=== Yahoo News scraping completed ===")
        logger.info(f"Total articles scraped: {results.get('total_articles', 0)}")

    async def _scrape_article_content(self, url: str, session: aiohttp.ClientSession, timeout: int = 30) -> Dict[str, Any]:
        """
        Scrape content from a single article URL.
        
        Args:
            url: Article URL
            session: aiohttp ClientSession for connection pooling
            timeout: Request timeout in seconds
            
        Returns:
            Dictionary with article content and metadata
        """
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://news.yahoo.com/',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1',
                'Cache-Control': 'max-age=0'
            }
            
            # Use the helper method to make the request
            html = await self._make_request(session, url, headers, timeout)
            if not html:
                return {'url': url, 'source_url': url, 'status': 'error: failed to fetch article'}
                
            soup = BeautifulSoup(html, 'html.parser')
            
            # Extract main content - this is a simplified version
            content = ''
            
            # Try different selectors for main content
            selectors = [
                'article',
                'div[class*="article-body"]',
                'div[class*="content"]',
                'div[class*="post-content"]',
                'div[class*="article-content"]',
                'div[itemprop="articleBody"]'
            ]
            
            for selector in selectors:
                content_element = soup.select_one(selector)
                if content_element:
                    # Clean up the content
                    for tag in content_element.select('script, style, nav, footer, aside, .ad, [class*="ad-"]'):
                        tag.decompose()
                        
                        # Get text with proper spacing
                        content = ' '.join(content_element.stripped_strings)
                        break
                
                # If no content found with selectors, fall back to body text
                if not content:
                    body = soup.find('body')
                    if body:
                        # Remove script and style elements
                        for script in body(['script', 'style']):
                            script.decompose()
                        content = ' '.join(body.stripped_strings)
                
                # Limit content length
                if len(content) > 10000:
                    content = content[:10000] + '...'
                
                # Extract all links from the article
                backlinks = []
                try:
                    for link in soup.find_all('a', href=True):
                        href = link.get('href', '').strip()
                        if href and not href.startswith('#'):
                            # Make relative URLs absolute
                            if href.startswith('/'):
                                base_url = '/'.join(url.split('/')[:3])
                                href = f"{base_url}{href}"
                            backlinks.append(href)
                except Exception as e:
                    logger.warning(f"Error extracting backlinks: {str(e)}")
                
                # Extract article title
                title = ''
                try:
                    # Try common title selectors
                    title_elem = soup.find('h1') or soup.find('title')
                    if title_elem:
                        title = title_elem.get_text(strip=True)
                        # Clean up the title (remove extra spaces, newlines, etc.)
                        title = ' '.join(title.split())
                except Exception as e:
                    logger.warning(f"Error extracting title: {str(e)}")
                
                # Fetch images using the title
                image_urls = []
                try:
                    if title:
                        image_urls = await self.fetch_images(title, max_results=5)
                except Exception as e:
                    logger.warning(f"Error fetching images: {str(e)}")
                
                # Extract video iframes and embeds
                video_link = ''
                try:
                    # First, try to find YouTube videos using the article title
                    if title:
                        video_url = await asyncio.get_event_loop().run_in_executor(
                            None,
                            lambda: self.scraper.scrape_youtube_video(title)
                        )
                        if video_url:
                            video_link = video_url
                            logger.info(f"Found YouTube video: {video_link}")
                    
                    # If no YouTube video found, look for embedded videos in the article
                    if not video_link:
                        video_sources = []
                        
                        # Check for iframe embeds (YouTube, Vimeo, etc.) - prioritize these
                        for iframe in soup.find_all('iframe'):
                            src = iframe.get('src', '')
                            if src and any(domain in src for domain in ['youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com']):
                                video_sources.append(src)
                        
                        # If no iframe found, check for video tags
                        if not video_sources:
                            for video in soup.find_all('video'):
                                src = video.get('src')
                                if src:
                                    video_sources.append(src)
                                else:
                                    # Check for source tags within video
                                    for source in video.find_all('source'):
                                        src = source.get('src')
                                        if src:
                                            video_sources.append(src)
                        
                        # Take the first video URL if any found
                        video_link = video_sources[0] if video_sources else ''
                    
                except Exception as e:
                    logger.warning(f"Error extracting videos: {str(e)}")
                    video_link = ''
                
                # Ensure we have a valid URL in the response
                article_data = {
                    'title': title,
                    'url': url,
                    'content': content,
                    'status': 'success',
                    'source': url,  # Changed from source_url to source
                    'backlinks': list(set(backlinks)),  # Remove duplicates
                    'image_links': image_urls[:5],  # Limit to 5 images
                    'video_links': video_link  # Single video URL as a string (not a list)
                }
                return article_data
                
        except asyncio.TimeoutError:
            return {'url': url, 'source': url, 'status': 'error: request timeout'}
        except Exception as e:
            logger.error(f"Error scraping article content from {url}: {str(e)}", exc_info=True)
            return {'url': url, 'source': url, 'status': f'error: {str(e)}'}




@staticmethod
def generate_schedule(
    categories: Dict[str, Dict[str, Any]],
    language: str = 'en',
    country: str = 'us',
    schedule_date: Optional[datetime.date] = None
) -> List[Dict[str, Any]]:
    """
    Generate a schedule for posting articles using exact times from the schedule.
    
    Args:
        categories: Dictionary of {
            category: {
                'count': int,
                'times': List[str]  # List of times in 'HH:MM' format
            }
        }
        language: Language code (e.g., 'en')
        country: Country code (e.g., 'us')
        schedule_date: Date for scheduling (defaults to today)
            
    Returns:
        List of scheduled items with category, scheduled time, and position
    """
    if schedule_date is None:
        schedule_date = datetime.utcnow().date()
    
    schedule = []
    position = 1
    
    for category, data in categories.items():
        count = data.get('count', 0)
        times = data.get('times', [])
        
        # If no times provided, use default scheduling
        if not times:
            default_time = datetime.combine(schedule_date, datetime.strptime('12:00', '%H:%M').time())
            for i in range(count):
                scheduled_time = default_time + timedelta(hours=i)
                schedule.append({
                    'category': category,
                    'scheduled_at': scheduled_time.isoformat(),
                    'position': position,
                    'language': language,
                    'country': country
                })
                position += 1
            continue
            
        # Schedule each article at the specified times
        for i in range(min(count, len(times))):
            try:
                # Parse the time string (e.g., '05:00')
                time_obj = datetime.strptime(times[i], '%H:%M').time()
                scheduled_time = datetime.combine(schedule_date, time_obj)
                
                schedule.append({
                    'category': category,
                    'scheduled_at': scheduled_time.isoformat(),
                    'position': position,
                    'language': language,
                    'country': country
                })
                position += 1
                
            except (ValueError, IndexError) as e:
                logger.warning(f"Invalid time format for {category} at index {i}: {e}")
    
    # Sort the schedule by scheduled time
    return sorted(schedule, key=lambda x: x['scheduled_at'])