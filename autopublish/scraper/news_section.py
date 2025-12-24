import asyncio
import logging
import random
import requests
import os
from datetime import datetime
import aiohttp
from typing import List, Dict, Any, Optional, Union, Tuple, Callable, Coroutine
from urllib.parse import urljoin, urlparse, quote_plus
from bs4 import BeautifulSoup
from .base import WebContentScraper

logger = logging.getLogger(__name__)


class BingScraper:
    """A class to handle Bing News scraping operations."""
    
    def __init__(self):
        """Initialize the BingScraper with default settings."""
        self.base_url = "https://www.bing.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
    async def fetch_news(
        self,
        categories: List[Dict[str, Any]],
        country: str = 'us',
        language: str = 'en',
        max_articles: int = 10
    ) -> Dict[str, Any]:
        """
        Fetch news from Bing with enhanced reliability features.
        
        Args:
            categories: List of dicts with 'name' (category name) and 'num' (number of articles)
            country: Country code for news localization (default: 'us')
            language: Language code for news content (default: 'en')
            max_articles: Maximum number of articles per category (default: 10)
            
        Returns:
            Dict containing articles organized by category and total count
            {
                'categories': {
                    'politics': [
                        {'title': '...', 'content': '...', 'url': '...'},
                        ...
                    ],
                    'technology': [...],
                    ...
                },
                'total_articles': 25
            }
        """
        results = {
            'categories': {},
            'total_articles': 0
        }
        
        logger.info("=== Starting Bing News Scraper ===")
        logger.info(f"Categories: {categories}")
        logger.info(f"Country: {country}, Language: {language}")
        
        web_scraper = WebContentScraper()
        
        for item in categories:
            category = item['name']
            num_articles = item['num']
            
            logger.info(f"Processing category: {category} (requested {num_articles} articles)")
            
            # Get the section URL for this category
            section_url = self._get_section_url(category, country, language)
            if not section_url:
                logger.warning(f"Could not find section URL for category: {category}")
                results['categories'][category] = []
                continue
                
            # Get article links (with extra for potential failures)
            try:
                links = await self._scrape_article_links(section_url, min_links=num_articles, country=country, language=language)
                
                if not links:
                    logger.warning(f"No article links found for {category}")
                    results['categories'][category] = []
                    continue
                    
                logger.info(f"Found {len(links)} articles for {category}, scraping content...")
                
                # Scrape the articles (synchronous call, no await needed)
                articles = web_scraper.scrape_multiple_urls(links, target_count=num_articles)
                
                # Process and store the scraped articles
                category_articles = []
                for article in articles:
                    if not article:
                        continue
                    category_articles.append({
                        'title': article.get('title', 'No title'),
                        'content': article.get('content', ''),
                        'url': article.get('url', ''),
                        'scraped_at': datetime.utcnow().isoformat()
                    })
                
                # Store the articles under their category
                results['categories'][category] = category_articles
                results['total_articles'] += len(category_articles)
                
                logger.info(f"Successfully scraped {len(category_articles)}/{num_articles} articles for {category}")
                
            except Exception as e:
                logger.error(f"Error processing category {category}: {str(e)}", exc_info=True)
                results['categories'][category] = []
        
        logger.info(f"Scraping complete. Total articles: {results['total_articles']}")
        return results

    def _get_section_url(self, category: str, country: str, language: str = 'en') -> Optional[str]:
        """
        Get the Bing News section URL for a given category, country, and language.
        
        Args:
            category: News category (e.g., 'politics', 'business', 'entertainment')
            country: Country code (e.g., 'us', 'uk')
            language: Language code (default: 'en')
            
        Returns:
            URL string or None if no matching section found
        """
        # Normalize inputs
        category = category.lower().strip()
        
        # Category to Bing News URL mapping
        category_mapping = {
            'general': 'https://www.bing.com/news',
            'world': 'https://www.bing.com/news/search',
            'business': 'https://www.bing.com/news/search',
            'entertainment': 'https://www.bing.com/news/search',
            'politics': 'https://www.bing.com/news/search',
            'scitech': 'https://www.bing.com/news/search',
            'technology': 'https://www.bing.com/news/search',
            'science': 'https://www.bing.com/news/search',
            'sports': 'https://www.bing.com/news/search',
            'health': 'https://www.bing.com/news/search',
        }
        
        # Bing News category parameters
        bing_categories = {
            'world': 'World',
            'business': 'Business',
            'entertainment': 'Entertainment',
            'politics': 'Politics',
            'scitech': 'Sci/Tech',
            'technology': 'Sci/Tech',
            'science': 'Sci/Tech',
            'sports': 'Sports',
            'health': 'Health'
        }
        
        # Get the base URL based on category
        base_url = category_mapping.get(category, 'https://www.bing.com/news')
        
        # For the general news page
        if category == 'general' or category not in bing_categories:
            return base_url
            
        # For category-specific pages
        bing_category = bing_categories[category]
        
        # Build the query parameters
        params = {
            'q': bing_category,
            'nvaug': f'[NewsVertical+Category="{self._get_bing_category_param(bing_category)}"]',
            'FORM': 'NSBABR'
        }
        
        # Add country and language parameters if needed
        if country and country.lower() != 'us':
            params['cc'] = country.upper()
        if language and language.lower() != 'en':
            params['setlang'] = language.lower()
            
        # Build the full URL with parameters
        from urllib.parse import urlencode
        return f"{base_url}?{urlencode(params)}"
    
    def _get_bing_category_param(self, category: str) -> str:
        """Get the Bing category parameter for the given category name."""
        param_mapping = {
            'World': 'rt_World',
            'Business': 'rt_Business',
            'Entertainment': 'rt_Entertainment',
            'Politics': 'rt_Politics',
            'Sci/Tech': 'rt_ScienceAndTechnology',
            'Sports': 'rt_Sports',
            'Health': 'rt_Health'
        }
        return param_mapping.get(category, 'rt_World')
    
    async def _scrape_article_links(self, section_url: str, min_links: int = 10, **kwargs) -> List[str]:
        """
        Scrape article links from a Bing News search results page.
        
        Args:
            section_url: URL of the Bing News search results page
            min_links: Minimum number of links to collect
            **kwargs: Additional arguments (country, language, etc.)
            
        Returns:
            List of article URLs
        """
        article_links = []
        try:
            # Add headers to mimic a real browser
            headers = {
                **self.headers,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Referer': 'https://www.bing.com/'
            }
            
            # Make the request
            response = requests.get(section_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # First, try to find news cards with article links
            for card in soup.select('.news-card, .tile'):
                link = card.select_one('a[href^="http"]')
                if link and link.get('href'):
                    href = link['href']
                    # Skip internal Bing links and tracking URLs
                    if not any(x in href for x in ['bing.com', 'javascript:', '#']):
                        article_links.append(href)
                        if len(article_links) >= min_links * 2:  # Get extra links as backup
                            break
            
            # If not enough links found, try alternative selectors
            if len(article_links) < min_links:
                for link in soup.select('a[href^="http"]'):
                    href = link.get('href')
                    if (href and 
                        not any(x in href for x in ['bing.com', 'javascript:', '#']) and 
                        href not in article_links):
                        article_links.append(href)
                        if len(article_links) >= min_links * 2:
                            break
            
            # Log the number of links found
            logging.info(f"Found {len(article_links)} article links at {section_url}")
            
        except Exception as e:
            logging.error(f"Error scraping article links from {section_url}: {str(e)}")
            
        return article_links[:min_links * 2]  # Return up to 2x requested links as backup


class YahooScraper:
    """A class to handle Yahoo News scraping operations."""
    
    def __init__(self, scraping_service=None):
        """Initialize the YahooScraper with default settings.
        
        Args:
            scraping_service: Optional ScrapingService instance to use for HTTP requests with proxy support
        """
        self.base_url = "https://news.yahoo.com/"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        self.scraping_service = scraping_service
        
    async def fetch_news(
        self,
        categories: List[Dict[str, Any]],
        country: str = 'us',
        language: str = 'en',
        max_articles: int = 10
    ) -> Dict[str, Any]:
        """
        Fetch news from Yahoo with enhanced reliability features.
        
        Args:
            categories: List of dicts with 'name' (category name) and 'num' (number of articles)
            country: Country code for news localization (default: 'us')
            language: Language code for news content (default: 'en')
            max_articles: Maximum number of articles per category (default: 10)
            
        Returns:
            Dict containing articles organized by category and total count
            {
                'categories': {
                    'politics': [
                        {'title': '...', 'content': '...', 'url': '...'},
                        ...
                    ],
                    'technology': [...],
                    ...
                },
                'total_articles': 25
            }
        """
        results = {
            'categories': {},
            'total_articles': 0
        }
        
        logger.info("=== Starting Yahoo News Scraper ===")
        logger.info(f"Categories: {categories}")
        logger.info(f"Country: {country}, Language: {language}")
        
        web_scraper = WebContentScraper()
        
        for item in categories:
            category = item['name']
            num_articles = item['num']
            
            logger.info(f"Processing category: {category} (requested {num_articles} articles)")
            
            # Get the section URL for this category
            section_url = self._get_section_url(category, country, language)
            if not section_url:
                logger.warning(f"Could not find section URL for category: {category}")
                results['categories'][category] = []
                continue
                
            # Get article links (with extra for potential failures)
            try:
                links = await self._scrape_article_links(section_url, min_links=num_articles, country=country, language=language)
                
                if not links:
                    logger.warning(f"No article links found for {category}")
                    results['categories'][category] = []
                    continue
                    
                logger.info(f"Found {len(links)} articles for {category}, scraping content...")
                
                # Scrape the articles (synchronous call, no await needed)
                articles = web_scraper.scrape_multiple_urls(links, target_count=num_articles)
                
                # Process and store the scraped articles
                category_articles = []
                for article in articles:
                    if not article:
                        continue
                    category_articles.append({
                        'title': article.get('title', 'No title'),
                        'content': article.get('content', ''),
                        'url': article.get('url', ''),
                        'scraped_at': datetime.utcnow().isoformat()
                    })
                
                # Store the articles under their category
                results['categories'][category] = category_articles
                results['total_articles'] += len(category_articles)
                
                logger.info(f"Successfully scraped {len(category_articles)}/{num_articles} articles for {category}")
                
            except Exception as e:
                logger.error(f"Error processing category {category}: {str(e)}", exc_info=True)
                results['categories'][category] = []
        
        logger.info(f"Scraping complete. Total articles: {results['total_articles']}")
        return results


    
    def _get_section_url(self, category: str, country: str, language: str = 'english') -> Optional[str]:
        """
        Get the Yahoo News section URL for a given category, country, and language.
        
        Args:
            category: News category in English (e.g., 'politics', 'health', 'entertainment')
            country: Country code (e.g., 'us', 'uk')
            language: Language ('english' or 'french')
            
        Returns:
            URL string or None if no matching section found
        """
        # Normalize inputs
        language = language.lower()
        category = category.lower().strip()
        
        # English to French category mapping
        en_to_fr = {
            'politics': 'politique',
            'world': 'monde',
            'science': 'sciences',
            'entertainment': 'divertissement',
            'health': 'sante',
            'lifestyle': 'style',
            'people': 'people',
            'celebrities': 'people',
            'technology': 'technologie',
            'business': 'affaires',
            'sports': 'sports',
            'us': 'monde/etats-unis',
            'france': 'france',
            'europe': 'europe',
            'africa': 'monde/afrique',
            'asia': 'monde/asie',
            'middle east': 'monde/moyen-orient'
        }
        
        if language == 'french':
            # French URL handling
            base_url = "https://fr.news.yahoo.com"
            
            # Special cases for French URLs
            if category == 'lifestyle':
                return "https://fr.style.yahoo.com/"
            elif category in ['people', 'celebrities']:
                return f"{base_url}/people/"
            
            # Get French category name or use original if not found
            fr_category = en_to_fr.get(category, category)
            
            # Special handling for country-specific French URLs
            if country.lower() == 'fr':
                if category in ['politics', 'economy', 'society']:
                    return f"{base_url}/{fr_category}/france/"
                
            # Handle French country pages
            if category == 'us':
                return f"{base_url}/monde/etats-unis/"
            elif category == 'uk':
                return f"{base_url}/monde/royaume-uni/"
            elif category in en_to_fr:
                return f"{base_url}/{fr_category}/"
                
            # Default French URL pattern
            return f"{base_url}/{fr_category}/"
            
        else:  # English (default)
            base_url = "https://news.yahoo.com"
            
            # Special cases for English URLs
            if category in ['entertainment', 'health', 'lifestyle']:
                return f"https://www.yahoo.com/{category}/"
            elif category in ['people', 'celebrities']:
                return "https://www.yahoo.com/entertainment/celebrity/"
            elif category == 'us':
                return f"{base_url}/us-news/"
            elif category == 'uk':
                return f"{base_url}/uk/"
                
            # Default English URL pattern for news categories
            return f"{base_url}/{category.replace(' ', '-')}/"
    
    async def _scrape_article_links(self, section_url: str, min_links: int = 10, country: str = 'us', language: str = 'en-US') -> List[str]:
        """
        Scrape article links from a section page, collecting extra links beyond the minimum.
        
        Args:
            section_url: URL of the section to scrape
            min_links: Minimum number of links needed (will collect more to account for failures)
            country: Country code for regional content (e.g., 'us', 'uk', 'ca')
            language: Language code for content (e.g., 'en-US', 'fr-FR', 'es-ES')
            
        Returns:
            List of article URLs (more than requested to account for potential failures)
        """
        # Calculate target number of links to collect (25% more than min_links, but at least 5 more)
        target_links = max(min_links * 2, min_links + 5, 10)  # At least 10, or min_links*2, or min_links+5, whichever is larger
        logger.info(f"Scraping article links from: {section_url} (Country: {country}, Language: {language})")
        
        # Set headers to mimic a browser with specified language and regional settings
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': f"{language},{language.split('-')[0]};q=0.9,en;q=0.8",
            'Accept-Encoding': 'gzip, deflate, br',
            'Referer': f'https://{country}.yahoo.com/',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'X-Forwarded-For': '.'.join([str(random.randint(1, 255)) for _ in range(4)]),  # Random IP for regional content
            'X-Client-Data': f'country={country.upper()}&lang={language}'  # Additional hints for regional content
        }
        
        try:
            # Make the request using the scraping service if available, otherwise fall back to requests
            if hasattr(self, 'scraping_service') and self.scraping_service and hasattr(self.scraping_service, '_fetch_url_async'):
                # Create a session for the async request
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Use the service's fetch method which handles proxies and retries
                    result = await self.scraping_service._fetch_url_async(session, section_url, headers=headers)
                    if not result or 'content' not in result:
                        logger.error(f"Failed to fetch {section_url} using proxy")
                        return []
                    html_content = result['content']
            else:
                # Fall back to direct requests if no scraping service is available
                response = requests.get(section_url, headers=headers, timeout=30)
                response.raise_for_status()
                html_content = response.text
            
            # Parse the HTML
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find all article links
            article_links = []
            
            # Common patterns for article links in Yahoo News
            link_selectors = [
                'a[href*=".html"]',  # Links containing .html
                'a[data-rapid_p*="Article"]',  # Data attributes used by Yahoo
                'a[data-ylk*="pkgt:news"]',  # Yahoo link tracking
                'a[data-ya-track*="news"]',  # Another Yahoo tracking pattern
                'h3 a',  # Common pattern for article headlines
                'a[data-content-id]'  # Content ID links
            ]
            
            # Try different selectors until we find links
            for selector in link_selectors:
                if not article_links:
                    links = soup.select(selector)
                    for link in links:
                        href = link.get('href')
                        if href and '.html' in href and 'yahoo.com' not in href:
                            # Handle relative URLs
                            if not href.startswith(('http://', 'https://')):
                                # Get the base URL from the section URL
                                base_url = f"{urlparse(section_url).scheme}://{urlparse(section_url).netloc}"
                                href = urljoin(base_url, href)
                            
                            # Clean the URL
                            href = href.split('?')[0]  # Remove query parameters
                            href = href.split('#')[0]  # Remove fragments
                            
                            # Make sure it's a news article URL
                            if '/video/' not in href and '/photos/' not in href and href not in article_links:
                                article_links.append(href)
                                
                                # Continue collecting all links
                else:
                    break
            
            # Log the number of links found
            logger.info(f"Found {len(article_links)} article links")
            
            # Return all unique links while preserving order
            seen = set()
            unique_links = []
            for link in article_links:
                if link not in seen:
                    seen.add(link)
                    unique_links.append(link)
            
            # Log results
            if len(unique_links) < min_links:
                logger.warning(f"Found only {len(unique_links)} unique article links (wanted at least {min_links})")
            else:
                logger.info(f"Collected {len(unique_links)} article links (target was {target_links} for {min_links} needed)")
                
            return unique_links
            
        except requests.RequestException as e:
            logger.error(f"Error fetching {section_url}: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error while scraping {section_url}: {str(e)}", exc_info=True)
            return []
    
    async def _scrape_articles(self, article_dicts: List[Dict], max_workers: int = 5) -> List[Dict]:
        """
        Scrape article contents concurrently.
        
        Args:
            article_dicts: List of article dictionaries containing URLs
            max_workers: Maximum number of concurrent workers
            
        Returns:
            List of scraped article data
        """
        # Implement concurrent scraping logic
        return []
    
    def _save_to_json(self, data: Dict, filename: str) -> None:
        """
        Save data to a JSON file for debugging.
        
        Args:
            data: Data to save
            filename: Base filename (without extension)
        """
        # Implement JSON saving logic
        pass


