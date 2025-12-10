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
from .models import User, Collection
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
            # Fetch all collections with their full details
            collections = []
            for collection in Collection.objects.all():
                collections.append({
                    'id': str(collection.id),
                    'db_name': collection.db_name,
                    'collection_name': collection.collection_name,
                    'full_name': collection.full_name,
                    'description': collection.description,
                    'created_at': collection.created_at.isoformat(),
                    'updated_at': collection.updated_at.isoformat()
                })
            return JsonResponse({'collections': collections}, status=200)
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


@method_decorator([csrf_exempt, login_required, admin_required], name='dispatch')
class CollectionCreateView(View):
    def post(self, request):
        try:
            data = json.loads(request.body.decode('utf-8'))
            full_name = data.get('name')  # Expected format: 'db_name.collection_name'
            description = data.get('description', '')
            
            if not full_name:
                return JsonResponse(
                    {'error': 'Collection name is required in format "database.collection"'}, 
                    status=400
                )
                
            # Split into db_name and collection_name
            if '.' not in full_name:
                return JsonResponse(
                    {'error': 'Collection name must be in format "database.collection"'},
                    status=400
                )
                
            db_name, collection_name = full_name.split('.', 1)  # Split only on first dot
            
            if not db_name or not collection_name:
                return JsonResponse(
                    {'error': 'Both database name and collection name are required'},
                    status=400
                )
                
            # Check if collection with this full_name already exists
            if Collection.objects.filter(full_name=full_name).exists():
                return JsonResponse(
                    {'error': f'A collection with the name "{full_name}" already exists'},
                    status=400
                )
                
            # Create the new collection
            collection = Collection.objects.create(
                db_name=db_name,
                collection_name=collection_name,
                full_name=full_name,
                description=description
            )
            
            return JsonResponse({
                'message': 'Collection created successfully',
                'collection': {
                    'id': str(collection.id),
                    'db_name': collection.db_name,
                    'collection_name': collection.collection_name,
                    'full_name': collection.full_name,
                    'description': collection.description,
                    'created_at': collection.created_at.isoformat(),
                    'updated_at': collection.updated_at.isoformat()
                }
            }, status=201)
            
        except json.JSONDecodeError:
            return JsonResponse(
                {'error': 'Invalid JSON'}, 
                status=400
            )
        except Exception as e:
            return JsonResponse(
                {'error': str(e)}, 
                status=500
            )
