#!/usr/bin/env python3
"""
Test script for GoogleNewsScraper
"""
import asyncio
import json
import logging
from autopublish.scraper.news_section import GoogleNewsScraper

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('google_news_scraper_test.log')
    ]
)

async def test_scraper():
    """Test the GoogleNewsScraper with sample categories"""
    # Initialize the scraper
    scraper = GoogleNewsScraper()
    
    # Test with a few categories
    test_categories = [
        {'name': 'technology', 'num': 3},  # Get 3 technology articles
        {'name': 'business', 'num': 2},    # Get 2 business articles
        {'name': 'science', 'num': 2}      # Get 2 science articles
    ]
    
    print("Starting Google News Scraper test...")
    print(f"Testing with categories: {[c['name'] for c in test_categories]}")
    
    try:
        # Fetch the news
        results = await scraper.fetch_news(
            categories=test_categories,
            country='us',
            language='en',
            max_articles=10
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
        
        # Save full results to file
        output_file = 'scraped_google_news_articles.json'
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        print(f"\nFull results saved to '{output_file}'")
        
        return results
        
    except Exception as e:
        print(f"Error during scraping: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

if __name__ == "__main__":
    asyncio.run(test_scraper())
