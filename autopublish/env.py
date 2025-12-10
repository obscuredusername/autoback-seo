# autopublish/env.py
import os
from typing import Any
from dotenv import load_dotenv

class Env:
    _loaded = False

    @classmethod
    def _load(cls) -> None:
        """Private method to load environment variables from .env files"""
        if cls._loaded:
            return
            
        env = os.environ.get('DJANGO_ENV', 'local')
        
        # Try to load specific environment file if it exists
        specific_env = f'.env.{env}'
        if os.path.isfile(specific_env):
            load_dotenv(specific_env)
        # Fall back to .env if specific file doesn't exist
        elif os.path.isfile('.env'):
            load_dotenv('.env')
            
        cls._loaded = True

    @classmethod
    def get(cls, key: str, default: Any = '') -> Any:
        """
        Get an environment variable with automatic type detection.
        Automatically loads .env file on first call.
        """
        cls._load()  # Ensure environment is loaded on first call
        
        value = os.environ.get(key)
        if value is None:
            return default
            
        # Convert to appropriate type
        lower_val = value.lower()
        
        # Handle boolean values
        if lower_val in ('true', 'false', 'yes', 'no', '1', '0', 't', 'f', 'y', 'n'):
            return lower_val in ('true', 'yes', '1', 't', 'y')
            
        # Try to convert to int
        try:
            return int(value)
        except ValueError:
            # Try to convert to float
            try:
                return float(value)
            except ValueError:
                # Return as string
                return value