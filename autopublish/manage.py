#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from django.core.management.commands.runserver import Command as runserver

def main():
    """Run administrative tasks."""
    # Load environment variables from .env file
    # Load environment variables from .env file
    env_path = Path(__file__).resolve().parent.parent / '.env'
    load_dotenv(dotenv_path=env_path)
    
    # Add the project root to Python path (one level up from manage.py)
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    
    # Set the default Django settings module
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'autopublish.settings')
    
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    # Set the default port from DJANGO_PORT environment variable or use 8000
    default_port = os.environ.get('DJANGO_PORT', '8000')
    
    # If running the runserver command, set the default port
    if len(sys.argv) > 1 and sys.argv[1] == 'runserver':
        # Check if port is already specified in the command
        if ':' not in sys.argv[-1] and not any(arg.startswith('--port') for arg in sys.argv):
            sys.argv.append(f'0.0.0.0:{default_port}' if os.environ.get('USE_0_0_0_0') else f'127.0.0.1:{default_port}')
    
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()