import os
import django
from django.utils import timezone
from bson import ObjectId

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'autopublish.settings')
django.setup()

from keyword_content.models import BlogPostPayload, Category

def test_blog_post_creation():
    print("\n=== Testing BlogPostPayload Creation ===")
    
    # Create test categories first
    cat1 = Category.objects.create(
        name="Test Category 1",
        slug="test-category-1"
    )
    cat2 = Category.objects.create(
        name="Test Category 2",
        slug="test-category-2"
    )
    
    # Test data
    test_data = [
        {
            'title': 'Test Post with String IDs',
            'content': 'This is a test post with string IDs',
            'categoryIds': [str(cat1._id)],
            'tagIds': [str(cat2._id)],
            'authorId': '683b3771a6b031d7d73735d7',
            'status': 'scheduled'
        },
        {
            'title': 'Test Post with ObjectIds',
            'content': 'This is a test post with ObjectIds',
            'categoryIds': [cat1._id],
            'tagIds': [cat2._id],
            'authorId': ObjectId('683b3771a6b031d7d73735d7'),
            'status': 'scheduled'
        },
        {
            'title': 'Test Post with JSON String IDs',
            'content': 'This is a test post with JSON string IDs',
            'categoryIds': f'["{str(cat1._id)}", "{str(cat2._id)}"]',
            'tagIds': f'["{str(cat1._id)}"]',
            'authorId': '683b3771a6b031d7d73735d7',
            'status': 'scheduled'
        }
    ]
    
    # Create and test posts
    for i, data in enumerate(test_data, 1):
        print(f"\n--- Test Case {i} ---")
        print(f"Input data: {data}")
        
        # Create post
        post = BlogPostPayload.objects.create(**data)
        
        # Print results
        print(f"Created Post ID: {post._id}")
        print(f"Title: {post.title}")
        print(f"Status: {post.status}")
        print(f"Category IDs (type: {type(post.categoryIds[0]) if post.categoryIds else 'None'}): {post.categoryIds}")
        print(f"Tag IDs (type: {type(post.tagIds[0]) if post.tagIds else 'None'}): {post.tagIds}")
        print(f"Author ID (type: {type(post.authorId)}): {post.authorId}")
        
        # Clean up
        post.delete()
    
    # Clean up categories
    cat1.delete()
    cat2.delete()
    
    print("\n=== Test Completed Successfully ===")

if __name__ == "__main__":
    test_blog_post_creation()
