from django.apps import AppConfig

class KeywordContentConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'keyword_content'
    verbose_name = 'Keyword Content'
    
    def ready(self):
        # Import signals
        from . import signals  # noqa
        
        # Setup Celery beat schedule
        try:
            from autopublish.autopublish.celery import app as celery_app
            
            celery_app.conf.beat_schedule = {
                'publish-scheduled-posts': {
                    'task': 'keyword_content.tasks.publish_scheduled_posts',
                    'schedule': 60.0,  # Run every minute
                },
            }
        except ImportError:
            # Celery might not be available during tests or management commands
            pass
