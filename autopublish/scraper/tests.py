import random
import requests
import time
import re
from bs4 import BeautifulSoup
from urllib.parse import unquote, urlparse, parse_qs

def scrape_youtube_video(keyword):
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
                    return {'title': title, 'url': video_url}
                    
        except Exception as e:
            print(f"Error with {url}: {str(e)}")
            continue
    
    print("❌ No YouTube videos found in search results")
    return None

def main():
    # Test with a search term
    search_term = input("Enter a search term: ") or "imran khan"
    
    print(f"\n🔍 Searching for videos about: {search_term}")
    start_time = time.time()
    
    try:
        result = scrape_youtube_video(search_term)
        
        if result:
            print("\n🎉 Success! Found video:")
            print(f"Title: {result['title']}")
            print(f"URL: {result['url']}")
            
            # Try to open the video in browser
            try:
                import webbrowser
                webbrowser.open(result['url'])
            except:
                pass
        else:
            print("\n❌ No videos found. Try a different search term.")
            
    except Exception as e:
        print(f"\n❌ An error occurred: {str(e)}")
    
    print(f"\n⏱️  Search completed in {time.time() - start_time:.2f} seconds")

if __name__ == "__main__":
    main()