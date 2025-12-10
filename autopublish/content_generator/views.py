from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
import json
import re
import os
from datetime import datetime
from pathlib import Path
from openai import AsyncOpenAI
from .base import ContentGenerator, ImageGenerator

# Ensure the data directory exists with sudo
import subprocess
import sys

# DATA_DIR = Path("data")
# if not DATA_DIR.exists():
#     try:
#         # Try to create directory with sudo
#         subprocess.run(['sudo', 'mkdir', '-p', str(DATA_DIR)], check=True)
#         subprocess.run(['sudo', 'chown', '-R', f'{os.getuid()}:{os.getgid()}', str(DATA_DIR)], check=True)
#     except subprocess.CalledProcessError as e:
#         print(f"Error: Failed to create directory with sudo: {e}", file=sys.stderr)
#         raise
DATA_DIR = Path("data")
os.makedirs(DATA_DIR, exist_ok=True)

# Initialize OpenAI client
client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

async def rephrase_news_content(request=None, **kwargs):
    """
    Rephrase news content. Can be called as a view or directly.
    
    Returns:
        dict: A dictionary with the following keys:
            - status: 'success' or 'error'
            - rephrased_content: The rephrased content (if successful)
            - original_length: Word count of original content
            - rephrased_length: Word count of rephrased content
            - error: Error message (if any)
    """
    try:
        # Get parameters from request or kwargs
        if isinstance(request, dict):
            data = request
        elif request and hasattr(request, 'body'):
            data = json.loads(request.body)
        else:
            data = kwargs

        title = data.get('title', '')
        content = data.get('content', '')
        language = data.get('language', 'fr')
        target_word_count = int(data.get('target_word_count', 2000))
        images = data.get('images', data.get('image_links', []))  # Support both 'images' and 'image_links' for backward compatibility
        backlinks = data.get('backlinks', [])  # Default to empty list if not provided
        video_links = data.get('video_links')  # Single video URL or None


        if not content:
            raise ValueError("Content is required")

        # Call the content generator
        content_generator = ContentGenerator()
        rephrase_result = await content_generator.rephrase_content(
            content=content,
            target_word_count=target_word_count,
            language=language,
            original_title=title,
            images=images,
            backlinks=backlinks,
            video_links=video_links
        )
        
        # Prepare the result
        result = {
            'status': 'success',
            'title': rephrase_result.get('title', title),
            'rephrased_content': rephrase_result['content'],
            'original_title': rephrase_result.get('original_title', title),
            'original_content': content,
            'original_length': rephrase_result.get('original_length', len(content.split())),
            'rephrased_length': rephrase_result.get('rephrased_length', len(rephrase_result.get('content', '').split())),
            'timestamp': datetime.utcnow().isoformat(),
            'image_urls': rephrase_result.get('image_urls', images),
            'selected_category': rephrase_result.get('selected_category', '')
        }
        
        # File saving to disk is disabled as per request
        # try:
        #     timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        #     filename = f"rephrased_{timestamp}.json"
        #     filepath = DATA_DIR / filename
            
        #     with open(filepath, 'w', encoding='utf-8') as f:
        #         json.dump(result, f, ensure_ascii=False, indent=2)
                
        #     result['saved_filename'] = str(filepath)
            
        # except Exception as save_error:
        #     # Don't fail the whole request if saving fails
        #     result['save_error'] = str(save_error)
        
        result['file_saving_disabled'] = True
        
        return result
        
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

# View decorator for HTTP requests
@csrf_exempt
@require_http_methods(["POST"])
async def rephrase_news_content_view(request):
    """
    HTTP endpoint for rephrasing news content.
    
    Expected POST data:
    {
        "content": "Original article content to rephrase",
        "title": "Article title (optional)",
        "target_word_count": 1000,  # optional, defaults to 1000
        "language": "en"  # optional, defaults to "en"
    }
    
    Returns:
        JSON response with rephrased content or error message
    """
    try:
        # Parse the request body
        try:
            data = json.loads(request.body)
            
            # Validate required fields
            if 'content' not in data or not data['content'].strip():
                return JsonResponse({
                    'status': 'error',
                    'error': 'Content is required and cannot be empty'
                }, status=400)
                
            # Set default values if not provided
            data.setdefault('title', '')
            data.setdefault('target_word_count', 1000)
            data.setdefault('language', 'en')
            
        except json.JSONDecodeError:
            return JsonResponse({
                'status': 'error',
                'error': 'Invalid JSON in request body'
            }, status=400)
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'error': f'Error processing request: {str(e)}'
            }, status=400)
            
        try:
            # Call the rephrase function
            result = await rephrase_news_content(data)
        
            # Return the result as JSON
            return JsonResponse(
                result,
                status=200 if result.get('status') == 'success' else 400,
                json_dumps_params={'ensure_ascii': False, 'indent': 2},
                content_type='application/json; charset=utf-8'
            )
            
        except Exception as e:
            return JsonResponse({
                'status': 'error',
                'error': f'Error while rephrasing content: {str(e)}'
            }, status=500)
            
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': f'An unexpected error occurred: {str(e)}'
        }, status=500)

