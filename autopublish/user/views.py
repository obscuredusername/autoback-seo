from django.shortcuts import render
from django.http import JsonResponse
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from .decorators import admin_required
import json
from .models import User, Profile
from django.utils import timezone

@method_decorator(csrf_exempt, name='dispatch')
class UserCreateView(View):
    def post (self, request):
        try:
            data = json.loads(request.body.decode('utf-8'))
            email = data.get('email')
            password = data.get('password')
            admin = False
            collection = ''

            if User.objects.filter(email = email).exists():
                return JsonResponse({'error': 'Email already exists'})
            
            user = User(email = email, admin = admin, collection = collection)
            user.set_password(password)
            user.save()

            return JsonResponse({'message': 'User created successfully'})
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid json'}, status = 400)
        
@method_decorator(csrf_exempt, name='dispatch')
class UserLoginView(View):
    def post(self, request):
        try:
            data = json.loads(request.body.decode('utf-8'))
            email = data.get('email')
            password = data.get('password')
            
            # Authenticate user
            user = authenticate(request, username=email, password=password)
            
            if user is not None:
                # Create user session
                login(request, user)
                return JsonResponse({
                    'message': 'Login successful',
                    'user_id': str(user.id),  # Convert ObjectId to string for JSON serialization
                    'email': user.email,
                    'admin': user.admin,
                    'collection': user.collection,
                    'sessionid': request.session.session_key
                })
            else:
                return JsonResponse({'error': 'Invalid email or password'}, status=400)

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)


@method_decorator(csrf_exempt, name='dispatch')
class UserLogoutView(View):
    def post(self, request):
        # Logout the user and clear the session
        logout(request)
        return JsonResponse({'message': 'Successfully logged out'})


@method_decorator(login_required, name='dispatch')
class SessionCheckView(View):
    def get(self, request):
        """Check if user is authenticated via session"""
        return JsonResponse({
            'authenticated': True,
            'user': {
                'id': str(request.user.id),  # Convert ObjectId to string for JSON serialization
                'email': request.user.email,
                'admin': request.user.admin,
                'collection': request.user.collection
            }
        })

@method_decorator(admin_required, name='dispatch')
class UserList(View):
    def get(self, request):
        show = request.GET.get('show', 'users')
        if show == 'collections':
            return JsonResponse({'collections': []}, status=200)
        else:
            # Fetch all users with their collection details
            users = User.objects.all()
            users_list = []
            for user in users:
                user_dict = {
                    'id': str(user.id),
                    'email': user.email,
                    'admin': user.admin,
                    'collection': user.collection,
                    'is_active': user.is_active,
                    'date_joined': user.date_joined.isoformat() if user.date_joined else None
                }
                users_list.append(user_dict)
            return JsonResponse({'users': users_list}, status=200)

    def post(self, request):
        show = request.GET.get('show', 'user')  # default to 'user'
        try:
            data = json.loads(request.body.decode('utf-8'))
            user_email = data.get('user_email')

            if not user_email:
                return JsonResponse({'error': 'Email not provided'}, status=400)

            try:
                user = User.objects.get(email=user_email)
            except User.DoesNotExist:
                return JsonResponse({'error': 'User not found'}, status=404)

            if show == 'user':
                admin = data.get('admin')
                if admin is None:
                    return JsonResponse({'error': 'Admin status not provided'}, status=400)
                user.admin = admin
                user.save(update_fields=['admin'])
                return JsonResponse({'message': f'User {user_email} admin status updated'}, status=200)

            elif show == 'collections':
                new_collection = data.get('collection')
                if new_collection is None:
                    return JsonResponse({'error': 'Collection not provided'}, status=400)
                user.collection = new_collection
                user.save()
                return JsonResponse({'message': f'User {user_email} collection updated'}, status=200)

            else:
                return JsonResponse({'error': 'Invalid show parameter'}, status=400)

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)


    def delete(self, request):
        try:
            data = json.loads(request.body.decode('utf-8'))
            user_email = data.get('user_email')

            if user_email is None:
                return JsonResponse({'error': 'Email not provided'}, status=400)

            try:
                user = User.objects.get(email=user_email)
                user.delete()
                return JsonResponse({'message': f'User {user_email} deleted successfully'}, status=200)
            except User.DoesNotExist:
                return JsonResponse({'error': 'User not found'}, status=404)

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

    def put(self, request):
        try:
            data = json.loads(request.body.decode('utf-8'))
            user_email = data.get('user_email')
            new_collection = data.get('collection')

            if not user_email or new_collection is None:
                return JsonResponse({'error': 'Email or collection not provided'}, status=400)

            try:
                user = User.objects.get(email=user_email)
                user.collection = new_collection
                user.save()
                return JsonResponse({'message': f'User {user_email} collection updated successfully'}, status=200)
            except User.DoesNotExist:
                return JsonResponse({'error': 'User not found'}, status=404)

        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

