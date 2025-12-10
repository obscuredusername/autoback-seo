#!/usr/bin/env python3
"""
Test script for the BingScraper class.
"""
import asyncio
import logging
import sys
from typing import List, Dict, Any

# Add the project root to the Python path
import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from autopublish.scraper.news_section import BingScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

async def test_scraper():
    """Test the BingScraper with sample categories"""
    # Initialize the scraper
    scraper = BingScraper()
    
    # Test with a few categories
    test_categories = [
        {'name': 'politics', 'num': 3},  # Get 3 politics articles
        {'name': 'technology', 'num': 2},  # Get 2 technology articles
    ]
    
    print("Starting Bing News Scraper test...")
    print(f"Testing with categories: {[c['name'] for c in test_categories]}")
    
    try:
        # Fetch the news
        results = await scraper.fetch_news(
            categories=test_categories,
            country='us',
            language='en'
        )
        
        # Print summary
        print("\n=== Test Results ===")
        print(f"Total articles scraped: {results['total_articles']}")
        
        # Print articles by category
        for category, articles in results['categories'].items():
            print(f"\n--- {category.upper()} ({len(articles)} articles) ---")
            for i, article in enumerate(articles, 1):
                print(f"\nArticle {i}:")
                print(f"Title: {article['title']}")
                print(f"URL: {article['url']}")
                print(f"Preview: {article['content'][:150]}..." if article['content'] else "No content")
        
        return True
        
    except Exception as e:
        print(f"Error during scraping: {str(e)}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Run the async test
    success = asyncio.run(test_scraper())
    sys.exit(0 if success else 1)
