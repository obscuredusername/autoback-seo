import json
import os
import random
import re
import requests
import sys
import threading
import time
import traceback
from bs4 import BeautifulSoup
from urllib.parse import urlparse, unquote
from .utils import retry

class WebContentScraper:
    def __init__(self):
        self.session = requests.Session()
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.59',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        self.session.headers.update({
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        self.default_timeout = (10, 20)

    @retry(max_retries=3, initial_delay=1, max_delay=10, backoff_factor=2)
    def search_duckduckgo(self, keyword, country_code='us', language='en', max_results=25):
        try:
            search_url = "https://duckduckgo.com/"
            params = {'q': keyword, 't': 'h_', 'ia': 'web'}
            self.session.headers.update({'User-Agent': random.choice(self.user_agents)})
            response = self.session.get(search_url, params={'q': keyword}, timeout=self.default_timeout)
            if response.status_code == 200:
                search_params = {
                    'q': keyword,
                    'kl': f'{country_code}-{language}',
                    't': 'h_',
                    'ia': 'web',
                    's': '0'
                }
                time.sleep(1)
                response = self.session.get(
                    'https://duckduckgo.com/html/',
                    params=search_params,
                    timeout=self.default_timeout,
                    headers={
                        'User-Agent': random.choice(self.user_agents),
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.5',
                        'Accept-Encoding': 'gzip, deflate',
                        'Referer': 'https://duckduckgo.com',
                        'DNT': '1',
                        'Connection': 'keep-alive',
                        'Upgrade-Insecure-Requests': '1'
                    }
                )
                if response.status_code == 200:
                    soup = BeautifulSoup(response.content, 'html.parser')
                    links = []
                    results = soup.find_all('div', class_='result')
                    for result in results:
                        link = result.find('a', class_='result__a')
                        if not link:
                            continue
                        href = link.get('href', '')
                        if href.startswith('/'):
                            href = 'https://duckduckgo.com' + href
                        if 'duckduckgo.com/l/?uddg=' in href:
                            try:
                                href = unquote(href.split('uddg=')[-1].split('&')[0])
                            except:
                                continue
                        if href and href.startswith('http') and not any(x in href.lower() for x in ['duckduckgo.com', 'duck.co']):
                            if href not in links:
                                links.append(href)
                                if len(links) >= max_results:
                                    break
                    return links
            return []
        except requests.Timeout:
            print(f"Timeout while searching DuckDuckGo for '{keyword}'")
            return []
        except requests.ConnectionError as e:
            print(f"Connection error while searching DuckDuckGo for '{keyword}': {str(e)}")
            return []
        except Exception as e:
            print(f"Error searching DuckDuckGo: {str(e)}")
            return []

    @retry(max_retries=2, initial_delay=1, max_delay=5, backoff_factor=1.5)
    def search_with_fallback(self, keyword, country_code='us', language='en', max_results=25, attempt=1, max_attempts=2, retry_delay=10):
        """
        Search with fallback providers and retry logic when all providers fail
        
        Args:
            keyword: Search term
            country_code: Country code for localized results
            language: Language code for results
            max_results: Maximum number of results to return
            attempt: Current attempt number (internal use)
            max_attempts: Maximum number of attempts to try all providers
            retry_delay: Delay in seconds between retry attempts (default: 10)
            
        Returns:
            List of search results or empty list if all attempts fail
        """
        print(f"🔍 Attempt {attempt}/{max_attempts}: Searching for '{keyword}' with fallback providers...")
        
        # Try DuckDuckGo first
        results = self.search_duckduckgo(keyword, country_code, language, max_results)
        if results:
            print(f"✅ DuckDuckGo search successful: {len(results)} results")
            return results
        
        print("⚠️ DuckDuckGo failed, trying alternative search...")
        
        # Fallback 1: Try Bing search
        results = self.search_bing(keyword, max_results)
        if results:
            print(f"✅ Bing search successful: {len(results)} results")
            return results
        
        # Fallback 2: Try direct Google search (simple)
        results = self.search_google_simple(keyword, max_results)
        if results:
            print(f"✅ Google search successful: {len(results)} results")
            return results
        
        # If we have more attempts left, retry the entire process
        if attempt < max_attempts:
            print(f"⚠️ All search providers failed, waiting {retry_delay} seconds before retry ({attempt + 1}/{max_attempts})...")
            time.sleep(retry_delay)  # Wait for the specified delay before retrying
            
            # Rotate user agent before retry
            self.session.headers.update({'User-Agent': random.choice(self.user_agents)})
            
            return self.search_with_fallback(
                keyword=keyword,
                country_code=country_code,
                language=language,
                max_results=max_results,
                attempt=attempt + 1,
                max_attempts=max_attempts,
                retry_delay=retry_delay
            )
        
        print("❌ All search providers failed after all attempts")
        return []

    @retry(max_retries=3, initial_delay=1, max_delay=10, backoff_factor=2)
    def bing_image_scraper(self, query: str, max_results: int = 10):
        """
        Scrape full-size Bing image URLs.
        
        :param query: Search keyword
        :param max_results: Number of images to fetch
        :return: List of image URLs
        """
        print(f"\n=== Starting bing_image_scraper with query: {query} ===")
        
        url = "https://www.bing.com/images/search"
        params = {
            "q": query,
            "form": "HDRSC2",
            "first": "1",
            "tsc": "ImageBasicHover",
            "qft": "+filterui:imagesize-large"  # request large images
        }
        
        # Use the same headers as in tests.py
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.bing.com/",
            "DNT": "1",
            "Connection": "keep-alive"
        }
        
        print(f"Making request to: {url}")
        print(f"Params: {params}")
        print(f"Headers: {headers}")

        try:
            # Make the request using the session
            response = self.session.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            
            print(f"\n=== Response Status: {response.status_code} ===")
            print(f"Final URL: {response.url}")
            print(f"Response Headers: {response.headers}")
            
            # Save response to file for inspection
            temp_file = 'bing_response.html'
            try:
                with open(temp_file, 'w', encoding='utf-8') as f:
                    f.write(response.text)
                print(f"Saved response to {temp_file}")
                
                soup = BeautifulSoup(response.text, "html.parser")
                
                # Debug: Print page title
                title = soup.find('title')
                print(f"Page title: {title.text if title else 'No title found'}")
            finally:
                # Clean up the temporary file
                try:
                    # Use the os module that's already imported
                    if os.path.exists(temp_file):
                        os.remove(temp_file)
                        print(f"Deleted temporary file: {temp_file}")
                except Exception as e:
                    print(f"Warning: Could not delete temporary file {temp_file}: {e}")
            
            # Find all image containers
            image_containers = soup.find_all("a", class_="iusc")
            print(f"Found {len(image_containers)} image containers")
            
            results = []
            for i, div in enumerate(image_containers[:10]):  # Limit to first 10 for debugging
                try:
                    m = div.get("m")
                    if not m:
                        print(f"No 'm' attribute in container {i}")
                        continue
                        
                    m_json = json.loads(m)
                    img_url = m_json.get("murl")
                    
                    if img_url and img_url.startswith("http"):
                        print(f"Found image URL: {img_url}")
                        results.append(img_url)
                        if len(results) >= max_results:
                            break
                except json.JSONDecodeError as e:
                    print(f"JSON decode error in container {i}: {e}")
                    print(f"Problematic 'm' content: {m[:200]}...")
                except Exception as e:
                    print(f"Error processing container {i}: {str(e)}")
            
            print(f"\n=== Found {len(results)} valid image URLs ===")
            return results
            
        except requests.exceptions.RequestException as e:
            print(f"Request failed: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"Response status: {e.response.status_code}")
                print(f"Response headers: {e.response.headers}")
                print(f"Response content: {e.response.text[:500]}...")
        except Exception as e:
            print(f"Unexpected error in bing_image_scraper: {str(e)}")
            # Use the traceback module that's already imported
            traceback.print_exc()
            
        return []
    
    def search_bing(self, keyword, max_results=25):
        """
        Search using Bing (no API key required)
        """
        try:
            search_url = "https://www.bing.com/search"
            params = {'q': keyword, 'count': min(max_results, 50)}
            
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            response = self.session.get(search_url, params=params, headers=headers, timeout=self.default_timeout)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                links = []
                
                # Bing search results are in different selectors
                results = soup.find_all('li', class_='b_algo') or soup.find_all('div', class_='b_algo')
                
                for result in results:
                    link_elem = result.find('a')
                    if link_elem:
                        href = link_elem.get('href', '')
                        if href and href.startswith('http') and 'bing.com' not in href:
                            if href not in links:
                                links.append(href)
                                if len(links) >= max_results:
                                    break
                
                return links
            
            return []
            
        except Exception as e:
            print(f"Error searching Bing: {str(e)}")
            return []

    def search_google_simple(self, keyword, max_results=25):
        """
        Simple Google search (may be rate limited)
        """
        try:
            search_url = "https://www.google.com/search"
            params = {'q': keyword, 'num': min(max_results, 50)}
            
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Accept-Encoding': 'gzip, deflate',
                'DNT': '1',
                'Connection': 'keep-alive',
                'Upgrade-Insecure-Requests': '1'
            }
            
            # Add delay to avoid rate limiting
            time.sleep(2)
            
            response = self.session.get(search_url, params=params, headers=headers, timeout=self.default_timeout)
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.content, 'html.parser')
                links = []
                
                # Google search results
                results = soup.find_all('div', class_='g') or soup.find_all('div', {'data-ved': True})
                
                for result in results:
                    link_elem = result.find('a')
                    if link_elem:
                        href = link_elem.get('href', '')
                        if href and href.startswith('http') and 'google.com' not in href:
                            if href not in links:
                                links.append(href)
                                if len(links) >= max_results:
                                    break
                
                return links
            
            return []
            
        except Exception as e:
            print(f"Error searching Google: {str(e)}")
            return []

    def get_unique_links(self, links, count=15):
        unique_links = []
        seen_base_domains = set()
        for link in links:
            try:
                domain = urlparse(link).netloc.lower()
                domain_parts = domain.split('.')
                if len(domain_parts) >= 2:
                    base_domain = '.'.join(domain_parts[-2:])
                else:
                    base_domain = domain
                if base_domain not in seen_base_domains and self.is_valid_url(link):
                    unique_links.append(link)
                    seen_base_domains.add(base_domain)
                    if len(unique_links) >= count:
                        break
            except:
                continue
        return unique_links

    def is_valid_url(self, url):
        try:
            parsed = urlparse(url)
            skip_domains = ['youtube.com', 'facebook.com', 'twitter.com', 'instagram.com', 
                          'linkedin.com', 'tiktok.com', 'pinterest.com']
            skip_extensions = ['.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']
            domain = parsed.netloc.lower()
            path = parsed.path.lower()
            if any(skip in domain for skip in skip_domains):
                return False
            if any(path.endswith(ext) for ext in skip_extensions):
                return False
            return True
        except:
            return False

    @retry(max_retries=3, initial_delay=1, max_delay=10, backoff_factor=2)
    def scrape_url(self, url, min_length=100, timeout=None):
        """
        Scrape content from a single URL
        """
        try:
            print(f"Scraping: {url}")
            timeout = timeout or self.default_timeout
            response = self.session.get(url, timeout=timeout)
            response.raise_for_status()
            content_type = response.headers.get('content-type', '').lower()
            if 'html' not in content_type:
                return None
            # Dummy main content extraction (replace with real logic if needed)
            soup = BeautifulSoup(response.content, 'html.parser')
            title = soup.title.string if soup.title else url
            content = soup.get_text(separator=' ', strip=True)
            content = re.sub(r'\s+', ' ', content).strip()
            if len(content) < min_length:
                print(f"❌ Content too short ({len(content)} < {min_length})")
                return None
            return {
                'title': title,
                'content': content[:5000],
                'url': url,
                'content_length': len(content)
            }
        except requests.Timeout:
            print(f"Timeout while scraping {url}")
            return None
        except requests.ConnectionError:
            print(f"Connection error while scraping {url}")
            return None
        except Exception as e:
            print(f"Error scraping {url}: {e}")
            return None
    
    def scrape_multiple_urls(self, urls, target_count=5, delay=2, min_length=100):
        """
        Scrape multiple URLs in parallel (up to target_count at a time).
        Ensures exactly target_count successful scrapes by using backup URLs.
        """
        # Use the threading module that's already imported
        results = []
        processed_urls = set()
        threads = []
        results_lock = threading.Lock()

        def scrape_and_collect(url):
            result = self.scrape_url(url, min_length=min_length)
            if result:
                with results_lock:
                    if len(results) < target_count:
                        results.append(result)
                        print(f"✅ Successfully scraped ({len(results)}/{target_count})")
            else:
                print(f"❌ Failed to scrape or insufficient content")

        for url in urls:
            if len(results) >= target_count:
                break
            if url in processed_urls:
                continue
            processed_urls.add(url)
            print(f"Processing {len(results)+1}/{target_count}: {url}")
            t = threading.Thread(target=scrape_and_collect, args=(url,))
            t.start()
            threads.append(t)
            while len([th for th in threads if th.is_alive()]) >= target_count:
                time.sleep(0.1)
            time.sleep(delay)

        for t in threads:
            t.join()
            if len(results) >= target_count:
                break

        return results[:target_count]

    def scrape_from_title(self, title):
        """
        Search for a title and return the scraped content of the first result.
        
        Args:
            title: The title to search for
            
        Returns:
            dict: Scraped content with 'title', 'content', 'url', and 'content_length' keys
                 or None if no results or error occurred
        """
        # Search for the title, get up to 3 results to try
        results = self.search_with_fallback(
            title, 
            country_code='us', 
            language='en', 
            max_results=3,  # Get up to 3 results to try
            attempt=1, 
            max_attempts=2, 
            retry_delay=5
        )
        
        # Try each result until one succeeds
        if results:
            for result in results:
                url = result.get('url')
                if url:
                    try:
                        scraped = self.scrape_url(url)
                        if scraped and scraped.get('content'):
                            return scraped
                    except Exception as e:
                        print(f"Failed to scrape {url}: {str(e)}")
                        continue  # Try the next result
        
        return None
    
    @retry(max_retries=3, initial_delay=1, max_delay=10, backoff_factor=2)
    def scrape_youtube_video(self, keyword):
        """
        Scrape YouTube video links using multiple search engines
        Returns a dict with 'title' and 'url', or None if not found.
        """
        def extract_youtube_id(url):
            """Extract YouTube video ID from various URL formats"""
            patterns = [
                r'(?:youtube\.com/.*[?&]v=|youtu\.be/|youtube\.com/embed/|youtube\.com/v/|youtube\.com/watch\?v=)([^&\n?#]+)',
                r'youtube\.com/shorts/([^&\n?#]+)',
                r'youtu\.be/([^?&#/]+)'
            ]
            for pattern in patterns:
                match = re.search(pattern, url)
                if match:
                    return match.group(1)
            return None

        # User agents for request headers
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/91.0.864.59',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        ]
        
        # Create a new session
        session = requests.Session()
        session.headers.update({
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        
        search_keyword = f"{keyword} site:youtube.com"
        print(f"🔍 Searching for: {search_keyword}")
        
        # Try DuckDuckGo first, then Google as fallback
        urls = [
            f"https://duckduckgo.com/?q={search_keyword}&t=h_&iax=videos&ia=videos",
            f"https://www.google.com/search?q={search_keyword}&tbm=vid"
        ]
        
        for url in urls:
            try:
                print(f"Trying search: {url}")
                headers = {
                    'User-Agent': random.choice(user_agents),
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.5',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1'
                }
                
                response = session.get(url, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    # Look for YouTube links in the page
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        
                        # Skip if not a YouTube URL
                        if 'youtube.com/watch' not in href and 'youtu.be/' not in href:
                            continue
                            
                        # Handle Google search result URLs
                        if 'google.com/url?' in href:
                            try:
                                parsed = urlparse(href)
                                href = parse_qs(parsed.query)['q'][0]
                            except:
                                continue
                        
                        # Extract YouTube video ID
                        video_id = extract_youtube_id(href)
                        if not video_id:
                            continue
                            
                        # Get clean YouTube URL
                        video_url = f"https://www.youtube.com/watch?v={video_id}"
                        title = a.get_text(strip=True) or f"Video about {keyword}"
                        
                        # Get video title from YouTube if possible
                        try:
                            yt_response = session.get(
                                f"https://www.youtube.com/oembed?url={video_url}&format=json",
                                timeout=10
                            )
                            if yt_response.status_code == 200:
                                title = yt_response.json().get('title', title)
                        except:
                            pass
                            
                        print(f"✅ Found YouTube video: {title}")
                        return video_url  # Return just the URL string
                        
            except Exception as e:
                print(f"Error with {url}: {str(e)}")
                continue
        
        print("❌ No YouTube videos found in search results")
        return None  # Return None if no video is found