class GoogleNewsScraper:
    """A class to handle Google News scraping operations."""
    
    def __init__(self):
        """Initialize the GoogleNewsScraper with default settings."""
        self.base_url = "https://news.google.com"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
        
        # Google News topic IDs for different categories
        self.topic_ids = {
            'home': None,  # Home page has no topic ID
            'world': 'CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx1YlY4U0JXVnVMVWRDR2dKUVN5Z0FQAQ',
            'business': 'CAAqKggKIiRDQkFTRlFvSUwyMHZNRGx6TVdZU0JXVnVMVWRDR2dKUVN5Z0FQAQ',
            'technology': 'CAAqKggKIiRDQkFTRlFvSUwyMHZNRGRqTVhZU0JXVnVMVWRDR2dKUVN5Z0FQAQ',
            'entertainment': 'CAAqKggKIiRDQkFTRlFvSUwyMHZNREpxYW5RU0JXVnVMVWRDR2dKUVN5Z0FQAQ',
            'science': 'CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp0Y1RjU0JXVnVMVWRDR2dKUVN5Z0FQAQ',
            'health': 'CAAqJQgKIh9DQkFTRVFvSUwyMHZNR3QwTlRFU0JXVnVMVWRDS0FBUAE',
            'sports': 'CAAqKggKIiRDQkFTRlFvSUwyMHZNRFp1ZEdvU0JXVnVMVWRDR2dKUVN5Z0FQAQ',
            # Add more categories as needed
        }
        
        # Map common category names to Google's category names
        self.category_mapping = {
            'general': 'home',
            'tech': 'technology',
            'sci': 'science',
            'sci/tech': 'technology',
            'sci-tech': 'technology',
            'scitech': 'technology',
            'sport': 'sports',
            'entertain': 'entertainment',
            'business': 'business',
            'world': 'world',
            'health': 'health'
        }
        
    async def fetch_news(
        self,
        categories: List[Dict[str, Any]],
        country: str = 'us',
        language: str = 'en',
        max_articles: int = 10
    ) -> Dict[str, Any]:
        """
        Fetch news from Google News with enhanced reliability features.
        
        Args:
            categories: List of dicts with 'name' (category name) and 'num' (number of articles)
            country: Country code for news localization (default: 'us')
            language: Language code for news content (default: 'en')
            max_articles: Maximum number of articles per category (default: 10)
            
        Returns:
            Dict containing articles organized by category and total count
            {
                'categories': {
                    'politics': [
                        {'title': '...', 'content': '...', 'url': '...'},
                        ...
                    ],
                    'technology': [...],
                    ...
                },
                'total_articles': 25
            }
        """
        results = {
            'categories': {},
            'total_articles': 0
        }
        
        logger.info("=== Starting Google News Scraper ===")
        logger.info(f"Categories: {categories}")
        logger.info(f"Country: {country}, Language: {language}")
        
        web_scraper = WebContentScraper()
        
        for item in categories:
            category = item['name'].lower()
            num_articles = min(item['num'], max_articles)  # Ensure we don't exceed max_articles
            
            logger.info(f"Processing category: {category} (requested {num_articles} articles)")
            
            # Get the section URL for this category
            section_url = self._get_section_url(category, country, language)
            if not section_url:
                logger.warning(f"Could not find section URL for category: {category}")
                results['categories'][category] = []
                continue
                
            # Get article links (with extra for potential failures)
            try:
                links = await self._scrape_article_links(
                    section_url, 
                    min_links=num_articles, 
                    country=country, 
                    language=language
                )
                
                if not links:
                    logger.warning(f"No article links found for {category}")
                    results['categories'][category] = []
                    continue
                    
                logger.info(f"Found {len(links)} articles for {category}, scraping content...")
                
                # Scrape the articles (synchronous call, no await needed)
                articles = web_scraper.scrape_multiple_urls(links, target_count=num_articles)
                
                # Process and store the scraped articles
                category_articles = []
                for article in articles:
                    if not article:
                        continue
                    category_articles.append({
                        'title': article.get('title', 'No title'),
                        'content': article.get('content', ''),
                        'url': article.get('url', ''),
                        'scraped_at': datetime.utcnow().isoformat()
                    })
                
                # Store the articles under their category
                results['categories'][category] = category_articles
                results['total_articles'] += len(category_articles)
                
                logger.info(f"Successfully scraped {len(category_articles)}/{num_articles} articles for {category}")
                
            except Exception as e:
                logger.error(f"Error processing category {category}: {str(e)}", exc_info=True)
                results['categories'][category] = []
        
        logger.info(f"Scraping complete. Total articles: {results['total_articles']}")
        return results
    
    def _get_section_url(self, category: str, country: str, language: str = 'en') -> Optional[str]:
        """
        Get the Google News section URL for a given category, country, and language.
        
        Args:
            category: News category (e.g., 'politics', 'business', 'entertainment')
            country: Country code (e.g., 'us', 'uk')
            language: Language code (e.g., 'en', 'es', 'fr')
            
        Returns:
            URL string or None if no matching section found
        """
        # Normalize inputs
        category = category.lower().strip()
        country = country.upper()
        language = language.lower()
        
        # Map common category names to Google's category names
        mapped_category = self.category_mapping.get(category, category)
        
        # Get the topic ID for the category
        topic_id = self.topic_ids.get(mapped_category)
        
        # Build the base URL
        if mapped_category == 'home' or topic_id is None:
            # Home page URL
            return f"{self.base_url}/home?hl={language}-{country}&gl={country}&ceid={country}:{language}"
        else:
            # Category page URL
            return f"{self.base_url}/topics/{topic_id}?hl={language}-{country}&gl={country}&ceid={country}:{language}"
    
    async def _scrape_article_links(
        self, 
        section_url: str, 
        min_links: int = 10, 
        country: str = 'us', 
        language: str = 'en'
    ) -> List[Dict[str, str]]:
        """
        Scrape article titles and links from a Google News section page.
        
        Args:
            section_url: URL of the section to scrape
            min_links: Minimum number of articles needed (will collect more to account for failures)
            country: Country code for regional content (e.g., 'us', 'uk', 'ca')
            language: Language code for content (e.g., 'en', 'es', 'fr')
            
        Returns:
            List of dictionaries containing article titles and URLs
            [{'title': 'Article Title', 'url': 'https://...'}, ...]
        """
        # Calculate target number of links to collect (25% more than min_links, but at least 5 more)
        target_links = max(min_links * 2, min_links + 5, 10)
        logger.info(f"Scraping article links from: {section_url} (Country: {country}, Language: {language})")
        
        # Set headers with language and regional settings
        headers = self.headers.copy()
        headers.update({
            'Accept-Language': f"{language}-{country},{language};q=0.9,en;q=0.8",
            'Referer': f'https://news.google.com/home?hl={language}-{country}&gl={country}&ceid={country}:{language}'
        })
        
        try:
            # Make the request
            response = requests.get(section_url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Parse the HTML
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Find all articles - Google News uses a specific structure
            articles_data = []
            
            # Find all article elements
            articles = soup.find_all('article')
            
            # If no articles found, try alternative selectors
            if not articles:
                articles = soup.select('div[role="listitem"], div[jsname*="jqWkF"]')
            
            # Extract titles and links from articles
            for article in articles:
                # First try to find title in gPFEn class (Google News specific)
                title_elem = article.find('a', class_='gPFEn')
                
                # Fall back to other selectors if not found
                if not title_elem:
                    title_elem = article.find(['h3', 'h4', 'h2', 'a'])
                
                if not title_elem:
                    continue
                
                # Get the title text and clean it up
                title = title_elem.get_text(strip=True)
                if not title:
                    continue
                
                # Find the link element
                link = article.find('a', href=True)
                if not link:
                    continue
                
                href = link.get('href', '').strip()
                if not href:
                    continue
                
                # Handle relative URLs (common in Google News)
                if href.startswith('./'):
                    # Convert relative URL to absolute
                    href = f"{self.base_url}{href[1:]}"
                elif href.startswith('.'):
                    # Handle any other relative paths
                    href = f"{self.base_url}{href}"
                elif href.startswith('/'):
                    # Handle root-relative URLs
                    href = f"{self.base_url}{href}"
                elif not href.startswith(('http://', 'https://')):
                    # Handle any other non-absolute URLs
                    href = f"{self.base_url}/{href}"
                
                # Handle Google News redirect URLs (they contain the actual URL in parameters)
                if 'news.google.com' in href and ('/articles/' in href or '/read' in href):
                    try:
                        # Parse the URL to get the query parameters
                        from urllib.parse import parse_qs, urlparse
                        parsed = urlparse(href)
                        query = parse_qs(parsed.query)
                        
                        # The actual URL might be in the 'url' parameter or in the path
                        if 'url' in query:
                            href = query['url'][0]
                        elif '/read' in parsed.path:
                            # For /read/ URLs, we can use the URL as is
                            href = f"{self.base_url}{parsed.path}"
                    except Exception as e:
                        logger.debug(f"Error parsing Google News URL {href}: {str(e)}")
                        continue
                
                # Clean up the URL
                href = href.split('&ved=')[0]  # Remove tracking parameters
                href = href.split('?utm_')[0]  # Remove UTM parameters
                
                # Create article data dictionary
                article_data = {
                    'title': title,
                    'url': href
                }
                
                # Add to our list if it's not a duplicate
                if not any(a['url'] == href for a in articles_data):
                    articles_data.append(article_data)
                    
                    # Stop if we've collected enough articles
                    if len(articles_data) >= target_links:
                        break
            
            # Log the number of links found
            logger.info(f"Found {len(articles_data)} articles")
            
            # Log results
            if len(articles_data) < min_links:
                logger.warning(f"Found only {len(articles_data)} articles (wanted at least {min_links})")
            else:
                logger.info(f"Collected {len(articles_data)} articles (target was {target_links} for {min_links} needed)")
                
            return articles_data
            
        except requests.RequestException as e:
            logger.error(f"Error fetching {section_url}: {str(e)}")
            return []
        except Exception as e:
            logger.error(f"Error scraping article links from {section_url}: {str(e)}")
            return []
    
    async def _scrape_articles(self, article_dicts: List[Dict], max_workers: int = 5) -> List[Dict]:
        """
        Scrape article contents using the title to get better search results.
        
        Args:
            article_dicts: List of article dictionaries containing titles and URLs
            max_workers: Maximum number of concurrent workers (not used in this implementation)
            
        Returns:
            List of scraped article data with title, content, and URL
        """
        
        web_scraper = WebContentScraper()
        scraped_articles = []
        
        for article in article_dicts:
            if not article or 'title' not in article:
                continue
                
            # Use the title to search and scrape the article content
            scraped = web_scraper.scrape_from_title(article['title'])
            
            if scraped and 'content' in scraped and scraped['content']:
                # If we successfully scraped content, use that
                scraped_articles.append({
                    'title': scraped.get('title', article.get('title', 'No title')),
                    'content': scraped['content'],
                    'url': scraped.get('url', article.get('url', '')),
                    'scraped_at': datetime.utcnow().isoformat()
                })
            elif 'url' in article and article['url']:
                # If title-based scraping failed, fall back to direct URL scraping
                try:
                    direct_scrape = web_scraper.scrape_url(article['url'])
                    if direct_scrape and 'content' in direct_scrape and direct_scrape['content']:
                        scraped_articles.append({
                            'title': direct_scrape.get('title', article.get('title', 'No title')),
                            'content': direct_scrape['content'],
                            'url': direct_scrape.get('url', article.get('url', '')),
                            'scraped_at': datetime.utcnow().isoformat()
                        })
                except Exception as e:
                    logger.warning(f"Failed to scrape {article.get('url', 'unknown')}: {str(e)}")
            
            # Add a small delay to be polite to servers
            await asyncio.sleep(1)
            
        return scraped_articles
        for article in article_dicts:
            title = article.get('title')
            if not title:
                continue
                
            # Try to get content using the title
            scraped = scraper.scrape_from_title(title)
            
            if scraped and scraped.get('content'):
                # Use the scraped content if successful
                article.update({
                    'content': scraped['content'],
                    'url': scraped['url'],  # Use the final URL after any redirects
                    'content_length': len(scraped['content'])
                })
                scraped_articles.append(article)
            
            # Small delay to be nice to servers
            import time
            time.sleep(1)
        
        return scraped_articles
    
    def _save_to_json(self, data: Dict, filename: str) -> None:
        """
        Save data to a JSON file for debugging.
        
        Args:
            data: Data to save
            filename: Base filename (without extension)
        """
        # Implement JSON saving logic if needed
        pass

class GNewsFetcher:
    """
    A class to handle fetching news from GNews API.
    Handles API requests, rate limiting, and response processing.
    """
    
    def __init__(self, api_key: str = None):
        """
        Initialize the GNewsFetcher with API key and WebContentScraper.
        
        Args:
            api_key: GNews API key. If not provided, will try to get from environment variable GNEWS_API_KEY.
        """
        self.api_key = api_key or os.getenv('GNEWS_API_KEY', 'c3064f083b58fc9b4ab20a19cfe2aebf')
        self.base_url = "https://gnews.io/api/v4/top-headlines"

        self.web_scraper = WebContentScraper()
        
    async def fetch_articles(
        self, 
        query: str, 
        category: str = None,
        country: str = 'us', 
        language: str = 'en',
        max_articles: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Fetch news articles from GNews API with full content.
        
        Args:
            query: Search query or topic
            category: News category (optional)
            country: Country code (default: 'us')
            language: Language code (default: 'en')
            max_articles: Maximum number of articles to fetch (default: 10)
            
        Returns:
            List of article dictionaries with full content and metadata
        """
        params = {
            'token': self.api_key,
            'lang': language,
            'country': country.lower(),
            'max': min(max_articles * 2, 100),  # Get more to account for potential failures
            'q': query or ''
        }
        
        if category and category.lower() != 'general':
            params['topic'] = category.lower()
        
        try:
            # Get article metadata from GNews API
            async with aiohttp.ClientSession() as session:
                async with session.get(self.base_url, params=params) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"GNews API error: {response.status} - {error_text}")
                        return []
                        
                    data = await response.json()
                    articles = data.get('articles', [])
                    
                    # Process initial article metadata
                    processed_articles = []
                    
                    # Process articles one by one to get full content
                    for i, article in enumerate(articles):
                        if len(processed_articles) >= max_articles:
                            break
                            
                        try:
                            # Process basic article info
                            processed = self._process_article(article, category)
                            if not processed or not processed.get('url'):
                                continue
                            
                            # Scrape full content for this article
                            url = processed['url']
                            scraped = self.web_scraper.scrape_url(url)
                            
                            if scraped and 'content' in scraped and scraped['content']:
                                # Update with scraped content
                                processed.update({
                                    'content': scraped['content'],
                                    'title': scraped.get('title', processed['title']),
                                    'image_url': scraped.get('image_url', processed.get('image_url', ''))
                                })
                                
                                # Only add if we got valid content
                                if len(processed['content']) > 50:  # Ensure we have meaningful content
                                    processed_articles.append(processed)
                                    
                            # Add a small delay between requests
                            if i < len(articles) - 1:
                                await asyncio.sleep(1)
                                
                        except Exception as e:
                            logger.warning(f"Error processing article {i+1}: {str(e)}")
                            continue
                    
                    return processed_articles
                    
        except Exception as e:
            logger.error(f"Error in GNewsFetcher: {str(e)}", exc_info=True)
            return []
    
    def _process_article(self, article: Dict[str, Any], category: str = None) -> Dict[str, Any]:
        """
        Process and clean a single article from GNews API.
        
        Args:
            article: Raw article data from GNews API
            category: Article category
            
        Returns:
            Processed article dictionary with full content or None if processing fails
        """
        try:
            article_url = article.get('url', '').strip()
            if not article_url:
                logger.warning("No URL found in article")
                return None

            # Extract domain from URL
            parsed_url = urlparse(article_url)
            domain = parsed_url.netloc.replace('www.', '')
            
            # Get the full content using the web scraper
            logger.info(f"Scraping full article content from: {article_url}")
            scraped = self.web_scraper.scrape_url(article_url)
            
            if not scraped or not scraped.get('content'):
                logger.warning(f"Failed to scrape content from {article_url}")
                return None

            # Extract and clean the content
            content = scraped['content']
            if len(content) < 100:  # Minimum content length
                logger.warning(f"Content too short from {article_url}")
                return None

            # Format published date
            published_at = article.get('publishedAt', '')
            if published_at:
                try:
                    # Convert ISO format to datetime and back to ensure consistency
                    dt = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
                    published_at = dt.isoformat()
                except (ValueError, AttributeError):
                    published_at = datetime.utcnow().isoformat()
            else:
                published_at = datetime.utcnow().isoformat()

            # Build the article data
            return {
                'title': article.get('title', 'No title'),
                'content': content,
                'url': article_url,
                'image_url': article.get('image', ''),
                'published_at': published_at,
                'source': {
                    'name': article.get('source', {}).get('name', domain),
                    'url': f"{parsed_url.scheme}://{parsed_url.netloc}" if parsed_url.scheme and parsed_url.netloc else ''
                },
                'category': category.lower() if category else 'general',
                'language': article.get('language', 'en'),
                'metadata': {
                    'api': 'gnews',
                    'retrieved_at': datetime.utcnow().isoformat(),
                    'content_source': 'full_scrape'
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing article: {str(e)}", exc_info=True)
            return None
    
    async def fetch_by_category(
        self, 
        categories: List[Dict[str, Any]], 
        country: str = 'us', 
        language: str = 'en',
        max_articles_per_category: int = 5
    ) -> Dict[str, Any]:
        """
        Fetch articles for multiple categories with full content.
        
        Args:
            categories: List of dicts with 'name' (category) and 'count' (number of articles)
            country: Country code (default: 'us')
            language: Language code (default: 'en')
            max_articles_per_category: Maximum articles per category (default: 5)
            
        Returns:
            Dictionary with category as key and list of articles with full content
        """
        results = {}
        
        for category_data in categories:
            category_name = category_data.get('name')
            article_count = category_data.get('count', max_articles_per_category)
            
            try:
                # Use a simple query for the category
                query = f"{category_name} news"
                
                # Fetch articles with full content
                articles = await self.fetch_articles(
                    query=query,
                    category=category_name,
                    country=country,
                    language=language,
                    max_articles=article_count
                )
                
                # Sort by published date if available
                sorted_articles = sorted(
                    articles,
                    key=lambda x: x.get('published_at', ''), 
                    reverse=True
                )
                
                # Store the results with the requested count
                results[category_name] = sorted_articles[:article_count]
                logger.info(f"Fetched {len(sorted_articles)}/{article_count} articles for category: {category_name}")
                
            except Exception as e:
                logger.error(f"Error fetching category {category_name}: {str(e)}", exc_info=True)
                results[category_name] = []
        
        return results

