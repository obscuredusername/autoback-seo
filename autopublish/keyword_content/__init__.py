# This will make sure the app is always imported when Django starts
from __future__ import absolute_import, unicode_literals

# This will make these tasks available at the package level
__all__ = [
    'process_keyword_task',
    'fetch_keyword_content_prereqs',
    'publish_scheduled_posts',
    'process_blog_plan_and_scraped_data',
    'prepare_content'
]

def __getattr__(name):
    if name in __all__:
        from .tasks import (
            process_keyword_task,
            fetch_keyword_content_prereqs,
            publish_scheduled_posts,
            process_blog_plan_and_scraped_data,
            prepare_content
        )
        return locals()[name]
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

default_app_config = 'keyword_content.apps.KeywordContentConfig'