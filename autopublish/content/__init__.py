# This file is intentionally minimal to avoid AppRegistryNotReady errors.
# Celery will auto-discover tasks from tasks.py through the app config.
# Do not import tasks here at module level.

default_app_config = 'content.apps.ContentConfig'
