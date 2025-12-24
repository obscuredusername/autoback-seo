import datetime
import asyncio
import json
import logging
import traceback
from pathlib import Path
from asgiref.sync import sync_to_async, async_to_sync
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.request import Request
from rest_framework.parsers import JSONParser
from rest_framework.authentication import SessionAuthentication, BasicAuthentication
from django.apps import apps
from django.http import JsonResponse
from django.contrib.sessions.models import Session
from django.contrib.auth import get_user_model
from celery.result import AsyncResult
from bson import ObjectId

from .tasks import process_keyword_task, process_news_task

logger = logging.getLogger(__name__)


class KeywordBlogPostView(APIView):
    """
    API endpoint for generating blog posts from keywords.
    Handles keyword-based content generation with scheduling support.
    """
    authentication_classes = [SessionAuthentication, BasicAuthentication]
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
        
    async def get_categories_from_api(self, domain_link='https://extifixpro.com'):
        """
        Get all categories from the external API.
        Returns a tuple of (category_names, categories_dict) where:
        - category_names: list of category names for backward compatibility
        - categories_dict: dict mapping category names to their term_id
        """
        import aiohttp
        import logging
        
        logger = logging.getLogger(__name__)
        api_url = f'{domain_link}/wp-json/thirdparty/v1/categories'
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
        try:
            # Authentication check
            if not request.user.is_authenticated:
                return Response(
                    {"error": "User not authenticated"}, 
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            user = request.user
            
            # Get collection
            collection = 'default'
            if hasattr(user, 'collection') and user.collection:
                collection = user.collection


            # Parse request body
            try:
                data = request.data
                if not data and request.body:
                     data = json.loads(request.body.decode('utf-8'))
            except Exception as e:
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
                return Response({"error": "No valid keywords provided"}, status=status.HTTP_400_BAD_REQUEST)

            # Validate required fields
            required_fields = ['language', 'country', 'min_words']
            for field in required_fields:
                if field not in data:
                    return Response({"error": f"Missing required field: {field}"}, status=status.HTTP_400_BAD_REQUEST)

            # Get domain_link from request, default to hardcoded if not present
            domain_link = data.get('domain_link', 'https://extifixpro.com')
            
            mins_words = data.get('min_words', 2000)

            # Get categories synchronously
            available_categories = async_to_sync(self.get_categories_from_api)(domain_link)
            
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
                'collection': data.get('collection', collection),
                'domain_link': domain_link
            }
            print(f"✅ Categories in posts function: {request_body['available_categories']}")
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
            
            logger.info(f"🔍 Processing {len(keywords)} keywords: {', '.join(keywords)}")
            if collection:
                logger.info(f"✅ Using collection: {collection}")
            if 'scheduled_time' in request_body:
                logger.info(f"✅ Using scheduled time: {request_body['scheduled_time']}")
                
            # Process asynchronously
            task = process_keyword_task.delay(request_body)
            return Response({
                "status": "processing",
                "task_id": str(task.id),
                "message": "Your request is being processed asynchronously"
            }, status=status.HTTP_202_ACCEPTED)
                
        except Exception as e:
            logger.error(f"❌ Unexpected error: {str(e)}", exc_info=True)
            return Response({
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class NewsSchedulerView(APIView):
    """
    API endpoint for scheduling news processing tasks asynchronously using Celery.
    Handles news-based content generation with scheduling support.
    """
    logger = logging.getLogger(__name__)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Initialize logger in __init__ as well for compatibility
        if not hasattr(self, 'logger'):
            self.logger = logging.getLogger(__name__)
        
    def post(self, request, *args, **kwargs):
        """
        Handle POST request to schedule news processing.
        Queues the task and returns immediately with a task ID.
        """
        try:
            print(f"Request data: {request.data}")
            self.logger.info("=== NewsSchedulerView POST request received ===")
            self.logger.info(f"Request data: {request.data}")
            
            data = request.data
            categories = data.get('categories', {})
            language = data.get('language', 'en')
            print(categories)
            if not categories:
                error_msg = 'No categories provided in request'
                self.logger.error(error_msg)
                return Response(
                    {'error': error_msg}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            self.logger.info(f"Processing request with categories: {categories}")
            print(categories)
            
            session_id = request.COOKIES.get('sessionid')
            self.logger.info(f"Looking for session ID in cookies: {session_id}")
            
            if not session_id:
                error_msg = 'No session ID found in cookies'
                self.logger.error(error_msg)
                return Response(
                    {'error': error_msg},
                    status=status.HTTP_401_UNAUTHORIZED
                )
            
            try:                
                self.logger.info(f"Looking up session with ID: {session_id}")
                
                try:
                    session = Session.objects.get(session_key=session_id)
                    session_data = session.get_decoded()
                    self.logger.info(f"Session data: {session_data}")
                    
                    user_id = session_data.get('_auth_user_id',None)
                    if not user_id:
                        error_msg = 'No user ID found in session data'
                        self.logger.error(error_msg)
                        return Response(
                            {'error': error_msg},
                            status=status.HTTP_401_UNAUTHORIZED
                        )
                    
                    self.logger.info(f"Found user ID in session: {user_id}")
                    
                    User = get_user_model()
                    try:
                        # Handle user_id conversion
                        is_object_id = False
                        if isinstance(user_id, str):
                            try:
                                user_id_obj = ObjectId(user_id)
                                is_object_id = True
                                user_id = user_id_obj
                            except Exception:
                                # Not a valid ObjectId, keep as string/int
                                pass
                        
                        # Try to get user
                        try:
                            if is_object_id:
                                user = User.objects.get(_id=user_id)
                            else:
                                # Try standard Django pk lookup for non-ObjectId
                                user = User.objects.get(pk=user_id)
                        except (User.DoesNotExist, Exception):
                            # Fallback: try querying by id or _id with original value
                            try:
                                user = User.objects.get(id=user_id)
                            except (User.DoesNotExist, Exception):
                                try:
                                    user = User.objects.get(_id=user_id)
                                except (User.DoesNotExist, Exception):
                                    raise User.DoesNotExist(f"User {user_id} not found")
                        self.logger.info(f"Found user: {user.email if hasattr(user, 'email') else 'No email'}")
                        
                        # Get collection from user model or default
                        if hasattr(user, 'collection') and user.collection:
                            target_path = user.collection
                            self.logger.info(f"Using collection from user model: {target_path}")
                        else:
                            # Try to get from user profile or related model
                            try:
                                if hasattr(user, 'profile') and hasattr(user.profile, 'collection'):
                                    target_path = user.profile.collection
                                    self.logger.info(f"Using collection from user profile: {target_path}")
                                else:
                                    target_path = 'CRM.posts'
                                    self.logger.warning(f"No collection found for user, using default: {target_path}")
                            except Exception as profile_error:
                                target_path = 'CRM.posts'
                                self.logger.warning(f"Error getting user profile, using default collection: {str(profile_error)}")
                        
                        data['target_path'] = target_path
                        self.logger.info(f"Final target_path set to: {target_path}")

                        # Get domain_link from user profile if not in request or empty
                        if not data.get('domain_link'):
                            if hasattr(user, 'domain_link') and user.domain_link:
                                data['domain_link'] = user.domain_link
                                self.logger.info(f"Using domain_link from user model: {data['domain_link']}")
                            elif hasattr(user, 'profile') and hasattr(user.profile, 'domain_link'):
                                data['domain_link'] = user.profile.domain_link
                                self.logger.info(f"Using domain_link from user profile: {data['domain_link']}")
                        
                    except User.DoesNotExist:
                        error_msg = f'User with ID {user_id} not found'
                        self.logger.error(error_msg)
                        return Response(
                            {'error': error_msg},
                            status=status.HTTP_404_NOT_FOUND
                        )
                    
                except Session.DoesNotExist:
                    error_msg = 'Invalid or expired session'
                    self.logger.error(error_msg)
                    return Response(
                        {'error': error_msg},
                        status=status.HTTP_401_UNAUTHORIZED
                    )
                
            except Exception as e:
                error_msg = f'Error processing session: {str(e)}'
                self.logger.error(error_msg, exc_info=True)
                return Response(
                    {'error': 'Internal server error while processing session'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                        
            except Exception as e:
                error_msg = f'Error fetching user collection: {str(e)}'
                self.logger.error(f"{error_msg}\n{traceback.format_exc()}")
                return Response(
                    {'error': error_msg},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
            
            # Get time_delay from request data with a default of 10 minutes
            time_delay = data.get('time_delay', 10)
            # Log the time_delay being set
            self.logger.info(f"Setting time_delay to {time_delay} minutes in request data")
            
            # Queue the task with the data as a dict to ensure proper serialization
            try:
                # Convert QueryDict to regular dict if needed
                if hasattr(data, 'dict'):
                    task_data = data.dict()
                else:
                    task_data = dict(data)
                
                task = process_news_task.delay(task_data)
                self.logger.info(f"Successfully queued task with ID: {task.id} with time delay: {time_delay} minutes")
                
                return Response({
                    'status': 'processing',
                    'task_id': str(task.id),
                    'message': 'News processing task has been queued.',
                    'target_path': data.get('target_path')
                }, status=status.HTTP_202_ACCEPTED)
                
            except Exception as e:
                error_msg = f'Failed to queue task: {str(e)}'
                self.logger.error(f"{error_msg}\n{traceback.format_exc()}")
                return Response(
                    {'error': error_msg},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )
                
        except Exception as e:
            return Response(
                {'error': f'Failed to queue task: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    def get(self, request, task_id=None, *args, **kwargs):
        """
        Check the status of a news processing task.
        """
        if not task_id:
            return Response(
                {'error': 'Task ID is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        task_result = AsyncResult(task_id)
        
        response_data = {
            'task_id': task_id,
            'status': task_result.status,
            'result': task_result.result if task_result.ready() else None
        }
        
        return Response(response_data, status=status.HTTP_200_OK)