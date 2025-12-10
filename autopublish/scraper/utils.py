import asyncio
import functools
import random
import time
from typing import Dict, List, Optional, Type, Tuple, TypeVar, Callable, Any, Awaitable

T = TypeVar('T')
R = TypeVar('R')

def retry(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    backoff_factor: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,)
    ):
    """
    A retry decorator for both sync and async functions.
    
    Args:
        max_retries: Maximum number of retry attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        backoff_factor: Multiplier for delay between retries
        exceptions: Tuple of exceptions to catch and retry on
    """
    def decorator(func: Callable[..., R]) -> Callable[..., R]:
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs) -> R:
                retries = 0
                delay = initial_delay
                last_exception = None
                
                while True:
                    try:
                        return await func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        retries += 1
                        if retries > max_retries:
                            print(f"❌ Max retries ({max_retries}) exceeded for {func.__name__}")
                            raise
                        
                        # Calculate jitter (up to 25% of delay)
                        jitter = delay * 0.25 * random.random()
                        current_delay = min(delay + jitter, max_delay)
                        
                        # Log the retry
                        print(f"⚠️ Retry {retries}/{max_retries} for {func.__name__} after {current_delay:.2f}s: {str(e)}")
                        
                        # Wait before retry
                        await asyncio.sleep(current_delay)
                        
                        # Increase delay for next retry
                        delay = min(delay * backoff_factor, max_delay)
            
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs) -> R:
                retries = 0
                delay = initial_delay
                last_exception = None
                
                while True:
                    try:
                        return func(*args, **kwargs)
                    except exceptions as e:
                        last_exception = e
                        retries += 1
                        if retries > max_retries:
                            print(f"❌ Max retries ({max_retries}) exceeded for {func.__name__}")
                            raise
                        
                        # Calculate jitter (up to 25% of delay)
                        jitter = delay * 0.25 * random.random()
                        current_delay = min(delay + jitter, max_delay)
                        
                        # Log the retry
                        print(f"⚠️ Retry {retries}/{max_retries} for {func.__name__} after {current_delay:.2f}s: {str(e)}")
                        
                        # Wait before retry
                        time.sleep(current_delay)
                        
                        # Increase delay for next retry
                        delay = min(delay * backoff_factor, max_delay)
            
            return sync_wrapper
    
    return decorator


class YahooLink:
    """Utility class for generating and validating Yahoo news URLs."""
    
    # Map of standard categories to Yahoo-specific paths
    CATEGORY_MAP = {
        'finance': 'finance',
        'business': 'business',
        'technology': 'tech',
        'science': 'science',
        'health': 'health',
        'entertainment': 'entertainment',
        'sports': 'sports',
        'politics': 'politics',
        'world': 'world',
    }
    
    @classmethod
    def get_yahoo_url(cls, category: str, language: str = 'en') -> str:
        """
        Generate Yahoo news URL for the given category and language.
        
        Args:
            category: News category (e.g., 'business', 'technology')
            language: Language code (e.g., 'en', 'es')
            
        Returns:
            str: Formatted Yahoo news URL
        """
        category = category.lower()
        language = language.lower()
        
        # Map to Yahoo-specific category if needed
        yahoo_category = cls.CATEGORY_MAP.get(category, category)
        
        # Special handling for finance which has a different domain
        if yahoo_category == 'finance':
            subdomain = 'www' if language == 'en' else language
            return f"https://{subdomain}.finance.yahoo.com"
        
        # For other categories
        subdomain = 'www' if language == 'en' else language
        return f"https://{subdomain}.yahoo.com/news/{yahoo_category}"
    
    @classmethod
    def is_valid_category(cls, category: str) -> bool:
        """Check if a category is valid for Yahoo news."""
        return category.lower() in cls.CATEGORY_MAP
    
    @classmethod
    def get_valid_categories(cls) -> List[str]:
        """Get list of valid Yahoo news categories."""
        return list(cls.CATEGORY_MAP.keys())
    
    @classmethod
    def generate_urls_for_categories(
        cls, 
        categories: Dict[str, int], 
        language: str = 'en'
    ) -> Dict[str, str]:
        """
        Generate Yahoo URLs for multiple categories with counts.
        
        Args:
            categories: Dict of {category: count} pairs
            language: Language code
            
        Returns:
            Dict of {category: url} pairs
        """
        return {
            category: cls.get_yahoo_url(category, language)
            for category in categories
            if cls.is_valid_category(category)
        }
         