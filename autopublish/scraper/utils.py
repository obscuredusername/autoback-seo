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

    
   