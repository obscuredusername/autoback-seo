import json
from bson import ObjectId
from django.core.exceptions import ValidationError
from djongo import models as djongo_models

class ListField(djongo_models.JSONField):
    """
    Custom field that ensures values are always stored as lists in MongoDB.
    Handles both ObjectId and regular values properly.
    """
    def __init__(self, *args, object_id=False, **kwargs):
        self.object_id = object_id
        kwargs.setdefault('default', list)
        super().__init__(*args, **kwargs)
    
    def get_prep_value(self, value):
        """Convert Python object to a database value."""
        if value is None:
            return []
        
        # Convert string to list if needed
        if isinstance(value, str):
            value = value.strip()
            if value.startswith('[') and value.endswith(']'):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    value = [value]
            else:
                value = [value]
        
        # Ensure we have an iterable
        if not isinstance(value, (list, tuple)):
            value = [value]
        
        # Process ObjectId conversion if needed
        if self.object_id:
            result = []
            for item in value:
                if item is None:
                    continue
                try:
                    # Convert to ObjectId if it's not already one
                    if not isinstance(item, ObjectId):
                        item = str(item).strip('"\'[] ')
                        if item:  # Only process non-empty strings
                            result.append(ObjectId(item))
                except Exception as e:
                    raise ValidationError(f"Invalid ObjectId: {item}")
            return result
        
        # For non-ObjectId lists, ensure all items are JSON serializable
        try:
            json.dumps(value)
            return value
        except (TypeError, ValueError):
            return [str(item) for item in value]
    
    def from_db_value(self, value, *args):
        """Convert database value to Python object."""
        return self.to_python(value)
    
    def to_python(self, value):
        """Convert value to Python object."""
        if value is None:
            return []
        
        # Handle string input
        if isinstance(value, str):
            value = value.strip()
            if value.startswith('[') and value.endswith(']'):
                try:
                    value = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    value = [value]
            else:
                value = [value]
        
        # Ensure we have an iterable
        if not isinstance(value, (list, tuple)):
            value = [value]
        
        # Convert ObjectId to string if needed
        if self.object_id:
            result = []
            for item in value:
                if item is None:
                    continue
                try:
                    # Convert ObjectId to string for Python use
                    if isinstance(item, ObjectId):
                        result.append(str(item))
                    else:
                        # If it's a string that looks like an ObjectId, keep it as is
                        item_str = str(item).strip('"\'[] ')
                        if len(item_str) == 24:  # Standard ObjectId length
                            result.append(item_str)
                except Exception:
                    continue
            return result
        
        return list(value)
