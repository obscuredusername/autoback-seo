import json
from datetime import datetime, timedelta
from django.test import TestCase
from django.utils import timezone
from bson import ObjectId
from keyword_content.models import BlogPostPayload, Category

class BlogPostSerializationTest(TestCase):
    def setUp(self):
        # Create test category
        self.category = Category.objects.create(
            _id=ObjectId('68598639e46eb0ed3674d3f6'),
            name='Test Category',
            slug='test-category'
        )
        
        # Test data with various formats of categoryIds
        self.test_data = [
            # Case 1: Proper list of ObjectIds
            {
                'title': 'Test Post 1',
                'content': 'Test content 1',
                'categoryIds': [str(self.category._id)],
                'authorId': '683b3771a6b031d7d73735d7',
                'status': 'scheduled'
            },
            # Case 2: String representation of list
            {
                'title': 'Test Post 2',
                'content': 'Test content 2',
                'categoryIds': f'["{self.category._id}"]',
                'authorId': '683b3771a6b031d7d73735d7',
                'status': 'scheduled'
            },
            # Case 3: Single string value
            {
                'title': 'Test Post 3',
                'content': 'Test content 3',
                'categoryIds': str(self.category._id),
                'authorId': '683b3771a6b031d7d73735d7',
                'status': 'scheduled'
            },
            # Case 4: Empty value
            {
                'title': 'Test Post 4',
                'content': 'Test content 4',
                'categoryIds': None,
                'authorId': '683b3771a6b031d7d73735d7',
                'status': 'scheduled'
            }
        ]

    def test_blogpost_serialization(self):
        """Test that BlogPostPayload correctly handles categoryIds serialization"""
        for i, data in enumerate(self.test_data, 1):
            with self.subTest(test_case=f'Test case {i}'):
                # Create and save the blog post
                blog_post = BlogPostPayload(**data)
                blog_post.save()
                
                # Refresh from database
                saved_post = BlogPostPayload.objects.get(_id=blog_post._id)
                
                # Check that categoryIds is a list
                self.assertIsInstance(saved_post.categoryIds, list, 
                                   f'Test case {i}: categoryIds should be a list')
                
                # If we had categoryIds in the input, check they were properly saved
                if data['categoryIds']:
                    # Check that all items in categoryIds are strings
                    for cat_id in saved_post.categoryIds:
                        self.assertIsInstance(cat_id, str,
                                          f'Test case {i}: categoryIds items should be strings')
                    
                    # Check that the category ID was preserved
                    if isinstance(data['categoryIds'], str):
                        try:
                            # If it was a string representation of a list, parse it
                            expected_ids = json.loads(data['categoryIds'])
                            if not isinstance(expected_ids, list):
                                expected_ids = [expected_ids]
                        except json.JSONDecodeError:
                            expected_ids = [data['categoryIds']]
                    else:
                        expected_ids = data['categoryIds'] if isinstance(data['categoryIds'], list) else [data['categoryIds']]
                    
                    # Clean expected IDs (remove any quotes or brackets)
                    cleaned_expected = []
                    for cat_id in expected_ids:
                        if cat_id:
                            cleaned = str(cat_id).strip('"\'[] ')
                            if cleaned:
                                cleaned_expected.append(cleaned)
                    
                    # Check that we have the expected category IDs
                    self.assertEqual(len(saved_post.categoryIds), len(cleaned_expected),
                                 f'Test case {i}: Mismatch in number of category IDs')
                    
                    for expected_id in cleaned_expected:
                        self.assertIn(expected_id, saved_post.categoryIds,
                                   f'Test case {i}: Expected category ID {expected_id} not found')
                
                # Test the to_dict() method
                post_dict = saved_post.to_dict()
                
                # Check that to_dict() returns a list of strings for categoryIds
                self.assertIsInstance(post_dict['categoryIds'], list,
                                   f'Test case {i}: to_dict() should return a list for categoryIds')
                
                if post_dict['categoryIds']:  # Only check if we have category IDs
                    for cat_id in post_dict['categoryIds']:
                        self.assertIsInstance(cat_id, str,
                                          f'Test case {i}: to_dict() should return strings in categoryIds')
                
                # Check that the data can be JSON serialized
                try:
                    json.dumps(post_dict)
                except TypeError as e:
                    self.fail(f'Test case {i}: to_dict() result is not JSON serializable: {e}')
                
                print(f"Test case {i} passed - categoryIds: {post_dict['categoryIds']}")

    def test_blogpost_with_categories(self):
        """Test that categories ManyToManyField works with categoryIds"""
        # Create a blog post with categories
        blog_post = BlogPostPayload.objects.create(
            title='Test Post with Categories',
            content='Test content with categories',
            categoryIds=[str(self.category._id)],
            authorId='683b3771a6b031d7d73735d7',
            status='scheduled'
        )
        
        # Add the category to the ManyToManyField
        blog_post.categories.add(self.category)
        blog_post.save()
        
        # Refresh from database
        saved_post = BlogPostPayload.objects.get(_id=blog_post._id)
        
        # Check that categoryIds and categories are in sync
        self.assertEqual(len(saved_post.categoryIds), 1)
        self.assertEqual(len(saved_post.categories.all()), 1)
        self.assertEqual(str(saved_post.categories.first()._id), saved_post.categoryIds[0])
        
        print("Test with categories passed")

    def tearDown(self):
        # Clean up test data
        BlogPostPayload.objects.all().delete()
        Category.objects.all().delete()

if __name__ == '__main__':
    import django
    django.setup()
    from django.core.management import call_command
    call_command('test', 'tests.test_blogpost_serialization', verbosity=2)
