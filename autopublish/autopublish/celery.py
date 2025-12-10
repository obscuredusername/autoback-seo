# autopublish/autopublish/celery.py
import os
from celery import Celery
from dotenv import load_dotenv

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'autopublish.settings')

# Load environment variables
load_dotenv()

# Initialize Celery before importing Django
app = Celery('autopublish')

# Load configuration from Django settings
app.config_from_object('django.conf:settings', namespace='CELERY')

# Initialize Django after Celery is configured
import django
django.setup()

# Now it's safe to import Django models and settings
from django.conf import settings

# PostgreSQL connection
postgres_user = os.getenv('POSTGRES_USER', 'postgres')
postgres_password = os.getenv('POSTGRES_PASSWORD', 'postgres')
postgres_host = os.getenv('POSTGRES_HOST', 'localhost')
postgres_port = os.getenv('POSTGRES_PORT', '5432')
postgres_db = os.getenv('POSTGRES_DB', 'autopublish')

# Format PostgreSQL URIs for Celery
postgres_uri = f'postgresql://{postgres_user}:{postgres_password}@{postgres_host}:{postgres_port}/{postgres_db}'
broker_uri = settings.CELERY_BROKER_URL if hasattr(settings, 'CELERY_BROKER_URL') else f'sqla+{postgres_uri}'

# Configure Celery
app.conf.update(
    broker_url=broker_uri,
    result_backend=f'db+{postgres_uri}',
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    task_track_started=True,
    task_time_limit=3600,  # 60 minutes
    task_soft_time_limit=3300,  # 55 minutes
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        'process-scheduled-posts': {
            'task': 'process_scheduled_posts',
            'schedule': 60.0,  # Run every minute
            'options': {
                'expires': 30.0,  # Expire after 30 seconds to prevent overlap
            },
        },
    },
    beat_schedule_filename='celerybeat-schedule',
)

# Configure task discovery after Django is fully loaded
app.autodiscover_tasks(
    packages=['keyword_content', 'content_generator', 'content'],
)

# Import tasks after Celery is set up
try:
    # These imports will happen after Django is fully loaded
    from keyword_content import tasks as keyword_tasks  # noqa
    from content_generator import tasks as content_tasks  # noqa
    
    # Import content tasks last since they depend on Django models
    from content import autodiscover as content_autodiscover
    content_autodiscover()
except Exception as e:
    # Log the error but don't fail - this allows the app to start
    # even if there are issues with task registration
    import logging
    logger = logging.getLogger(__name__)
    logger.warning(f"Could not import all tasks: {e}")

# Simple task for testing
@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
    return f'Request: {self.request!r}'

# This will make sure our tasks are registered
app.finalize()