@method_decorator(csrf_exempt, name='dispatch')
class ProfileList(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
        
        profiles = Profile.objects.filter(user=request.user)
        profiles_data = []
        for profile in profiles:
            profiles_data.append({
                'id': profile.id,
                'name': profile.name,
                'language': profile.language,
                'region': profile.region,
                'domain_link': profile.domain_link,
                'created_at': profile.created_at.isoformat(),
                'updated_at': profile.updated_at.isoformat()
            })
        return JsonResponse({'profiles': profiles_data}, status=200)

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
            
        try:
            data = json.loads(request.body.decode('utf-8'))
            name = data.get('name')
            language = data.get('language', 'en')
            region = data.get('region', 'us')
            domain_link = data.get('domain_link')
            
            if not name:
                return JsonResponse({'error': 'Name is required'}, status=400)
                
            profile = Profile.objects.create(
                user=request.user,
                name=name,
                language=language,
                region=region,
                domain_link=domain_link
            )
            
            return JsonResponse({
                'message': 'Profile created successfully',
                'profile': {
                    'id': profile.id,
                    'name': profile.name,
                    'language': profile.language,
                    'region': profile.region,
                    'domain_link': profile.domain_link
                }
            }, status=201)
            
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

@method_decorator(csrf_exempt, name='dispatch')
class ProfileDetail(View):
    def get(self, request, profile_id):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
            
        try:
            profile = Profile.objects.get(id=profile_id, user=request.user)
            return JsonResponse({
                'profile': {
                    'id': profile.id,
                    'name': profile.name,
                    'language': profile.language,
                    'region': profile.region,
                    'domain_link': profile.domain_link,
                    'created_at': profile.created_at.isoformat(),
                    'updated_at': profile.updated_at.isoformat()
                }
            }, status=200)
        except Profile.DoesNotExist:
            return JsonResponse({'error': 'Profile not found'}, status=404)

    def put(self, request, profile_id):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
            
        try:
            profile = Profile.objects.get(id=profile_id, user=request.user)
            data = json.loads(request.body.decode('utf-8'))
            
            profile.name = data.get('name', profile.name)
            profile.language = data.get('language', profile.language)
            profile.region = data.get('region', profile.region)
            profile.domain_link = data.get('domain_link', profile.domain_link)
            profile.save()
            
            return JsonResponse({
                'message': 'Profile updated successfully',
                'profile': {
                    'id': profile.id,
                    'name': profile.name,
                    'language': profile.language,
                    'region': profile.region,
                    'domain_link': profile.domain_link
                }
            }, status=200)
            
        except Profile.DoesNotExist:
            return JsonResponse({'error': 'Profile not found'}, status=404)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

    def delete(self, request, profile_id):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentication required'}, status=401)
            
        try:
            profile = Profile.objects.get(id=profile_id, user=request.user)
            profile.delete()
            return JsonResponse({'message': 'Profile deleted successfully'}, status=200)
        except Profile.DoesNotExist:
            return JsonResponse({'error': 'Profile not found'}, status=404)
