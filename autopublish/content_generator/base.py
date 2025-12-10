import os
import re
import time
import json
import asyncio
import shutil
import aiohttp
import random
import requests
import logging
from typing import Optional, Dict, Any, List, Union
from dotenv import load_dotenv

# Configure logger
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()
import random
import requests
import openai
from typing import Dict, Any, Optional, List, Union
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.retrievers import TFIDFRetriever
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from .prompts import (
    get_blog_content_prompt,
    get_blog_plan_prompt,
    get_blog_expansion_prompt,
    get_blog_rephrasing_prompt
)
from PIL import Image
from io import BytesIO
from typing import Optional
from datetime import datetime


class ContentGenerator:
    def __init__(self, chunk_size: int = 1000, max_chunks: int = 10):
        self.client = openai.AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=120.0)
        self.chunk_size = chunk_size
        self.max_chunks = max_chunks
#used
    async def generate_blog_plan(self, keyword: str, language: str = "en", max_retries: int = 3, available_categories: List[str] = None) -> Dict[str, Any]:
        """
        Generate a comprehensive blog plan including title, headings, category, and image prompts
        
        Args:
            keyword: The main keyword/topic for the blog
            language: Language for the blog content
            max_retries: Maximum number of retry attempts if generation fails
            available_categories: List of available category names to choose from
        """
        retry_count = 0
        last_error = None
        blog_plan = None
        
        # Prepare the categories text for the prompt
        categories_text = ""
        if available_categories:
            categories_text = "Available categories: " + ", ".join(f'"{cat}"' for cat in available_categories) + "\n"
        
        while retry_count < max_retries:
            try:
                blog_plan_prompt = get_blog_plan_prompt(keyword, language, available_categories)

                response = await self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are a professional content strategist creating detailed blog outlines. Always respond with valid JSON."},
                        {"role": "user", "content": blog_plan_prompt}
                    ],
                    temperature=0.7,
                    max_tokens=4000,  # Using 4000 tokens for gpt-3.5-turbo as requested
                    response_format={"type": "json_object"}  # Request JSON response format
                )
                
                raw_response = response.choices[0].message.content.strip()
                print(f"\n=== RAW LLM RESPONSE for '{keyword}' in '{language}' (Attempt {retry_count + 1}) ===")
                print(raw_response)
                print("="*20)
                
                try:
                    # Try to parse the response directly first
                    try:
                        blog_plan = json.loads(raw_response)
                    except json.JSONDecodeError:
                        # If direct parse fails, try to extract JSON from code blocks
                        json_match = re.search(r'```(?:json)?\n(.*?)\n```', raw_response, re.DOTALL)
                        if json_match:
                            blog_plan = json.loads(json_match.group(1))
                        else:
                            # If no code block, try to find JSON object directly
                            json_match = re.search(r'({.*})', raw_response, re.DOTALL)
                            if json_match:
                                blog_plan = json.loads(json_match.group(1))
                            else:
                                raise ValueError("No valid JSON found in response")
                    
                    # Validate the structure
                    if not isinstance(blog_plan, dict):
                        raise ValueError("Blog plan must be a JSON object")
                        
                    # Ensure required fields exist with proper types
                    required_fields = {
                        'title': str,
                        'category': str,
                        'table_of_contents': list,
                        'headings': list
                    }
                    
                    for field, field_type in required_fields.items():
                        if field not in blog_plan:
                            raise ValueError(f"Missing required field: {field}")
                        if not isinstance(blog_plan[field], field_type):
                            raise ValueError(f"Field '{field}' must be of type {field_type.__name__}")
                    
                    # Validate table_of_contents structure
                    for item in blog_plan['table_of_contents']:
                        if not isinstance(item, dict) or 'heading' not in item or 'subheadings' not in item:
                            raise ValueError("Invalid table_of_contents format")
                        if not isinstance(item['subheadings'], list):
                            raise ValueError("subheadings must be a list")
                    
                    # Validate headings structure
                    for heading in blog_plan['headings']:
                        if not isinstance(heading, dict) or 'title' not in heading or 'description' not in heading:
                            raise ValueError("Invalid heading format")
                        if 'subheadings' in heading and not isinstance(heading['subheadings'], list):
                            raise ValueError("subheadings must be a list")
                    if 'meta_description' in blog_plan:
                        if not isinstance(blog_plan['meta_description'], str):
                            raise ValueError("meta_description must be a string")
                    
                    print(f"✅ Validated blog plan with {len(blog_plan['headings'])} headings")
                    return blog_plan
                except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                    last_error = f"Validation error: {str(e)}"
                    print(f"❌ {last_error}")
                    if retry_count < max_retries - 1:
                        print(f"🔄 Retrying... (attempt {retry_count + 2}/{max_retries})")
                    
            except Exception as e:
                last_error = f"Unexpected error: {str(e)}"
                print(f"❌ {last_error}")
                if retry_count < max_retries - 1:
                    print(f"🔄 Retrying... (attempt {retry_count + 2}/{max_retries})")
            
            retry_count += 1
        
        # If we get here, all retries failed
        print(f"❌ Failed to generate valid blog plan after {max_retries} attempts")
        if last_error:
            print(f"Last error: {last_error}")
            
        # Return a minimal valid structure to prevent complete failure
        return {
            "title": keyword,
            "category": "General",
            "blog_plan" : blog_plan or {}
            }

    async def keyword_generation(
            self, 
            keyword: str, 
            language: str = "en", 
            max_retries: int = 3,
            #change me
            min_length: int = 500,
            image_links: Optional[List[str]] = None,
            backlinks: Optional[List[str]] = None,
            video_link: Optional[str] = None,
            scraped_data: Optional[List[Dict[str, Any]]] = None,
            available_categories: Optional[List[str]] = None
        ) -> Dict[str, Any]:
        """
        Generate complete blog content for a given keyword.
        
        Args:
            keyword: Main keyword/topic for the blog
            language: Language code (default: 'en')
            max_retries: Maximum number of retry attempts
            min_length: Minimum word count for the generated content
            scraped_data: Optional scraped data for RAG
            available_categories: List of available category names from the database
            
        Returns:
            Dictionary containing:
            - title: Generated blog title
            - content: Generated HTML content
            - category: Selected category name
            - image_prompts: List of image prompts
            - word_count: Word count of generated content
            - success: Boolean indicating success/failure
            - error: Error message if success is False
        """
        print(f"🔍 Starting keyword generation for: {keyword}")
        try:
            # 1. Generate blog plan with available categories
            print("🔍 Generating blog plan...")
            print(f"🔍 Available categories: {available_categories}")
            
            # Generate the blog plan with available categories
            blog_plan = await self.generate_blog_plan(
                keyword=keyword,
                language=language,
                max_retries=max_retries,
                available_categories=available_categories or []
            )
            print(f"🔍 Blog plan generated: {bool(blog_plan)}")
            if blog_plan:
                print(f"🔍 Blog plan keys: {list(blog_plan.keys())}")
            
            # Check if blog plan has required fields instead of success key
            required_fields = ['title', 'category', 'table_of_contents', 'headings','meta_description']
            if not blog_plan or not all(field in blog_plan for field in required_fields):
                error_msg = "Invalid blog plan structure"
                print(f"❌ Failed to generate valid blog plan: {error_msg}")
                print(f"❌ Blog plan structure: {blog_plan}")
                return {
                    "success": False,
                    "error": f"Failed to generate valid blog plan: {error_msg}"
                }
            
            if scraped_data is not None:
                # Handle both list and dictionary formats for scraped_data
                if isinstance(scraped_data, dict) and "results" in scraped_data:
                    # Handle dictionary format with 'results' key
                    containers = scraped_data["results"]
                else:
                    # Handle case where scraped_data is a list directly
                    containers = scraped_data if isinstance(scraped_data, list) else []
                
                for container in containers:
                    if isinstance(container, dict) and "url" in container:
                        backlinks.append(container["url"])

            logger.info(f"Backlinks: {backlinks}")
            logger.info(f"Video Link: {video_link}")
            # 2. Process scraped_data for RAG if available
            section_chunks = {}
            if scraped_data is not None:
                print(f"🔍 Processing {len(scraped_data) if isinstance(scraped_data, list) else 1} items of scraped data for RAG...")
                
                # Extract text from scraped data
                texts = []
                if isinstance(scraped_data, list):
                    for item in scraped_data:
                        if isinstance(item, str) and item.strip():
                            texts.append(item.strip())
                        elif isinstance(item, dict):
                            # Try to get text from common fields
                            text = None
                            for field in ['snippet', 'description', 'text', 'content', 'excerpt', 'summary']:
                                if field in item and isinstance(item[field], str) and item[field].strip():
                                    text = item[field].strip()
                                    break
                            if text:
                                texts.append(text)
                elif isinstance(scraped_data, str) and scraped_data.strip():
                    texts.append(scraped_data.strip())
                
                if texts:
                    print(f"ℹ️ Extracted {len(texts)} text chunks from scraped data")
                    # Use TF-IDF to get most relevant chunks
                    relevant_chunks = self.get_most_relevant_chunks_langchain(
                        texts, 
                        keyword, 
                        top_k=3  # Get top 3 most relevant chunks
                    )
                    # Add to section_chunks under a general section
                    if relevant_chunks:
                        section_chunks["rag_context"] = relevant_chunks
                        print(f"✅ Processed {len(relevant_chunks)} relevant chunks from scraped data")
                    else:
                        print("⚠️ No relevant chunks found in scraped data")
                else:
                    print("⚠️ No usable text found in scraped data")
            else:
                print("ℹ️ No scraped_data provided, continuing without RAG")
            
            # 3. Generate blog content with the specified min_length and RAG context
            print(f"🔍 Generating blog content with min_length={min_length}...")
            print(f"🔍 Passing {len(backlinks or [])} backlinks to content generator")
            logger.info(f"category names: {available_categories}")
            content_result = await self.generate_blog_content(
                keyword=keyword,
                language=language,
                blog_plan=blog_plan,
                video_info=None,  # Can be updated if video info is available
                category_names=available_categories or [],  # Pass available categories
                section_chunks=section_chunks,  # Pass the RAG chunks here
                target_word_count=min_length,  # Pass the min_length as target_word_count
                backlinks=backlinks  # Pass the backlinks
            )
            selected_category_name = None
            print(f"🔍 Content generation result: {bool(content_result)}")
            if content_result:
                print(f"🔍 Content result keys: {list(content_result.keys())}")
                if 'content' in content_result:
                    content_length = len(content_result['content'])
                    print(f"🔍 Generated content length: {content_length} chars")
                if 'category' in content_result:
                    selected_category_name = content_result['category']
                    print(f"🔍 Selected category: {selected_category_name}")
            
            if not content_result or not content_result.get("success", False):
                error_msg = content_result.get("error", "Unknown error") if isinstance(content_result, dict) else "No content result"
                print(f"❌ Failed to generate blog content: {error_msg}")
                return {
                    "success": False,
                    "error": f"Failed to generate blog content: {error_msg}"
                }
            
            # 3. Inject images into the content if we have image prompts
            content = content_result.get("content", "")
            image_urls = []
            
            if blog_plan.get("image_prompts"):
                print("🔍 Injecting images into content...")
                image_generator = ImageGenerator()
                
                try:
                    # Process up to 2 image prompts
                    # for i, image_prompt in enumerate(blog_plan["image_prompts"][:2]):
                    #     prompt = image_prompt.get("prompt", "")
                    #     if not prompt:
                    #         continue
                            
                    #     print(f"🖼️  Generating image {i+1} with prompt: {prompt}")
                    #     try:
                    #         # Generate the image
                    #         # image_result = await image_generator.generate_image(prompt)
                    #         # if not image_result or not image_result.get('url'):
                    #         #     print(f"⚠️  Failed to generate image {i+1}")
                    #         #     continue
                            
                    #         BFL_image_result = image_result.get('url', '')
                    #         image_url = image_result.get('url', '')
                    #         if not image_url:
                    #             print(f"⚠️  No URL in image result for prompt {i+1}")
                    #             continue
                                
                    #         # Add to image_urls list
                    #         image_urls.append(image_url)
                    #         print(f"✅ Generated image {i+1} URL: {image_url}")
                            
                    #         # Create image HTML with the specified format
                    #         img_tag = (
                    #             f'<figure class="image">\n'
                    #             f'  <img src="{image_url}" alt="{prompt}" class="blog-image" style="max-width: 100%; height: auto; margin: 20px 0;" />\n'
                    #             f'  <figcaption style="text-align: center; font-style: italic; color: #666; margin-top: 8px;">'

                    #             f'{prompt}'

                    #             f'</figcaption>\n'
                    #             f'</figure>\n\n'
                    #         )
                            
                    #         # First image goes at the top
                    #         if i == 0:
                    #             # Add a paragraph before the image if it's at the very top
                    #             if not content.strip().startswith('<'):
                    #                 content = f'<p></p>\n{img_tag}\n' + content
                    #             else:
                    #                 # Insert after the first heading if it exists
                    #                 heading_match = re.search(r'<h1[^>]*>.*?</h1>', content, re.DOTALL)
                    #                 if heading_match:
                    #                     pos = heading_match.end()
                    #                     content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                    #                 else:
                    #                     content = img_tag + '\n' + content
                    #             print("✅ Inserted first image at the top of the content")
                    #         # Second image goes after the first paragraph or heading
                    #         elif i == 1 and content:
                    #             # Try to find the first paragraph or heading to insert after
                    #             para_match = re.search(r'<p[^>]*>.*?</p>', content, re.DOTALL) or \
                    #                        re.search(r'<h[1-6][^>]*>.*?</h[1-6]>', content, re.DOTALL)
                                
                    #             if para_match:
                    #                 # Insert after the first paragraph or heading
                    #                 pos = para_match.end()
                    #                 content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                    #                 print("✅ Inserted second image after first paragraph/heading")
                    #             else:
                    #                 # Insert in the middle of the content if no paragraph found
                    #                 mid_point = len(content) // 2
                    #                 content = content[:mid_point] + '\n' + img_tag + '\n' + content[mid_point:]
                    #                 print("✅ Inserted second image in the middle of the content")
                                    
                    #     except Exception as img_error:
                    #         print(f"⚠️  Error generating/inserting image {i+1}: {str(img_error)}")
                    #         import traceback
                    #         traceback.print_exc()
                    logger.info(f"================ {image_links}")
                    # Process images until we have 2 valid ones or run out of images
                    valid_image_count = 0
                    processed_count = 0
                    valid_images = []  # Store valid image URLs and their HTML tags
                    
                    # First pass: Collect valid images
                    for i, image_link in enumerate(image_links):
                        if valid_image_count >= 2:
                            break
                            
                        if not image_link:
                            logger.warning(f"Skipping empty image link at position {i+1}")
                            continue
                            
                        processed_count += 1
                        logger.info(f"🖼️  Processing image {processed_count}: {image_link}")
                        
                        try:
                            # Call the local API to process the image
                            import aiohttp
                            import json
                            
                            async with aiohttp.ClientSession() as session:
                                payload = {"image_links": [image_link]}
                                async with session.post(
                                    "https://nigga.cemantix.net/generator/download-image/",
                                    json=payload,
                                    headers={"Content-Type": "application/json"}
                                ) as response:
                                    if response.status == 200:
                                        result = await response.json()
                                        if result.get("status") == "completed" and result.get("results"):
                                            image_url = result["results"][0]["processed_url"]
                                            print(f"🔄 Image processing result: {image_url}")
                                            
                                            # Check if image is from the correct domain
                                            if "spreadtheword.fr" in image_url:
                                                valid_image_count += 1
                                                print(f"✅ Found valid image {valid_image_count}/2: {image_url}")
                                                
                                                # Create image HTML with the specified format using the keyword for alt text
                                                img_tag = (
                                    f'<img src="{image_url}" alt="{keyword}" class="blog-image" rel="nofollow" style="max-width: 100%; height: auto; margin: 20px 0;" />\n'
                                )
                                valid_images.append((image_url, img_tag))
                                image_urls.append(image_url)
                                if valid_image_count >= 2:
                                    print("✅ Found 2 valid images from spreadtheword.fr")
                                    break
                        except Exception as e:
                            print(f"⚠️  Error processing image {processed_count}: {str(e)}")
                            import traceback
                            traceback.print_exc()

                    # Second pass: Insert the valid images in the correct positions
                    for idx, (img_url, img_tag) in enumerate(valid_images):
                        if idx == 0:  # First image - insert at top
                            if not content.strip().startswith('<'):
                                content = f'<p></p>\n{img_tag}\n' + content
                            else:
                                # Insert after the first heading if it exists
                                heading_match = re.search(r'<h1[^>]*>.*?</h1>', content, re.DOTALL)
                                if heading_match:
                                    pos = heading_match.end()
                                    content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                                else:
                                    content = img_tag + '\n' + content
                            print(f"✅ Inserted first valid image at the top of the content: {img_url}")
                            
                        elif idx == 1:  # Second image - insert after 12th heading or at end
                            # Find all heading matches (h1 through h6)
                            heading_matches = list(re.finditer(r'<h[1-6][^>]*>.*?</h[1-6]>', content, re.DOTALL))
                            
                            # Check if we have at least 12 headings
                            if len(heading_matches) >= 12:
                                twelfth_heading = heading_matches[11]  # 0-based index, so [11] is the 12th heading
                                pos = twelfth_heading.end()
                                content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                                print(f"✅ Inserted second valid image after 12th heading: {img_url}")
                            else:
                                # Fallback to inserting after last heading if less than 12 exist
                                if heading_matches:
                                    last_heading = heading_matches[-1]
                                    pos = last_heading.end()
                                    content = content[:pos] + '\n' + img_tag + '\n' + content[pos:]
                                    print(f"✅ Inserted second valid image after last heading (less than 12 headings found): {img_url}")
                                else:
                                    # If no headings found, insert at the end
                                    content = content + '\n' + img_tag + '\n'
                                    print(f"✅ Inserted second valid image at the end (no headings found): {img_url}")
                    
                    if not valid_images:
                        print("⚠️  No valid images found from spreadtheword.fr")
                
                except Exception as e:
                    print(f"⚠️  Error generating/inserting images: {str(e)}")
                    import traceback
                    traceback.print_exc()
            
            # 3.4. Remove the very first heading from content
            try:
                # Find the first heading
                first_heading_match = re.search(r'<h[1-6][^>]*>.*?</h[1-6]>', content, re.DOTALL)
                if first_heading_match:
                    # Remove the first heading from content
                    content = content[:first_heading_match.start()] + content[first_heading_match.end():]
                    print("✅ Removed the first heading from content")
            except Exception as e:
                print(f"⚠️  Error removing first heading: {str(e)}")
                import traceback
                traceback.print_exc()
            
            # 3.5. Insert video if video_link is provided
            if video_link:
                try:
                    # Find all heading matches (h1 through h6)
                    heading_matches = list(re.finditer(r'<h[1-6][^>]*>.*?</h[1-6]>', content, re.DOTALL))
                    
                    if heading_matches:
                        # Try to find the 16th heading (0-based index 15)
                        if len(heading_matches) >= 16:
                            target_heading = heading_matches[15]  # 0-based index, so [15] is the 16th heading
                            print("✅ Found 16th heading, inserting video after it")
                        else:
                            # Fallback to the last heading if less than 16 exist
                            target_heading = heading_matches[-1]
                            print(f"ℹ️ Less than 16 headings found ({len(heading_matches)}), inserting video after the last heading")
                        
                        video_embed = f'''
<!-- YouTube Video Section -->
<div class="video-container" style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%; margin: 30px 0; background: #f5f5f5; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1);">
    <h2 style="padding: 15px 20px 10px; margin: 0; color: #333; font-size: 1.5em;">Video: {keyword}</h2>
    <div style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;">
        <iframe 
            src="{video_link.replace('watch?v=', 'embed/')}" 
            style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: none;" 
            allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
            allowfullscreen>
        </iframe>
    </div>
    <p style="padding: 10px 20px; margin: 0; font-size: 0.9em; color: #666; background: #f9f9f9; border-top: 1px solid #eee;">
        Watch this video to learn more about {keyword}.
    </p>
</div>
'''
                        # Insert the video after the target heading
                        content = content[:target_heading.end()] + '\n' + video_embed + '\n' + content[target_heading.end():]
                        print(f"✅ Successfully inserted video after heading")
                        if 'target_heading' in locals() and target_heading:
                            heading_text = target_heading.group(0)[:50] + '...' if len(target_heading.group(0)) > 50 else target_heading.group(0)
                            print(f"📌 Inserted after: {heading_text}")
                except Exception as e:
                    print(f"⚠️  Error inserting video: {str(e)}")
                    import traceback
                    traceback.print_exc()
            # Add backlinks if content has one or no href tags
            # href_count = len(re.findall(r'<a\s+[^>]*href=', content, re.IGNORECASE))
            # if href_count <= 1 and backlinks:
            #     print(f"ℹ️ Found only {href_count} link(s) in content, adding backlinks...")
                
            #     # Extract domains from backlinks that aren't already in content
            #     domains = []
            #     for url in backlinks:
            #         domain = re.sub(r'^https?://(www\.)?([^/]+).*', r'\2', url)
            #         # Skip if this domain is already linked in content
            #         if domain not in content:
            #             domains.append((domain, url))
            #             if len(domains) >= 3:  # We only need up to 3 unique domains
            #                 break
                
            #     if domains:
            #         # Split content by <p> tags
            #         paragraphs = re.split(r'(<p[^>]*>.*?</p>)', content, flags=re.DOTALL)
            #         new_paragraphs = []
            #         link_count = 0
                    
            #         for i, para in enumerate(paragraphs):
            #             new_paragraphs.append(para)
            #             # After every 5th paragraph, add a backlink if we have more to add
            #             if i > 0 and i % 5 == 0 and link_count < len(domains):
            #                 domain, url = domains[link_count]
            #                 link_phrases = [
            #                     f'<p>Pour plus d\'informations détaillées, consultez <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>.</p>',
            #                     f'<p>Vous pouvez trouver des informations supplémentaires sur ce sujet sur <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>.</p>',
            #                     f'<p>Pour en savoir plus, visitez <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>.</p>',
            #                     f'<p>J\'ai trouvé un article intéressant sur <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a> à propos de ce sujet.</p>',
            #                     f'<p>Selon <a href="{url}" target="_blank" rel="nofollow noopener noreferrer">{domain}</a>, c\'est un aspect important à considérer.</p>'
            #                 ]
            #                 new_paragraphs.append(random.choice(link_phrases))
            #                 link_count += 1
                    
            #         if link_count > 0:
            #             content = ''.join(new_paragraphs)
            #             print(f"✅ Added {link_count} backlinks to the content")
            #         else:
            #             print("⚠️ No new backlinks could be added (all domains already in content)")
            #     else:
            #         print("⚠️ No new backlinks available to add (all domains already in content)")
            # else:
            #     print(f"ℹ️ Content already contains {href_count} links, no additional backlinks added")


            # 4. Clean the content before returning
            cleaned_content = self._clean_html_content(content)
            
            # 5. Return the generated content with images
            result = {
                "success": True,
                "title": blog_plan.get("title", keyword),
                "content": cleaned_content,
                "meta_description": blog_plan.get("meta_description", ""),
                "category": blog_plan.get("category", ""),
                "image_prompts": blog_plan.get("image_prompts", []),
                "image_urls": image_urls,
                "word_count": len(re.sub(r'<[^>]+>', ' ', cleaned_content).split()),
                "selected_category_name": selected_category_name
            }
            print(f"✅ Successfully generated content with {result.get('word_count', 0)} words and {len(image_urls)} images")
            return result
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ Error in keyword generation: {str(e)}\n{error_trace}")
            return {
                "success": False,
                "error": f"Error in keyword generation: {str(e)}"
            }

    def get_most_relevant_chunks_langchain(self, chunks: list, query: str, top_k: int = 5) -> list:
        """Use LangChain's TFIDFRetriever to get the most relevant chunks for a query."""
        if not chunks:
            return []
            
        retriever = TFIDFRetriever.from_texts(chunks)
        results = retriever.invoke(query)
        return [doc.page_content for doc in results[:top_k]]

    def chunk_text(self, text: str) -> list:
        """Split text into chunks of approximately chunk_size characters."""
        chunks = []
        current_chunk = ""
        sentences = re.split(r'(?<=[.!?])\s+', text)
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) <= self.chunk_size:
                current_chunk += sentence + " "
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = sentence + " "
                
        if current_chunk:
            chunks.append(current_chunk.strip())
            
        return chunks

    @staticmethod
    def _is_html_balanced(html: str) -> bool:
        """Check if HTML tags are properly balanced."""
        stack = []
        tag_re = re.compile(r'<(/?)(\w+)[^>]*>', re.IGNORECASE)
        
        for match in tag_re.finditer(html):
            is_end_tag, tag = match.groups()
            tag = tag.lower()
            
            # Skip self-closing tags
            if tag in ('img', 'br', 'hr', 'meta', 'link', 'input', 'area', 'base', 'col', 'command', 
                      'embed', 'keygen', 'param', 'source', 'track', 'wbr'):
                continue
                
            if is_end_tag:
                if not stack:
                    return False
                if stack[-1].lower() != tag:
                    return False
                stack.pop()
            else:
                stack.append(tag)
                
        return len(stack) == 0
    
    @staticmethod
    def _fix_html_structure(html: str) -> str:
        """
        Attempt to fix common HTML structure issues and ensure proper tag nesting.
        
        Args:
            html: The HTML content to fix
            
        Returns:
            str: Fixed HTML content with proper structure
        """
        if not html or not isinstance(html, str):
            return ""
            
        # First, try using BeautifulSoup for better HTML parsing if available
        try:
            from bs4 import BeautifulSoup, Tag
            from bs4.builder import builder_registry
            
            # Use html.parser instead of lxml for better compatibility
            soup = BeautifulSoup(html, 'html.parser')
            
            # Ensure proper document structure
            if not soup.find() or not soup.find().name:
                # If no valid HTML structure, wrap in a div
                new_soup = BeautifulSoup('<div class="content-container"></div>', 'html.parser')
                new_soup.div.append(soup)
                soup = new_soup
                
            # Ensure all tags are properly nested and closed
            for tag in soup.find_all(True):
                # Skip self-closing tags
                if tag.name in ('img', 'br', 'hr', 'meta', 'link', 'input', 'area', 'base', 'col', 'command', 
                              'embed', 'keygen', 'param', 'source', 'track', 'wbr'):
                    continue
                    
                # Ensure all links have proper attributes
                if tag.name == 'a' and tag.get('href'):
                    if tag['href'].startswith(('http://', 'https://')):
                        tag['target'] = '_blank'
                        rel_attrs = set(tag.get('rel', []))
                        rel_attrs.update(['nofollow', 'noopener', 'noreferrer'])
                        tag['rel'] = list(rel_attrs)
            
            # Convert back to string and clean up
            fixed_html = str(soup)
            
            # Remove any empty tags except those that should be self-closing
            fixed_html = re.sub(r'<([a-z]+)([^>]*)>\s*</\1>', '', fixed_html, flags=re.IGNORECASE)
            
            # Ensure proper line breaks for better readability
            fixed_html = re.sub(r'>\s+<', '>\n<', fixed_html)
            
            return fixed_html.strip()
            
        except Exception as e:
            logger.warning(f"Error fixing HTML with BeautifulSoup: {str(e)}")
            # Fallback to regex-based fixing if BeautifulSoup fails
            
        # Remove any incomplete tags at the end
        html = re.sub(r'<[^>]*$', '', html)
        
        # Convert h1 to h2 for better hierarchy
        html = re.sub(r'<h1(.*?)>', r'<h2\1>', html, flags=re.IGNORECASE)
        html = re.sub(r'</h1>', '</h2>', html, flags=re.IGNORECASE)
        
        # Ensure proper nesting of heading levels
        last_heading_level = 0
        lines = html.split('\n')
        for i, line in enumerate(lines):
            heading_match = re.match(r'<(h[1-6])([^>]*)>', line, re.IGNORECASE)
            if heading_match:
                tag = heading_match.group(1).lower()
                level = int(tag[1])
                
                # Ensure heading levels don't skip (h1 -> h3 is bad, h1 -> h2 is good)
                if level > last_heading_level + 1:
                    # Replace with appropriate level
                    new_level = last_heading_level + 1
                    lines[i] = re.sub(
                        r'<h[1-6]([^>]*)>', 
                        f'<h{new_level}\1>', 
                        line, 
                        flags=re.IGNORECASE
                    )
                    lines[i] = lines[i].replace(
                        f'</{tag}>', 
                        f'</h{new_level}>'
                    )
                    level = new_level
                    
                last_heading_level = level
        
        html = '\n'.join(lines)
        
        # Fix unclosed tags
        open_tags = []
        tag_re = re.compile(r'<(/?)(\w+)[^>]*>', re.IGNORECASE)
        
        for match in tag_re.finditer(html):
            is_end_tag, tag = match.groups()
            tag = tag.lower()
            
            # Skip self-closing tags
            if tag in ('img', 'br', 'hr', 'meta', 'link', 'input', 'area', 'base', 'col', 'command', 
                      'embed', 'keygen', 'param', 'source', 'track', 'wbr'):
                continue
                
            if is_end_tag:
                if open_tags and open_tags[-1] == tag:
                    open_tags.pop()
            else:
                open_tags.append(tag)
        
        # Close any unclosed tags in reverse order
        for tag in reversed(open_tags):
            html += f'</{tag}>'
        
        # Ensure the content is properly wrapped in a container
        if not (html.strip().startswith('<') and html.strip().endswith('>')):
            html = f'<div class="content-container">\n{html}\n</div>'
            
        return html
    
    @staticmethod
    def _is_content_complete(content: str) -> bool:
        """Check if the content appears complete."""
        # Check if content ends with proper punctuation
        if not content.strip():
            return False
            
        # Check if the last character is a sentence-ending punctuation
        last_char = content.strip()[-1]
        if last_char not in ('.', '!', '?', '>', '"', "'"):
            return False
            
        # Check if we have a reasonable number of words
        text_only = re.sub(r'<[^>]+>', ' ', content)
        words = text_only.split()
        if len(words) < 50:  # Arbitrary minimum word count
            return False
            
        return True
    
    @staticmethod
    def _clean_markdown_ticks(content: str) -> str:
        """
        Remove markdown code block ticks from content.
        
        Args:
            content: The content that might contain markdown code blocks
            
        Returns:
            str: Content with markdown code block ticks removed
        """
        # Remove ```html and ``` from the content
        content = re.sub(r'```(?:html\n)?|```', '', content)
        
        # Also handle the case where content is wrapped in backticks with parentheses
        # e.g., ```html (content) ```
        content = re.sub(r'```(?:html\s*)?\((.*?)\)\s*```', r'\1', content, flags=re.DOTALL)
        
        # Remove any remaining backticks that might be at the start/end of lines
        content = re.sub(r'^\s*`+|`+\s*$', '', content, flags=re.MULTILINE)
        
        return content.strip()

    @staticmethod
    def _clean_html_content(html: str) -> str:
        """
        Clean and normalize HTML content, ensuring valid structure and proper backlink handling.
        Removes any content that is not wrapped in HTML tags.
        
        Args:
            html: The HTML content to clean
            
        Returns:
            str: Cleaned and validated HTML content with only wrapped content
        """
        if not html or not isinstance(html, str):
            return ""
            
        # First clean any markdown ticks
        html = ContentGenerator._clean_markdown_ticks(html)
        
        # Remove any CSS styles and DOCTYPE if present
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        html = re.sub(r'<!DOCTYPE[^>]*>', '', html, flags=re.IGNORECASE)
        
        # Parse with BeautifulSoup for better HTML processing
        try:
            from bs4 import BeautifulSoup, NavigableString
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove any script tags for security but keep iframes
            for script in soup(['script', 'object']):  # Keep iframe and embed for video support
                script.decompose()
                
            # Sanitize iframe tags to only allow from trusted sources (like YouTube)
            for iframe in soup.find_all('iframe'):
                src = iframe.get('src', '')
                if not any(domain in src for domain in ['youtube.com', 'youtu.be', 'vimeo.com']):
                    iframe.decompose()
                    continue
                # Ensure iframe has security attributes
                iframe['sandbox'] = 'allow-same-origin allow-scripts allow-popups'
                iframe['allowfullscreen'] = ''
                
            # Ensure all links have target="_blank" and proper rel attributes
            for a in soup.find_all('a', href=True):
                if a['href'].startswith(('http://', 'https://')):
                    a['target'] = '_blank'
                    rel_attrs = set(a.get('rel', []))
                    rel_attrs.update(['nofollow', 'noopener', 'noreferrer'])
                    a['rel'] = list(rel_attrs)
            
            # Remove any text nodes that are direct children of the top-level element
            # and not wrapped in any HTML tags
            for element in soup.contents:
                if isinstance(element, NavigableString) and element.strip():
                    element.extract()
            
            # Also check for text nodes after the last tag in the document
            if soup.contents and isinstance(soup.contents[-1], NavigableString):
                soup.contents[-1].extract()
            
            html = str(soup)
            
            # Additional check using regex to remove any remaining non-HTML content
            # This handles cases where BeautifulSoup might not catch everything
            lines = []
            for line in html.split('\n'):
                line = line.strip()
                if line and not line.startswith('<'):
                    continue  # Skip lines that don't start with a tag
                lines.append(line)
            html = '\n'.join(lines)
            
        except Exception as e:
            logger.warning(f"Error parsing HTML with BeautifulSoup: {str(e)}")
            # Fallback to regex-based cleaning if BeautifulSoup fails
            html = ContentGenerator._fix_html_structure(html)
            
            # Remove any content not wrapped in HTML tags using regex
            # This is a fallback if BeautifulSoup fails
            html = re.sub(r'^[^<].*?$', '', html, flags=re.MULTILINE)
        
        # Fix any remaining HTML structure issues
        if not ContentGenerator._is_html_balanced(html):
            html = ContentGenerator._fix_html_structure(html)
        
        # Clean up any extra whitespace and ensure proper line breaks
        html = '\n'.join(line.strip() for line in html.split('\n') if line.strip())
        
        # Ensure the content is properly wrapped in a container if it contains any HTML
        if html.strip() and not (html.strip().startswith('<') and html.strip().endswith('>')):
            html = f'<div class="content-container">\n{html}\n</div>'
        
        return html
    
    @staticmethod
    def wrap_content_in_html(title: str, content: str) -> str:
        """Return the content as-is without any additional wrapping."""
        return content

    async def generate_blog_content(
        self, 
        keyword: str, 
        language: str, 
        blog_plan: Dict[str, Any], 
        category_names: List[str], 
        scraped_articles: Dict[str, List[str]], 
        custom_length_prompt: str = "",
        target_word_count: int = 2000,
        max_expansion_attempts: int = 2,  # Maximum number of expansion attempts
        backlinks: Optional[List[str]] = None,  # Add backlinks parameter with default None
    ) -> Dict[str, Any]:
        """
        Generate blog content using OpenAI API with robust expansion handling
        
        Args:
            keyword: Main keyword/topic
            language: Content language
            blog_plan: Blog structure and outline
            category_names: List of available categories
            scraped_articles: List of scraped articles
            custom_length_prompt: Custom prompt for content length
            target_word_count: Desired word count
            max_expansion_attempts: Maximum number of expansion attempts
            backlinks: Optional list of backlinks to include in the content
        Returns:
            Dict containing generated content and metadata
        """
        # Initialize section_chunks as an empty dict
        section_chunks = {}
        
        # Initialize backlinks as an empty list if not provided
        if backlinks is None:
            backlinks = []
        print(f"🔍 Starting blog content generation for: {keyword}")
        print(f"🔍 Target word count: {target_word_count}")
        print(f"🔍 Max expansion attempts: {max_expansion_attempts}")
        
        try:
            print("🔍 Generating content prompt...")
            
            if scraped_articles:
                print("🔍 Scraped articles exist:")
                # Use TF-IDF to get most relevant chunks
                relevant_chunks = self.get_most_relevant_chunks_langchain(
                    scraped_articles, 
                    keyword, 
                    top_k=3  # Get top 3 most relevant chunks
                )
                # Add to section_chunks under a general section
                if relevant_chunks:
                    section_chunks["rag_context"] = relevant_chunks
                    print(f"✅ Processed {len(relevant_chunks)} relevant chunks from scraped data")
                else:
                    print("⚠️ No relevant chunks found in scraped data")

            # Format backlinks for better visibility in logs
            if backlinks:
                print("🔍 Formatted backlinks:")
                for i, link in enumerate(backlinks, 1):
                    print(f"  {i}. {link}")
            
            content_prompt = get_blog_content_prompt(
                keyword=keyword,
                language=language,
                blog_plan=blog_plan,
                section_chunks=section_chunks
            )
            print("✅ Content prompt generated")
            
            # Log a sample of the prompt to verify backlinks are included
            prompt_sample = content_prompt[:500] + "..." if len(content_prompt) > 500 else content_prompt
            print(f"🔍 Prompt sample (first 500 chars):\n---\n{prompt_sample}\n---")
            
            # Add custom length prompt if provided
            if custom_length_prompt:
                content_prompt = custom_length_prompt + "\n\n" + content_prompt
            
            # Set max_tokens based on model (8000 for gpt-4o-mini, 4000 for gpt-3.5-turbo)
            max_tokens = 8000  # Default for gpt-4o-mini
                
            print(f"🔍 Using max_tokens: {max_tokens}")
            
            # Format the categories for the prompt
            category_list = '\n'.join([f"- {cat}" for cat in category_names])
            
            print("🔍 Sending request to OpenAI...")
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": (
                        "You are a professional content writer specializing in creating comprehensive, well-researched blog posts. Write ONLY in {language} language.\n\n"
                        "AVAILABLE CATEGORIES (you MUST select exactly one of these):\n"
                        f"{category_list}\n\n"
                        "You MUST ALWAYS start your response with a category selection in the format 'SELECTED_CATEGORY: [exact category name from the available categories]' before writing any content. "
                        "The category name must match EXACTLY (including case and accents) with one of the available categories.\n"
                        "If no category seems perfect, choose the best matching one. DO NOT make up new categories.\n\n"
                        "DO NOT include any h1 tags in your content - the title is provided separately. "
                        "IMPORTANT: Your entire response MUST be in valid HTML markup (not Markdown, not plain text). Use <h2>, <h3>, <p>, <ul>, <li>, <img>, <blockquote>, <strong>, <em>, etc. as appropriate. "
                        "Do not use any Markdown formatting. Return only HTML markup for the blog content."
                    )},
                    {"role": "user", "content": content_prompt + "\n\nIMPORTANT: "
                        "1. Start with SELECTED_CATEGORY: [exact category name] on its own line\n"
                        "2. Then provide the blog content in valid HTML markup only\n"
                        "3. Use only these HTML tags: <h2>, <h3>, <p>, <ul>, <li>, <img>, <blockquote>, <strong>, <em>\n"
                        "4. Do not include <h1> tags or any Markdown formatting"
                    }
                ],
                temperature=0.7,
                max_tokens=max_tokens  # Using 8000 tokens for gpt-4o-mini as requested
            )
            print("✅ Received response from OpenAI")
            
            generated_content = response.choices[0].message.content.strip()
            print(f"🔍 Raw generated content length: {len(generated_content)} characters")
            
            # Extract selected category
            selected_category_name = None
            lines = generated_content.splitlines()
            for i, line in enumerate(lines[:5]):
                if line.strip().startswith("SELECTED_CATEGORY:"):
                    selected_category_name = line.replace("SELECTED_CATEGORY:", "").strip()
                    lines.pop(i)
                    generated_content = "\n".join(lines).lstrip()
                    break
            
            # Clean up the generated content using centralized cleaning function
            generated_content = self._clean_generated_content(generated_content)
            
            # Calculate word count (only count visible text, not HTML tags)
            text_only = re.sub(r'<[^>]+>', ' ', generated_content)
            word_count = len(text_only.split())
            print(f"🔍 Initial word count: {word_count}/{target_word_count}")
            
            # If content is too short, try to expand it
            expansion_attempt = 0
            while word_count < target_word_count and expansion_attempt < max_expansion_attempts:
                expansion_attempt += 1
                print(f"⚠️ Content is too short ({word_count}/{target_word_count} words), expansion attempt {expansion_attempt}...")
                
                
                try:
                    # Generate the expansion prompt with backlinks
                    expansion_prompt = get_blog_expansion_prompt(
                        target_word_count=target_word_count,
                        generated_content=generated_content,
                    )
                    
                    if not expansion_prompt or not isinstance(expansion_prompt, str):
                        print("❌ Failed to generate valid expansion prompt")
                        break
                        
                    print(f"🔍 Sending expansion request to OpenAI (attempt {expansion_attempt})...")
                    
                    # Request content expansion with higher temperature for more creative expansion
                    expansion_response = await self.client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=[
                            {"role": "system", "content": "You are a professional content writer who specializes in creating comprehensive, detailed blog posts. Your task is to expand the provided content while maintaining its quality, structure, and formatting. Ensure all HTML tags are properly closed and the content ends with complete sentences."},
                            {"role": "user", "content": expansion_prompt}
                        ],
                        temperature=0.7,  # Slightly lower temperature for more focused expansion
                        max_tokens=8000,  # Using 8000 tokens for gpt-4o-mini as requested
                        top_p=0.9,
                        frequency_penalty=0.1,
                        presence_penalty=0.1
                    )
                    print("✅ Received expansion response from OpenAI")
                    
                    expanded_content = expansion_response.choices[0].message.content
                    
                    # Clean and validate the expanded content
                    expanded_content = self._clean_html_content(expanded_content)
                    
                    # Calculate new word count
                    new_text_only = re.sub(r'<[^>]+>', ' ', expanded_content)
                    new_word_count = len(new_text_only.split())
                    
                    print(f"🔍 Expanded content word count: {new_word_count} (was {word_count})")
                    
                    if new_word_count > word_count:  # Only update if we got more content
                        generated_content = expanded_content
                        word_count = new_word_count
                    else:
                        print("⚠️ Expansion did not increase word count, stopping expansion")
                        break
                        
                except Exception as e:
                    print(f"⚠️ Error during content expansion: {str(e)}")
                    if expansion_attempt == max_expansion_attempts:
                        print("⚠️ Max expansion attempts reached, using current content")
                    continue
            
            # Final cleanup and validation using the centralized cleaning function
            generated_content = self._clean_generated_content(generated_content)
            
            # Calculate final word count
            final_text_only = re.sub(r'<[^>]+>', ' ', generated_content)
            final_word_count = len(final_text_only.split())
            
            print(f"✅ Final content generated with {final_word_count} words")
            
            return {
                "success": True,
                "content": generated_content,
                "word_count": final_word_count,
            }
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"❌ Error in generate_blog_content: {str(e)}\n{error_trace}")
            return {
                "success": False,
                "error": f"Error generating blog content: {str(e)}"
            }
    def _clean_generated_content(self, content: str) -> str:
        """
        Clean and normalize generated HTML content by removing unwanted tags and formatting.
        
        Args:
            content: The HTML content to clean
            
        Returns:
            str: Cleaned HTML content
        """
        if not content:
            return ""
            
        # Remove CSS styles and scripts
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL)
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL)
        
        # Remove HTML, HEAD, BODY, DOCTYPE declarations
        content = re.sub(r'<!DOCTYPE[^>]*>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'<html[^>]*>|</html>', '', content, flags=re.IGNORECASE)
        content = re.sub(r'<head[^>]*>.*?</head>', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<body[^>]*>|</body>', '', content, flags=re.IGNORECASE)
        
        # Remove unwanted tags
        content = re.sub(r'<h1[^>]*>.*?</h1>', '', content, flags=re.DOTALL | re.IGNORECASE)
        
        # Clean up whitespace
        content = '\n'.join(line.strip() for line in content.split('\n') if line.strip())
        
        # Ensure proper HTML structure
        if not self._is_html_balanced(content):
            content = self._fix_html_structure(content)
            
        return content
        
    async def rephrase_content(self, content: str, target_word_count: int, language: str = "en", original_title: str = "", 
                             images: list = None, backlinks: list = None, video_links: str = None) -> dict:
        """
        Rephrase the given content to match the target word count and enhance with media.
        
        Args:
            content: The original content to rephrase
            target_word_count: Target word count for the rephrased content
            language: Target language code (default: "en")
            original_title: Original title to be rephrased (optional)
            images: List of image URLs to be included in the rephrased content (optional)
            backlinks: List of backlinks to be included in the rephrased content (optional)
            video_links: URL of a related video to be included (optional)
            
        Returns:
            dict: {
                'title': str,  # Rephrased title
                'content': str,  # Rephrased content with media
                'original_title': str,  # Original title
                'original_length': int,  # Word count of original content
                'rephrased_length': int,  # Word count of rephrased content
                'image_urls': list,  # List of processed image URLs
                'video_links': str  # URL of the included video (if any)
            }
        """
        try:
            print(f"🔄 Starting content rephrasing. Original title: '{original_title}'", flush=True)
            print(f"📝 Original content length: {len(content)} characters", flush=True)
            
            # First, ensure we have a clean title to work with
            clean_title = original_title.strip()
            rephrased_title = clean_title  # Default to original if we don't rephrase
            
            # Then rephrase the content with the title
            prompt = get_blog_rephrasing_prompt(
                original_title=clean_title,
                original_content=content,
                language=language
            )
            
            print(f"📋 Sending rephrasing prompt to OpenAI...", flush=True)
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a professional content rewriter."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=4000
            )
            
            rephrased = response.choices[0].message.content.strip()
            print(f"✅ Received rephrased content from OpenAI. Length: {len(rephrased)} characters", flush=True)
            try:
                # Find the first heading
                first_heading_match = re.search(r'<h[1-6][^>]*>.*?</h[1-6]>', rephrased, re.DOTALL)
                if first_heading_match:
                    # Remove the first heading from content
                    rephrased = rephrased[:first_heading_match.start()] + rephrased[first_heading_match.end():]
                    print("✅ Removed the first heading from content")
            except Exception as e:
                print(f"⚠️  Error removing first heading: {str(e)}")
                import traceback
                traceback.print_exc()
            # Debug: Save raw rephrased content
            with open('/tmp/rephrased_raw.txt', 'w', encoding='utf-8') as f:
                f.write(rephrased)
            
            # Extract title and content if they're in a specific format
            if "TITLE:" in rephrased and "CONTENT:" in rephrased:
                # If we have both TITLE: and CONTENT: markers, split them
                title_part, content_part = rephrased.split("CONTENT:", 1)
                rephrased_title = title_part.replace("TITLE:", "").strip()
                rephrased = content_part.strip()
                print(f"✅ Extracted title and content from response", flush=True)
            elif "CONTENT:" in rephrased:
                # If only CONTENT: marker is present, just extract content
                rephrased = rephrased.split("CONTENT:", 1)[1].strip()
                print(f"✅ Extracted content from response (no title found)", flush=True)
            
            # If we still don't have a rephrased title, try to extract one from content
            if not rephrased_title or rephrased_title == clean_title:
                # Look for markdown headings (## ) or HTML headings (<h2>)
                heading_match = re.search(r'<h[12]>(.*?)</h[12]>|^##\s*(.+?)$', rephrased, re.MULTILINE)
                if heading_match:
                    rephrased_title = (heading_match.group(1) or heading_match.group(2)).strip()
                    print(f"✅ Extracted title from content: {rephrased_title}", flush=True)
            
            # Clean the rephrased content
            cleaned_content = self._clean_html_content(rephrased)
            processed_images = []  # This will store only the processed image URLs that are actually used
            
            print(f"✅ Cleaned rephrased content. Length: {len(cleaned_content)} characters", flush=True)
            
            word_count = len(cleaned_content.split())
            print(f"✅ Content length: {word_count} words")
            print(f"✅ Processing {len(images) if images else 0} images" if images else "✅ No images to process", flush=True)
            
            # Process and insert media if available
            if images and isinstance(images, list) and len(images) > 0:
                print(f"🖼️  Starting image processing for {len(images)} images", flush=True)
                image_generator = ImageGenerator()
                processed_images = []  # Store processed image URLs
                
                # First, filter and process only spreadtheword.fr images
                valid_images = []
                for img in images:
                    if not img:
                        continue
                    # Check if image is from spreadtheword.fr or needs processing
                    if 'spreadtheword.fr' in img:
                        valid_images.append(img)
                        print(f"✅ Found valid image from spreadtheword.fr: {img}", flush=True)
                    else:
                        print(f"⚠️  Skipping non-spreadtheword.fr image: {img}", flush=True)
                
                # If we don't have enough valid images, process some from the original list
                if len(valid_images) < 2:
                    print(f"ℹ️  Only {len(valid_images)} valid images found, processing more...", flush=True)
                    for img in images:
                        if len(valid_images) >= 2:
                            break
                        if not img or 'spreadtheword.fr' in img:
                            continue
                        try:
                            print(f"🔄 Processing external image: {img}", flush=True)
                            
                            # Call the local API to process the image
                            async with aiohttp.ClientSession() as session:
                                payload = {"image_links": [img]}
                                try:
                                    async with session.post(
                                        "https://nigga.cemantix.net/generator/download-image/",
                                        json=payload,
                                        headers={"Content-Type": "application/json"}
                                    ) as response:
                                        if response.status == 200:
                                            result = await response.json()
                                            if result.get("status") == "completed" and result.get("results"):
                                                image_url = result["results"][0]["processed_url"]
                                                if 'spreadtheword.fr' in image_url:
                                                    valid_images.append(image_url)
                                                    print(f"✅ Processed and saved to spreadtheword.fr: {image_url}", flush=True)
                                                    continue
                                except Exception as e:
                                    print(f"⚠️  Error calling image processing API: {str(e)}", flush=True)
                        except Exception as e:
                            print(f"⚠️  Failed to process or invalid domain for image: {img}", flush=True)
                
                # Now process up to 2 valid images
                for i in range(min(2, len(valid_images))):
                    try:
                        img_url = valid_images[i]
                        print(f"📌 Processing valid image {i+1}: {img_url}", flush=True)
                        
                        # Only add to processed_images if not already there (to avoid duplicates)
                        if img_url not in processed_images:
                            processed_images.append(img_url)
                            print(f"✅ Added valid image {i+1}: {img_url}", flush=True)
                            
                            # Create image HTML with unique alt text
                            img_alt = f"{rephrased_title} - Image {i+1}"
                            img_tag = f'<div style="text-align: center; margin: 20px 0;">\n' \
                                     f'  <img src="{img_url}" alt="{img_alt}" style="max-width: 100%; height: auto;">\n' \
                                     f'</div>\n\n'
                            # For first unique image, add at the top
                            if len(processed_images) == 1:
                                cleaned_content = img_tag + cleaned_content
                                print(f"✅ Inserted first unique image at the top", flush=True)
                            # For second unique image, try to insert after 5th heading
                            elif len(processed_images) == 2:
                                headings = re.findall(r'<h[1-6][^>]*>.*?</h[1-6]>', cleaned_content)
                                if len(headings) >= 5:
                                    # Find the position of the 5th heading
                                    fifth_heading = headings[4]
                                    insert_pos = cleaned_content.find(fifth_heading) + len(fifth_heading)
                                    cleaned_content = cleaned_content[:insert_pos] + '\n' + img_tag + cleaned_content[insert_pos:]
                                    print(f"✅ Inserted second unique image after 5th heading", flush=True)
                                else:
                                    # If less than 5 headings, insert after first paragraph
                                    para_match = re.search(r'</p>', cleaned_content)
                                    if para_match:
                                        insert_pos = para_match.end()
                                        cleaned_content = cleaned_content[:insert_pos] + '\n' + img_tag + cleaned_content[insert_pos:]
                                        print(f"✅ Inserted second unique image after first paragraph", flush=True)
                                    else:
                                        # Fallback to end of content
                                        cleaned_content += '\n' + img_tag
                                        print(f"✅ Inserted second unique image at the end (no suitable position found)", flush=True)
                                
                    except Exception as e:
                        print(f"⚠️  Error processing image {i+1}: {str(e)}", flush=True)
                        import traceback
                        traceback.print_exc()
                
            # Add video at the end if available
            if video_links:
                try:
                    print(f"🎥 Processing video link: {video_links}", flush=True)
                    # Ensure the video URL is properly formatted
                    if not video_links.startswith(('http://', 'https://')):
                        video_links = f'https://{video_links}'
                        
                    video_html = f'<div style="text-align: center; margin: 40px 0;">\n' \
                               f'  <h3>Related Video</h3>\n' \
                               f'  <div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden; max-width: 100%;">\n' \
                               f'    <iframe src="{video_links}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;" frameborder="0" allowfullscreen></iframe>\n' \
                               f'  </div>\n' \
                               f'</div>'
                    cleaned_content += '\n\n' + video_html
                    print(f"✅ Added video to the end of content", flush=True)
                except Exception as e:
                    print(f"⚠️  Error adding video: {str(e)}", flush=True)
                    import traceback
                    traceback.print_exc()
                
                if not processed_images:
                    print("⚠️  No valid images were processed and injected", flush=True)
                else:
                    print(f"✅ Successfully processed {len(processed_images)} images", flush=True)
            
            # Clean up any potential HTML issues after modifications
            cleaned_content = self._clean_html_content(cleaned_content)
            
            # Ensure we have exactly 2 images from spreadtheword.fr
            filtered_processed_images = []
            for img in processed_images:
                if 'spreadtheword.fr' in img and len(filtered_processed_images) < 2:
                    filtered_processed_images.append(img)
            
            # If we still don't have 2 images, add placeholders
            while len(filtered_processed_images) < 2:
                # Add a placeholder image from spreadtheword.fr
                placeholder_url = 'https://spreadtheword.fr/images/placeholder.jpg'
                filtered_processed_images.append(placeholder_url)
                print(f"ℹ️  Added placeholder image {len(filtered_processed_images)}", flush=True)
            
            # Log the images we're including
            if filtered_processed_images:
                print(f"✅ Including {len(filtered_processed_images)} image URLs in the final payload:")
                for url in filtered_processed_images:
                    print(f"    - {url}")
            else:
                print("⚠️  No valid images found to include in the payload")
            
            # Calculate final word count after all processing
            final_word_count = len(re.sub(r'<[^>]+>', ' ', cleaned_content).split())
            print(f"📊 Final content statistics:")
            print(f"   - Original length: {len(content.split())} words")
            print(f"   - Final length: {final_word_count} words")
            print(f"   - Included images: {len(filtered_processed_images)}")
            logger.info(f"✅ Final content statistics:")
            logger.info(f"   - Original length: {len(content.split())} words")
            logger.info(f"   - Final length: {final_word_count} words")
            logger.info(f"   - Included images: {len(filtered_processed_images)}")
            logger.info(f"   - Images: {filtered_processed_images}")
            
            return {
                'title': rephrased_title,
                'content': cleaned_content,
                'original_title': clean_title,
                'original_length': len(content.split()),
                'rephrased_length': final_word_count,
                'image_urls': filtered_processed_images,
                'video_links': video_links if video_links else None
            }
            
        except Exception as e:
            print(f"Error in rephrase_content: {str(e)}")
            raise

        async def generate_image_prompts(self, keyword: str, language: str = "en") -> List[Dict[str, str]]:
            """
            Generate specific image prompts for a given keyword
            """
            try:
                image_prompt_request = f"""Generate two detailed, realistic image prompts for an article about: "{keyword}"

    The images should be:
    1. Professional and relevant to the article topic
    2. Realistic and suitable for a blog post
    3. Descriptive enough for image generation

    Return ONLY a JSON array with exactly 2 image prompt objects:
    [
        {{
            "prompt": "Detailed description of first image",
            "purpose": "Purpose of this image in the article"
        }},
        {{
            "prompt": "Detailed description of second image", 
            "purpose": "Purpose of this image in the article"
        }}
    ]

    Make the prompts specific to the topic and avoid generic descriptions."""

                response = await self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "You are an expert at creating detailed, realistic image prompts for blog articles. Always respond with valid JSON only."},
                        {"role": "user", "content": image_prompt_request}
                    ],
                    temperature=0.7,
                    max_tokens=4000  # Using 4000 tokens for gpt-3.5-turbo as requested
                )
                
                raw_response = response.choices[0].message.content.strip()
                try:
                    image_prompts = json.loads(raw_response)
                    if isinstance(image_prompts, list) and len(image_prompts) >= 2:
                        return image_prompts[:2]  # Return only first 2 prompts
                    else:
                        print(f"⚠️ Invalid image prompts format, using fallback")
                        return self.get_fallback_image_prompts(keyword)
                except json.JSONDecodeError:
                    print(f"⚠️ Error parsing image prompts JSON, using fallback")
                    return self.get_fallback_image_prompts(keyword)
                    
            except Exception as e:
                print(f"❌ Error generating image prompts: {str(e)}")
                return self.get_fallback_image_prompts(keyword)

        def get_fallback_image_prompts(self, keyword: str) -> List[Dict[str, str]]:
            """
            Provide fallback image prompts when generation fails
            """
            return [
                {
                    "prompt": f"Professional photograph related to {keyword}, high quality, editorial style",
                    "purpose": "Main article image"
                },
                {
                    "prompt": f"Infographic or diagram illustrating key concepts about {keyword}, clean design",
                    "purpose": "Supporting visual content"
                }
            ]
        def create_image_prompts_from_title(self, title: str, original_keyword: str) -> List[Dict[str, str]]:
            """
            Create specific image prompts based on the title and original keyword
            """
            # Extract key concepts from title and keyword
            title_lower = title.lower()
            keyword_lower = original_keyword.lower()
            
            # Common product/tech keywords that suggest specific image types
            if any(word in title_lower or word in keyword_lower for word in ['kindle', 'tablet', 'device', 'phone', 'laptop']):
                return [
                    {
                        "prompt": f"Professional product photography of {original_keyword}, clean background, high resolution, editorial style",
                        "purpose": "Main product showcase image"
                    },
                    {
                        "prompt": f"Comparison chart or infographic showing {original_keyword} features and benefits, modern design",
                        "purpose": "Feature comparison visual"
                    }
                ]
            elif any(word in title_lower or word in keyword_lower for word in ['deal', 'sale', 'discount', 'price', 'offer']):
                return [
                    {
                        "prompt": f"Price tag or discount banner with {original_keyword}, shopping concept, professional photography",
                        "purpose": "Deal/pricing visual"
                    },
                    {
                        "prompt": f"Comparison of original vs discounted prices for {original_keyword}, savings visualization",
                        "purpose": "Savings comparison chart"
                    }
                ]
            elif any(word in title_lower or word in keyword_lower for word in ['amazon', 'prime', 'shopping']):
                return [
                    {
                        "prompt": f"Amazon Prime Day shopping concept with {original_keyword}, e-commerce theme, professional photography",
                        "purpose": "Prime Day shopping visual"
                    },
                    {
                        "prompt": f"Online shopping cart or wishlist with {original_keyword}, digital commerce interface",
                        "purpose": "E-commerce interface visual"
                    }
                ]
            else:
                # Generic but specific prompts based on the title
                return [
                    {
                        "prompt": f"Professional editorial image representing '{title}', high quality photography, relevant to the topic",
                        "purpose": "Main article image"
                    },
                    {
                        "prompt": f"Infographic or diagram related to '{original_keyword}', clean modern design, informative visual",
                        "purpose": "Supporting informational visual"
                    }
                ] 

