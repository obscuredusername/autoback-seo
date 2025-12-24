import asyncio
import logging
from celery import shared_task
from celery.utils.log import get_task_logger
from asgiref.sync import async_to_sync

# Import the ContentGenerator class from base
from .base import ContentGenerator

# Create an instance of ContentGenerator
content_generator = ContentGenerator()
logger = get_task_logger(__name__)

@shared_task(bind=True, name='autopublish.content_generator.tasks.get_blog_plan')
def get_blog_plan(self, *args, **kwargs):
    """Generate a blog plan for the given keyword."""
    if args and isinstance(args[0], dict):
        params = args[0]
        keyword = params.get('keyword')
        language = params.get('language', 'en')
        country = params.get('country', 'us')
        available_categories = params.get('available_categories', [])
        plan_id = params.get('plan_id')
    else:
        keyword = kwargs.get('keyword')
        language = kwargs.get('language', 'en')
        country = kwargs.get('country', 'us')
        available_categories = kwargs.get('available_categories', [])
        plan_id = kwargs.get('plan_id')
    
    if not keyword:
        return {'status': 'error', 'message': "No keyword provided", 'data': None}
    
    async def generate_plan():
        try:
            return await content_generator.generate_blog_plan(
                keyword=keyword,
                language=language,
                available_categories=available_categories
            )
        except Exception as e:
            logger.error(f"Error in generate_blog_plan: {str(e)}", exc_info=True)
            return None
    
    try:
        task_id = self.request.id if hasattr(self, 'request') else 'unknown'
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        blog_plan = loop.run_until_complete(generate_plan())
        loop.close()
        
        if not isinstance(blog_plan, dict): 
            blog_plan = {}
        if 'title' not in blog_plan: 
            blog_plan['title'] = f"Blog about {keyword}"
        if 'sections' not in blog_plan: 
            blog_plan['sections'] = []
        
        return {
            'status': 'success',
            'task_id': task_id,
            'message': 'Blog plan generated successfully',
            'data': blog_plan
        }
    except Exception as e:
        return {'status': 'error', 'message': str(e), 'data': None}

@shared_task(bind=True, name='autopublish.content_generator.tasks.generate_keyword_content')
def generate_keyword_content(self, *args, **kwargs):
    """Task for generating keyword content."""
    task_id = self.request.id if hasattr(self, 'request') else 'unknown'
    try:
        # Ensure we're working with a dictionary and make a copy
        data = args[0].copy() if args and isinstance(args[0], dict) else kwargs.copy()
        
        # Extract all parameters with proper defaults
        keyword = data.get('keyword', '')
        language = data.get('language', 'en')
        blog_plan = data.get('blog_plan', {})
        category_info = data.get('category', {})
        image_urls = data.get('image_urls', [])
        scraped_data = data.get('scraped_data', [])
        
        # Get target_word_count from min_words if target_word_count is not provided
        target_word_count = data.get('target_word_count') or data.get('min_words', 2000)
        target_word_count = int(target_word_count)  # Ensure it's an integer
        
        logger.info(f"🔢 Starting content generation with target word count: {target_word_count}")
        
        title = blog_plan.get('title', keyword)
        
        async def generate_content(word_count=target_word_count):
            logger.info(f"🔢 Inside generate_content, word count: {word_count}")
            
            section_chunks = {'target_word_count': word_count}
            
            if scraped_data:
                texts = []
                if isinstance(scraped_data, list):
                    for item in scraped_data:
                        if isinstance(item, str):
                            texts.append(item)
                        elif isinstance(item, dict):
                            for field in ['snippet', 'description', 'text', 'content', 'body']:
                                if item.get(field):
                                    texts.append(item[field])
                                    break
                
                if texts:
                    relevant_chunks = content_generator.get_most_relevant_chunks_langchain(texts, keyword)
                    if relevant_chunks:
                        section_chunks["rag_context"] = relevant_chunks

            return await content_generator.generate_blog_content(
                keyword=title,
                language=language,
                blog_plan=blog_plan,
                category_names=[category_info.get('name')] if category_info.get('name') else [],
                section_chunks=section_chunks,
                target_word_count=word_count,
                max_expansion_attempts=2,
                backlinks=None
            )

        # Call the async function
        result = async_to_sync(generate_content)()
        
        if not result or 'content' not in result:
            raise ValueError("No content generated")
        
        generated_title = result.get('title', title)
        if generated_title and generated_title != 'Unknown':
            title = generated_title
        
        featured_image = image_urls[0] if image_urls else None
        meta_description = result.get('meta_description') or blog_plan.get('meta_description', '')
        
        result.update({
            'task_status': 'success',
            'task_id': task_id,
            'title': title,
            'meta_description': meta_description,
            'category': category_info,
            'image_urls': image_urls,
            'featured_image': featured_image,
            'blog_plan': blog_plan,
            'focus_keyword': keyword,
            'scraped_data_used': bool(scraped_data),
            'scraped_data': scraped_data,
            'video_link': data.get('video_link')
        })
        return result
        
    except Exception as e:
        logger.error(f"Error in content generation: {str(e)}", exc_info=True)
        return {'status': 'error', 'message': str(e)}

@shared_task(bind=True, name='autopublish.content_generator.tasks.rephrase_content_task')
def rephrase_content_task(self, data):
    """Task to rephrase content."""
    task_id = self.request.id if hasattr(self, 'request') else 'unknown'
    try:
        from .views import rephrase_news_content
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(rephrase_news_content(data))
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"Error in rephrase task: {str(e)}", exc_info=True)
        return {'status': 'error', 'error': str(e)}
