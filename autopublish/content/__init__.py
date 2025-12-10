# This file makes Python treat the directory as a package

# Import tasks in a way that's safe during Django's initialization
from django.apps import apps

def autodiscover():
    """Auto-discover tasks in the tasks.py file."""
    try:
        # This import needs to be inside the function to avoid circular imports
        from . import tasks  # noqa
        from .tasks import process_scheduled_posts  # noqa
        return process_scheduled_posts
    except Exception as e:
        # Log the error but don't fail
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"Could not autodiscover tasks: {e}")
        return None

# Don't call autodiscover here - let Celery do it when it's ready
__all__ = ['autodiscover']
