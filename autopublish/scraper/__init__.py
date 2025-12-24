# Import tasks to ensure they are registered with Celery
from . import tasks  # noqa

# Make the tasks available at the package level
from .tasks import process_and_save_images, process_scraping_task, scrape_news_task  # noqa

__all__ = ['process_and_save_images', 'process_scraping_task', 'scrape_news_task']
