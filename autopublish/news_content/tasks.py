import os
import sys
import traceback
from celery import Celery
from celery.utils.log import get_task_logger

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'autopublish.settings')

# Get the Celery app from the Django project
from autopublish.celery import app

# Set up logging
logger = get_task_logger(__name__)

# Import the task implementation
from news_content.task_utils import process_news_task_impl

# Register the task with a fixed name to ensure it's always found
@app.task(bind=True, name="process_news_task")
def process_news_task(self, request_body):
    """
    Celery task to process news asynchronously.
    This is a thin wrapper around process_news_task_impl to maintain compatibility.
    """
    try:
        logger.info(f"[TASK] Starting process_news_task with data: {request_body}")
        result = process_news_task_impl(request_body)
        logger.info(f"[TASK] News task completed with result: {result}")
        return result
        
    except Exception as e:
        # Check if this is a retry exception
        if hasattr(self, 'retry') and isinstance(e, self.retry.__class__):
            # Re-raise retry exceptions
            raise
        
        # Handle other exceptions
        error_msg = f"Error in process_news_task: {str(e)}\n{traceback.format_exc()}"
        logger.error(f"[TASK] {error_msg}")
        return {"success": False, "error": "An error occurred while processing the news task"}