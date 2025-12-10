from bson import ObjectId
import logging
import json
from asgiref.sync import async_to_sync
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import UserCollection
from .tasks import process_keyword_task

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
            else:
                user_collection = UserCollection.objects.filter(user=user).first()
                if user_collection:
                    collection = user_collection.name

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

            # Get categories synchronously
            available_categories = async_to_sync(self.get_categories_from_api)()
            
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
