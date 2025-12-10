import os
import random
from typing import List, Dict, Optional, Union
from urllib.parse import urlparse
import logging

logger = logging.getLogger(__name__)

class ProxyManager:
    """
    Manages proxy rotation for web scraping operations.
    Handles different proxy types and provides fallback mechanisms.
    """
    
    def __init__(self, proxies_config: Optional[Dict] = None):
        """
        Initialize the ProxyManager with optional proxy configuration.
        
        Args:
            proxies_config: Dictionary containing proxy configuration
                Example: {
                    'http': ['http://user:pass@proxy1:port', 'http://proxy2:port'],
                    'https': ['https://user:pass@proxy1:port']
                }
        """
        self.proxies = {
            'http': [],
            'https': []
        }
        
        # Load proxies from environment variables if not provided
        if proxies_config is None:
            self._load_proxies_from_env()
        else:
            self._load_proxies_from_config(proxies_config)
    
    def _load_proxies_from_env(self):
        """Load proxy configurations from environment variables."""
        # Try to get proxies from environment variables
        http_proxy = os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy')
        https_proxy = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
        
        if http_proxy:
            self.proxies['http'].append(http_proxy)
        if https_proxy:
            self.proxies['https'].append(https_proxy)
        
        # Load additional proxies from comma-separated environment variables
        http_proxies = os.environ.get('HTTP_PROXIES', '').split(',')
        https_proxies = os.environ.get('HTTPS_PROXIES', '').split(',')
        
        self.proxies['http'].extend([p.strip() for p in http_proxies if p.strip()])
        self.proxies['https'].extend([p.strip() for p in https_proxies if p.strip()])
        
        # Remove duplicates while preserving order
        self.proxies['http'] = list(dict.fromkeys(self.proxies['http']))
        self.proxies['https'] = list(dict.fromkeys(self.proxies['https']))
    
    def _load_proxies_from_config(self, config: Dict):
        """Load proxy configurations from a dictionary."""
        for proxy_type, proxies in config.items():
            if proxy_type in self.proxies:
                if isinstance(proxies, str):
                    self.proxies[proxy_type].append(proxies)
                elif isinstance(proxies, (list, tuple)):
                    self.proxies[proxy_type].extend(proxies)
    
    def get_proxy_for_url(self, url: str) -> Optional[Dict[str, str]]:
        """
        Get a random proxy for the given URL.
        
        Args:
            url: The target URL to get a proxy for
            
        Returns:
            Dictionary with 'http' and/or 'https' proxy URLs, or None if no proxies available
        """
        if not any(self.proxies.values()):
            return None
            
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        
        # Default to http if scheme is not specified
        if scheme not in ['http', 'https']:
            scheme = 'http'
        
        # Try to get a proxy for the specific scheme first
        if self.proxies[scheme]:
            proxy_url = random.choice(self.proxies[scheme])
            return {scheme: proxy_url}
        
        # Fall back to the other scheme if available
        other_scheme = 'https' if scheme == 'http' else 'http'
        if self.proxies[other_scheme]:
            proxy_url = random.choice(self.proxies[other_scheme])
            return {scheme: proxy_url}
        
        return None
    
    def rotate_proxy(self, url: str, current_proxy: Optional[Dict[str, str]] = None) -> Optional[Dict[str, str]]:
        """
        Rotate to a different proxy for the given URL.
        
        Args:
            url: The target URL
            current_proxy: The current proxy being used (if any)
            
        Returns:
            A new proxy configuration or None if no other proxies available
        """
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        
        if scheme not in ['http', 'https']:
            scheme = 'http'
        
        # Get all available proxies for this scheme
        available_proxies = self.proxies[scheme].copy()
        
        # If we have a current proxy, remove it from available proxies
        if current_proxy and scheme in current_proxy:
            current_proxy_url = current_proxy[scheme]
            available_proxies = [p for p in available_proxies if p != current_proxy_url]
        
        # If we still have proxies left, return a random one
        if available_proxies:
            return {scheme: random.choice(available_proxies)}
        
        # Try the other scheme if available
        other_scheme = 'https' if scheme == 'http' else 'http'
        available_other_proxies = self.proxies[other_scheme].copy()
        
        if current_proxy and other_scheme in current_proxy:
            current_other_proxy = current_proxy[other_scheme]
            available_other_proxies = [p for p in available_other_proxies if p != current_other_proxy]
        
        if available_other_proxies:
            return {other_scheme: random.choice(available_other_proxies)}
        
        return None
    
    def mark_proxy_failed(self, proxy: Dict[str, str]):
        """
        Mark a proxy as failed so it can be rotated out.
        
        Args:
            proxy: The proxy configuration that failed
        """
        for scheme, proxy_url in proxy.items():
            if proxy_url in self.proxies[scheme]:
                self.proxies[scheme].remove(proxy_url)
                logger.warning(f"Removed failed proxy: {proxy_url}")
    
    def has_proxies(self) -> bool:
        """Check if any proxies are configured."""
        return any(self.proxies.values())
    
    def get_proxy_count(self) -> Dict[str, int]:
        """Get the number of available proxies by type."""
        return {k: len(v) for k, v in self.proxies.items()}

# Global instance for convenience
proxy_manager = ProxyManager()