@csrf_exempt
@require_http_methods(["POST"])
async def generate_blog_from_keyword(request):
    """
    API endpoint to generate blog content from a keyword.
    
    Expected POST data:
    {
        "keyword": "main topic",
        "language": "en",
        "min_words": 1000,
        "categories": ["technology", "business"],  # optional
        "scraped_data": [  # optional
            {
                "snippet": "text snippet 1",
                "description": "description 1"
            },
            {
                "snippet": "text snippet 2",
                "description": "description 2"
            }
        ]
    }
    
    Returns:
        JSON response with generated blog content or error message
    """
    try:
        # Parse request data
        data = json.loads(request.body)
        keyword = data.get('keyword', '').strip()
        language = data.get('language', 'en')
        min_words = int(data.get('min_words', 2000))  # Updated default from 1000 to 2000 words
        available_categories = data.get('available_categories', [])
        image_links = data.get('image_links', [])
        backlinks = data.get('backlinks', [])
        video_link = data.get('video_link', '')
                
        # Input validation
        if not keyword:
            return JsonResponse(
                {"error": "Keyword is required"}, 
                status=400
            )
            
        # Initialize content generator
        generator = ContentGenerator()

        # Extract scraped_data if provided
        scraped_data = data.get('scraped_data')
        if scraped_data is not None:
            print(f"ℹ️ Received {len(scraped_data)} items in scraped_data")
        
        print(f"ℹ️ Available categories: {available_categories}")
        
        # Generate blog content with optional scraped_data for RAG
        result = await generator.keyword_generation(
            keyword=keyword,
            language=language,
            min_length=min_words,
            image_links=image_links,
            max_retries=3,
            scraped_data=scraped_data,
            available_categories=available_categories,
            backlinks=backlinks,
            video_link=video_link
        )
        
        if not result.get('success', False):
            return JsonResponse(
                {"error": result.get('error', 'Failed to generate content')},
                status=400
            )
            
        # Extract only necessary fields for the response
        response_data = {
            "status": "success",
            "title": result.get('title'),
            "content": result.get('content'),
            "category": result.get('category'),
            "word_count": result.get('word_count', 0),
            "image_urls": result.get('image_urls', []),
            "meta_description": result.get('meta_description', ""),
            "image_prompts": result.get('image_prompts', []),
            "selected_category_name": result.get('selected_category_name')
        }
        
        return JsonResponse(response_data)
        
    except json.JSONDecodeError:
        return JsonResponse(
            {"error": "Invalid JSON data"}, 
            status=400
        )
    except ValueError as e:
        return JsonResponse(
            {"error": f"Invalid input: {str(e)}"}, 
            status=400
        )
    except Exception as e:
        return JsonResponse(
            {"error": f"An error occurred: {str(e)}"}, 
            status=500
        )
@csrf_exempt
@require_http_methods(["POST"])
async def generate_image(request):
    """
    Generate images from an array of prompts.
    
    Expected POST data:
    {
        "prompts": ["prompt 1", "prompt 2", ...],  # Array of image generation prompts
        "size": "1024x1024"  # Optional, default is 1024x1024
    }
    
    Returns:
        JSON response with array of image URLs or error message
    """
    try:
        data = json.loads(request.body)
        prompts = data.get('prompts', [])
        size = data.get('size', '1024x1024')
        
        if not prompts:
            return JsonResponse(
                {'error': 'No prompts provided'}, 
                status=400
            )
            
        # Generate images (this function will be implemented in base.py)
        image_generator = ImageGenerator()
        image_urls = []
        
        for prompt in prompts:
            try:
                keyword = prompt.split(".")[0]
                result = await image_generator.image_generation_process(prompt, keyword=keyword, size=size)
                if result.get('url'):
                    image_urls.append(result['url'])
            except Exception as e:
                print(f"Error generating image for prompt '{prompt}': {str(e)}")
                image_urls.append(None)  # Keep the array length consistent
        
        return JsonResponse({
            'status': 'success',
            'image_urls': image_urls,
            'prompts': prompts
        })
        
    except json.JSONDecodeError:
        return JsonResponse(
            {'error': 'Invalid JSON data'}, 
            status=400
        )
    except Exception as e:
        return JsonResponse(
            {'error': f'An error occurred: {str(e)}'}, 
            status=500
        )
async def download_image(request):
    try:
        data = json.loads(request.body)
        image_links = data.get('image_links')
        if not image_links:
            return JsonResponse(
                {'error': 'No image links provided'}, 
                status=400
            )
        
        results = []
        image_generator = ImageGenerator()
        
        for image_link in image_links:
            try:
                # Use the last part of the URL as the keyword
                keyword = image_link.split('/')[-1].split('.')[0]  # Remove file extension
                result = await image_generator.save_and_process_image(image_link, keyword)
                results.append({
                    'original_url': image_link,
                    'processed_url': result,
                    'status': 'success'
                })
            except Exception as e:
                results.append({
                    'original_url': image_link,
                    'error': str(e),
                    'status': 'error'
                })
        
        return JsonResponse({
            'status': 'completed',
            'results': results
        })
        
    except json.JSONDecodeError:
        return JsonResponse(
            {'error': 'Invalid JSON data'}, 
            status=400
        )
    except Exception as e:
        return JsonResponse(
            {'error': f'An error occurred: {str(e)}'}, 
            status=500,
            safe=False
        )
