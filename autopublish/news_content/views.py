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
from django.apps import apps

from scraper.views import NewsByCategoryView
from content_generator.views import rephrase_news_content
from .tasks import process_news_task
from celery.result import AsyncResult
from django.http import JsonResponse
from bson import ObjectId
from django.contrib.sessions.models import Session
from django.contrib.auth import get_user_model




class NewsSchedulerView(APIView):
    """
    API endpoint for scheduling news processing tasks asynchronously using Celery.
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
        