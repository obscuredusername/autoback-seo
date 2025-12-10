# This file makes the directory a Python package

"""
Custom middleware for the autopublish project.
"""

class DisableCSRFMiddleware:
    """
    Middleware to disable CSRF protection for development.
    WARNING: Only use this in development!
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Set attribute to bypass CSRF checks
        setattr(request, '_dont_enforce_csrf_checks', True)
        response = self.get_response(request)
        return response
