from django.shortcuts import render
from django.http import JsonResponse, HttpRequest, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django.contrib.sessions.models import Session
from django.utils.text import slugify
from django.contrib.auth import get_user_model
from content_generator.views import generate_blog_from_keyword
from scraper.views import KeywordSearchView
from bson import ObjectId
import logging
import json
import re
import asyncio
import datetime
from datetime import timezone, timedelta
from asgiref.sync import sync_to_async
from django.conf import settings
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.contrib.sessions.models import Session
from django.contrib.auth import get_user_model
from django.db import connection
from .models import BlogPostPayload, Category, UserCollection
from .tasks import process_keyword_task
import http.cookies

logger = logging.getLogger(__name__)

class BlogPost(APIView):
    authentication_classes = []
    permission_classes = []
    
    def _get_default_category(self) -> list:
        """Return a default category (A LA UNE) when no categories are found"""
        from bson import ObjectId
        default_category = {
            '_id': ObjectId('68598639e46eb0ed3674d3f6'),
            'name': 'A LA UNE',
            'slug': 'a-la-une',
            'description': 'Default category for articles'
        }
        print("⚠️ Using default category: A LA UNE")
        return [default_category]
        
    async def get_categories_from_api(self):
        """
        Get all categories from the external API.
        Returns a tuple of (category_names, categories_dict) where:
        - category_names: list of category names for backward compatibility
        - categories_dict: dict mapping category names to their term_id
        """
        import aiohttp
        import logging
        
        logger = logging.getLogger(__name__)
        api_url = 'https://extifixpro.com/wp-json/thirdparty/v1/categories'
        logger.info(f"🔍 Fetching categories from API: {api_url}")
        
        try:
            async with aiohttp.ClientSession() as session:
                logger.info("🔹 Creating new aiohttp session for category fetch")
                async with session.get(api_url) as response:
                    logger.info(f"🔹 API request status: {response.status}")
                    if response.status == 200:
                        categories = await response.json()
                        logger.info(f"✅ Successfully fetched {len(categories)} categories from API")
                        
                        # Create mapping of category names to their term_ids
                        categories_dict = {}
                        for cat in categories:
                            if isinstance(cat, dict) and 'name' in cat and 'term_id' in cat:
                                categories_dict[cat['name']] = str(cat['term_id'])
                        
                        # Log first few category names for debugging
                        category_names = list(categories_dict.keys())
                        if len(category_names) > 5:
                            logger.info(f"📋 Categories: {', '.join(category_names[:5])} ... and {len(category_names) - 5} more")
                        else:
                            logger.info(f"📋 Categories: {', '.join(category_names)}")
                        
                        return category_names, categories_dict
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Failed to fetch categories: HTTP {response.status} - {error_text}")
                        return [], {}
        except Exception as e:
            logger.error(f"❌ Error fetching categories from API: {str(e)}", exc_info=True)
            return [], {}

    def post(self, request, *args, **kwargs):
        # Wrap the async function and await it
        async def _post():
            try:
                # Get user and collection from request
                user, default_collection = await sync_to_async(self.get_user_from_request, thread_sensitive=True)(request)
                if not user:
                    return Response(
                        {"error": "User not authenticated"}, 
                        status=status.HTTP_401_UNAUTHORIZED
                    )
                
                # Log raw request body
                try:
                    request_body = request.body.decode('utf-8')
                    data = json.loads(request_body) if request_body else {}
                except json.JSONDecodeError as e:
                    print(f"❌ Error parsing request data: {str(e)}")
                    return Response({"error": f"Error parsing request: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
                
                # Extract keywords from the request data
                if 'keywords' not in data or not data['keywords']:
                    return Response({"error": "No keywords provided"}, status=status.HTTP_400_BAD_REQUEST)
                    
                # Handle both string and dictionary formats for keywords
                keywords = []
                for kw in data['keywords']:
                    if isinstance(kw, dict):
                        if 'text' in kw and kw['text']:
                            keywords.append(str(kw['text']))
                    elif kw:  # Handle case where keywords are just strings
                        keywords.append(str(kw))
                        
                if not keywords:
                    return Response({"error": "No valid keywords provided"}, status=status.HTTP_400_BAD_ERROR)

                # Validate required fields
                required_fields = ['language', 'country', 'min_words']
                for field in required_fields:
                    if field not in data:
                        return Response({"error": f"Missing required field: {field}"}, status=status.HTTP_400_BAD_REQUEST)

                available_categories = await self.get_categories_from_api()
                # Prepare request body for the task
                request_body = {
                    'keywords': [],
                    'language': data.get('language', 'en'),
                    'country': data.get('country', 'us'),
                    'min_words': data.get('min_words', 1000),
                    'tone': data.get('tone', 'professional'),
                    'word_count': data.get('word_count', data.get('min_words', 1000)),
                    'user_email': user.email,
                    'available_categories': available_categories,
                    'collection': data.get('collection', default_collection),
                }
                
                # Process keywords with their scheduled times
                for kw in data['keywords']:
                    if isinstance(kw, dict) and 'text' in kw and kw['text']:
                        keyword_data = {'text': str(kw['text'])}
                        if 'scheduled_time' in kw:
                            keyword_data['scheduled_time'] = kw['scheduled_time']
                        request_body['keywords'].append(keyword_data)
                    elif kw:  # Handle case where keywords are just strings
                        request_body['keywords'].append({'text': str(kw)})
                
                # Add scheduled_time if provided
                if 'scheduled_time' in data:
                    request_body['scheduled_time'] = data['scheduled_time']
                
                print(f"🔍 Processing {len(keywords)} keywords: {', '.join(keywords)}")
                if default_collection:
                    print(f"✅ Using collection: {default_collection}")
                if 'scheduled_time' in request_body:
                    print(f"✅ Using scheduled time: {request_body['scheduled_time']}")
                    
                # Process asynchronously
                task = process_keyword_task.delay(request_body)
                return Response({
                    "status": "processing",
                    "task_id": str(task.id),
                    "message": "Your request is being processed asynchronously"
                }, status=status.HTTP_202_ACCEPTED)
                    
            except Exception as e:
                print(f"❌ Unexpected error: {str(e)}")
                import traceback
                traceback.print_exc()
                return Response({
                    "success": False,
                    "error": f"Unexpected error: {str(e)}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Create and run the event loop
        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(_post())
        finally:
            loop.close()


    def get_user_from_request(self, request):
        """Extract user from request cookies or headers"""
        try:
            # Try to get session ID from cookies first
            sessionid = None
            if hasattr(request, 'COOKIES') and 'sessionid' in request.COOKIES:
                sessionid = request.COOKIES['sessionid']
            
            # If not in cookies, try to get from Authorization header
            if not sessionid and hasattr(request, 'META') and 'HTTP_AUTHORIZATION' in request.META:
                auth_header = request.META['HTTP_AUTHORIZATION']
                if auth_header.startswith('Bearer '):
                    sessionid = auth_header.split(' ')[1]
            
            if not sessionid:
                print("⚠️ No session ID found in request")
                return None, None
                
            # Get session
            try:
                session = Session.objects.get(session_key=sessionid)
                session_data = session.get_decoded()
                print(f"🔍 Session data: {session_data}")
            except Session.DoesNotExist:
                print(f"⚠️ Session not found for sessionid: {sessionid}")
                return None, None
            except Exception as e:
                print(f"⚠️ Error getting session: {str(e)}")
                return None, None
            
            # Get user ID from session
            user_id = session_data.get('_auth_user_id')
            if not user_id:
                print("⚠️ No user ID found in session data")
                return None, None
            
            # Get user - handle both string and ObjectId user IDs
            User = get_user_model()
            try:
                # First try to get user by string ID (Django's default)
                try:
                    user = User.objects.get(id=user_id)
                    print(f"✅ Found user by string ID: {user.email} (ID: {user.id})")
                except (User.DoesNotExist, ValueError):
                    # If that fails, try with ObjectId
                    from bson import ObjectId
                    try:
                        if not isinstance(user_id, ObjectId):
                            user_id = ObjectId(user_id)
                        user = User.objects.get(_id=user_id)
                        print(f"✅ Found user by ObjectId: {user.email} (ID: {user._id})")
                    except (User.DoesNotExist, Exception) as e:
                        print(f"⚠️ User not found with ID: {user_id} - {str(e)}")
                        return None, None
                
                # Get user's collection from their profile
                try:
                    # First try to get the collection name directly from user's collection field
                    if hasattr(user, 'collection') and user.collection:
                        print(f"✅ Using user's collection: {user.collection}")
                        return user, user.collection
                    
                    # If no collection field or it's empty, try to get from UserCollection model
                    try:
                        collection = UserCollection.objects.filter(user=user).first()
                        if collection:
                            print(f"✅ Found user collection in UserCollection model: {collection.name}")
                            return user, collection.name
                    except Exception as e:
                        print(f"⚠️ Error getting user collection from UserCollection model: {str(e)}")
                    
                    # Fallback to default collection name
                    print("ℹ️ No collection found, using 'default'")
                    return user, 'default'
                    
                except Exception as e:
                    print(f"⚠️ Error getting user collection: {str(e)}")
                    return user, 'default'  # Fallback to default collection name
                
            except User.DoesNotExist:
                print(f"⚠️ User with _id {user_id} not found")
                return None, None
                
        except Exception as e:
            print(f"⚠️ Unexpected error in get_user_from_request: {str(e)}")
            import traceback
            traceback.print_exc()
            return None, None