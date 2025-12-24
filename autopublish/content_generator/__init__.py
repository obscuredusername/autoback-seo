# Import tasks to make them discoverable by Celery
from .tasks import get_blog_plan, generate_keyword_content, rephrase_content_task

# Make tasks available at package level
__all__ = ['get_blog_plan', 'generate_keyword_content', 'rephrase_content_task']