class ImageGenerator:
    image_semaphore = asyncio.Semaphore(2)
    async def image_generation_process(self, prompt: str, keyword: str=None, size: str = "1024x1024", max_attempts: int = 3) -> Optional[str]:
        """
        Generate an image from a prompt with retry logic.
        
        Args:
            prompt: The text prompt for image generation
            keyword: Used for generating the filename
            size: The dimensions of the image (e.g., "1024x1024")
            max_attempts: Maximum number of generation attempts
            
        Returns:
            str: Public URL of the generated image, or None if all attempts fail
        """
        for attempt in range(1, max_attempts + 1):
            try:
                print(f"\n🔄 Attempt {attempt}/{max_attempts} - Generating image...")
                
                # Generate image
                result = await self.generate_image_bfl(prompt, size)
                
                if not result or 'url' not in result:
                    print(f"❌ Attempt {attempt} failed - No image URL in response")
                    if attempt < max_attempts:
                        await asyncio.sleep(2 ** attempt)  # Exponential backoff
                    continue
                    
                image_url = result['url']
                print(f"✅ Image generated successfully on attempt {attempt}")
                
                # Generate filename
                image_result = await self.save_and_process_image(image_url, keyword)
                
                return image_result
                
            except Exception as e:
                print(f"⚠️  Attempt {attempt} failed: {str(e)}")
                if attempt < max_attempts:
                    retry_delay = min(5 * attempt, 30)  # Cap at 30 seconds
                    print(f"⏳ Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                continue
        
        print("❌ All image generation attempts failed")
        return None

    def _add_watermark(self, image_path, watermark_path, output_path):
        """
        Add a watermark to the given image.
        
        Args:
            image_path: Path to the source image
            watermark_path: Path to the watermark image
            output_path: Path to save the watermarked image
            
        Returns:
            str: Path to the saved watermarked image
        """
        from PIL import Image, ImageEnhance, ImageDraw, ImageFont, ImageFilter
        import math
        
        try:
            # Open the original image and convert to RGBA
            with Image.open(image_path).convert("RGBA") as original_image, \
                 Image.open(watermark_path).convert("RGBA") as watermark:
                
                # Calculate new size (20% of the original watermark size)
                watermark_width, watermark_height = watermark.size
                scale_factor = 0.2
                new_size = (int(watermark_width * scale_factor), int(watermark_height * scale_factor))
                
                # Resize the watermark
                watermark = watermark.resize(new_size, Image.LANCZOS)
                
                # Create a transparent layer for the watermark
                watermark_layer = Image.new('RGBA', original_image.size, (0, 0, 0, 0))
                
                # Calculate tiling - we'll place watermarks diagonally
                spacing = int(max(watermark.size) * 1.5)  # Space between watermarks
                
                # Tile the watermark diagonally across the image
                for i in range(-watermark_layer.height // spacing, watermark_layer.width // spacing + 1):
                    # Calculate position for diagonal tiling
                    x = i * spacing
                    y = i * spacing
                    
                    # Create a rotated version of the watermark (45 degrees)
                    rotated_watermark = watermark.rotate(45, expand=True, resample=Image.BICUBIC)
                    
                    # Adjust opacity (50% of original)
                    alpha = rotated_watermark.split()[3]
                    alpha = ImageEnhance.Brightness(alpha).enhance(0.7)
                    rotated_watermark.putalpha(alpha)
                    
                    # Paste the watermark at the calculated position
                    watermark_layer.paste(
                        rotated_watermark,
                        (x, y),
                        rotated_watermark
                    )
                
                # Create a copy of the original image to apply the watermark
                watermarked = original_image.copy()
                
                # Composite the watermark layer onto the image
                watermarked = Image.alpha_composite(watermarked, watermark_layer)
                
                # Save the result
                watermarked.save(output_path, format='WEBP', quality=65, method=6)
                return output_path
                
        except Exception as e:
            logger.error(f"Error in _add_watermark: {str(e)}", exc_info=True)
            raise

    async def save_and_process_image(self, image_url: str, keyword: str) -> str:
        """
        Save image to disk in WebP format with 65% quality, add watermark if configured,
        and return the public URL. If saving fails, returns the original image URL.
        
        Args:
            image_url: URL of the image to download
            keyword: Keyword used for generating the filename
            
        Returns:
            str: Public URL of the saved image, or the original URL if saving fails
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"[save_and_process_image] Starting image processing")
        logger.info(f"[save_and_process_image] Original URL: {image_url}")
        logger.info(f"[save_and_process_image] Keyword: {keyword}")
        
        from PIL import Image, ImageFile, ImageEnhance
        import io
        import aiohttp
        import os
        import re
        import random
        import tempfile
        
        # Store the original URL to return if saving fails
        original_url = image_url
        logger.info(f"[save_and_process_image] Original URL stored: {original_url}")

        # Generate a safe filename
        # Get save directory from environment or use a default
        save_dir = os.getenv("IMAGES_SAVE_DIR", "/var/www/spreadtheword.fr/images")
        logger.info(f"[save_and_process_image] Using save directory: {save_dir}")

        # Generate a safe filename
        base_name = re.sub(r'[^a-zA-Z0-9]', '', str(keyword).replace(' ', ''))[:20]
        filename = f"{base_name}.webp"
        counter = 1
        filepath = ""

        # Check if file exists and find next available filename
        while True:
            filepath = os.path.join(save_dir, filename)
            if not os.path.exists(filepath):
                break
            filename = f"{base_name}{counter}.webp"
            counter += 1

        logger.info(f"[save_and_process_image] Generated filename: {filename}")
        
        try:
            # Create directory if it doesn't exist
            os.makedirs(save_dir, exist_ok=True, mode=0o777)
            filepath = os.path.join(save_dir, filename)
            
            # Check if we have write permissions
            if not os.access(os.path.dirname(filepath), os.W_OK):
                logger.warning(f"No write permissions in directory: {os.path.dirname(filepath)}")
                return original_url
            
            # If the URL is a local file path, just return it
            if image_url.startswith('file://'):
                local_path = image_url.replace('file://', '')
                logger.info(f"[save_and_process_image] Using existing local image: {local_path}")
                return local_path  # Return the local path
            
            # Set timeout for the request
            timeout = aiohttp.ClientTimeout(total=60)  # 60 seconds timeout
            
            logger.info(f"[save_and_process_image] Attempting to download image from: {image_url}")
            
            # Download the image
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(image_url) as response:
                    logger.info(f"[save_and_process_image] Image download status: {response.status}")
                    
                    if response.status != 200:
                        error_msg = f"Failed to download image: {image_url} (Status: {response.status}). Using original URL."
                        logger.error(f"[save_and_process_image] {error_msg}")
                        return original_url
                    
                    # Read the image data
                    img_data = await response.read()
                    logger.info(f"[save_and_process_image] Successfully read {len(img_data)} bytes of image data")
                    
                    try:
                        # Convert to WebP with 65% quality
                        with Image.open(io.BytesIO(img_data)) as img:
                            logger.info(f"[save_and_process_image] Opened image with mode: {img.mode}, size: {img.size}")
                            
                            try:
                                # Convert to RGB if necessary (for PNG with transparency)
                                if img.mode in ('RGBA', 'LA') or (img.mode == 'P' and 'transparency' in img.info):
                                    logger.info("[save_and_process_image] Converting image from transparent to RGB")
                                    background = Image.new('RGB', img.size, (255, 255, 255))
                                    
                                    try:
                                        # Handle different image modes and transparency
                                        if img.mode == 'RGBA':
                                            # For RGBA, use the alpha channel as mask if available
                                            if img.split()[-1] is not None:  # Check if alpha channel exists
                                                background.paste(img, mask=img.split()[-1])
                                            else:
                                                background.paste(img)
                                        else:
                                            # For other modes, just paste without mask
                                            background.paste(img)
                                        img = background
                                    except Exception as paste_error:
                                        logger.error(f"[save_and_process_image] Error pasting image with transparency: {str(paste_error)}")
                                        # Fallback to simple paste if mask fails
                                        background.paste(img.convert('RGB'))
                                        img = background
                            except Exception as img_convert_error:
                                logger.error(f"[save_and_process_image] Error converting image: {str(img_convert_error)}")
                                # If conversion fails, try to continue with the original image
                                if img.mode != 'RGB':
                                    img = img.convert('RGB')
                            
                            # Save the original image first
                            with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as temp_file:
                                temp_path = temp_file.name
                                img.save(temp_path, format='WEBP', quality=65, method=6)
                            
                            # Get the path to the watermark image - first check environment variable, then default location
                            watermark_path = os.getenv("WATERMARK_IMAGE_PATH")
                            if not watermark_path or not os.path.exists(watermark_path):
                                # Fall back to the default watermark location
                                watermark_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'watermark', 'spreadword.webp')
                            
                            logger.info(f"[save_and_process_image] Checking watermark at: {watermark_path}")
                            
                            if os.path.exists(watermark_path):
                                try:
                                    # Verify the watermark file is readable
                                    with Image.open(watermark_path) as test_img:
                                        logger.info(f"[save_and_process_image] Watermark image is valid. Mode: {test_img.mode}, Size: {test_img.size}")
                                    
                                    # Create a temporary file for the watermarked image
                                    with tempfile.NamedTemporaryFile(suffix='.webp', delete=False) as watermarked_temp_file:
                                        watermarked_path = watermarked_temp_file.name
                                    
                                    logger.info(f"[save_and_process_image] Applying watermark from: {watermark_path}")
                                    logger.info(f"[save_and_process_image] Source image: {temp_path}, Output: {watermarked_path}")
                                    
                                    # Apply watermark
                                    self._add_watermark(temp_path, watermark_path, watermarked_path)
                                    
                                    # Verify the watermarked image was created
                                    if os.path.exists(watermarked_path) and os.path.getsize(watermarked_path) > 0:
                                        temp_path = watermarked_path  # Use the watermarked image
                                        logger.info(f"[save_and_process_image] Successfully applied watermark. New temp path: {temp_path}")
                                    else:
                                        raise Exception("Watermarked file was not created or is empty")
                                        
                                except Exception as e:
                                    logger.error(f"[save_and_process_image] Error applying watermark: {str(e)}", exc_info=True)
                                    # Clean up any partial files
                                    if 'watermarked_path' in locals() and os.path.exists(watermarked_path):
                                        try:
                                            os.unlink(watermarked_path)
                                        except:
                                            pass
                                    # Continue with unwatermarked image if watermarking fails
                            else:
                                logger.warning(f"[save_and_process_image] Watermark file not found at: {watermark_path}")
                                logger.info(f"[save_and_process_image] Current working directory: {os.getcwd()}")
                                logger.info(f"[save_and_process_image] Directory contents: {os.listdir(os.path.dirname(watermark_path))}")
                            
                            # Move the final (watermarked or original) image to the target location
                            try:
                                shutil.move(temp_path, filepath)
                                logger.info(f"[save_and_process_image] Successfully saved image to {filepath}")
                            except Exception as e:
                                logger.error(f"[save_and_process_image] Error moving file to {filepath}: {str(e)}")
                                return original_url
                        
                        # Set proper permissions
                        os.chmod(filepath, 0o644)
                        
                        # Clean up any temporary files that might be left
                        if os.path.exists(temp_path):
                            try:
                                os.unlink(temp_path)
                            except:
                                pass
                        
                        # Return the full public URL with domain
                        public_url = f"https://spreadtheword.fr/images/{filename}"  # Adjust this based on your URL structure
                        logger.info(f"[save_and_process_image] Successfully saved image to {filepath}")
                        logger.info(f"[save_and_process_image] Public URL: {public_url}")
                        
                        return public_url
                    
                    except Exception as e:
                        error_msg = f"Error processing image {image_url}: {str(e)}. Using original URL."
                        logger.error(f"[save_and_process_image] {error_msg}", exc_info=True)
                        return original_url
    
        except Exception as e:
            error_msg = f"Error saving image {image_url}: {str(e)}. Using original URL."
            logger.error(f"[save_and_process_image] {error_msg}", exc_info=True)
            return original_url
            
        except PermissionError as e:
            error_msg = f"Permission denied when saving image to directory: {os.path.dirname(filepath) if filepath else 'unknown'}. Error: {str(e)}"
            logger.error(f"[save_and_process_image] {error_msg}")
            logger.info("[save_and_process_image] Using original URL due to permission error")

            if os.geteuid() == 0:  # If running as root
                try:
                    os.chmod(save_dir, 0o777)
                    logger.info(f"[save_and_process_image] Attempted to fix permissions on {save_dir}")
                except Exception as perm_error:
                    logger.error(f"[save_and_process_image] Failed to fix permissions: {str(perm_error)}")
            return original_url
            
        except Exception as e:
            error_msg = f"Unexpected error processing image {image_url}: {str(e)}"
            logger.error(f"[save_and_process_image] {error_msg}", exc_info=True)
            logger.info("[save_and_process_image] Using original URL due to unexpected error")
            return original_url