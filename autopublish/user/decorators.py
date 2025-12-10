from django.http import JsonResponse
from functools import wraps

def admin_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        if not getattr(user, 'admin', False):
            return JsonResponse({'error': 'Admin privileges required'}, status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped_view
