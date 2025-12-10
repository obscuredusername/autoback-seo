import os
import sys
import json
from bson import ObjectId

# Set up Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'autopublish.settings')
import django
django.setup()

from keyword_content.models import BlogPostPayload, Category

def print_section(title):
    print(f"\n{'='*50}")
    print(f" {title} ")
    print(f"{'='*50}")

def test_blog_post_creation():
    print_section("Starting BlogPostPayload Test")
    
    # Create test categories
    print("\nCreating test categories...")
    try:
        cat1 = Category.objects.create(
            name="Test Category 1",
            slug="test-category-1"
        )
        cat2 = Category.objects.create(
            name="Test Category 2",
            slug="test-category-2"
        )
        print(f"Created categories: {cat1.name} ({cat1._id}), {cat2.name} ({cat2._id})")
    except Exception as e:
        print(f"Error creating categories: {str(e)}")
        return
    
    # Test cases
    test_cases = [
        {
            'name': 'String IDs',
            'data': {
                'title': 'Test Post with String IDs',
                'content': 'This is a test post with string IDs',
                'categoryIds': [str(cat1._id)],
                'tagIds': [str(cat2._id)],
                'authorId': '683b3771a6b031d7d73735d7',
                'status': 'scheduled'
            }
        },
        {
            'name': 'ObjectIds',
            'data': {
                'title': 'Test Post with ObjectIds',
                'content': 'This is a test post with ObjectIds',
                'categoryIds': [cat1._id],
                'tagIds': [cat2._id],
                'authorId': ObjectId('683b3771a6b031d7d73735d7'),
                'status': 'scheduled'
            }
        },
        {
            'name': 'JSON String IDs',
            'data': {
                'title': 'Test Post with JSON String IDs',
                'content': 'This is a test post with JSON string IDs',
                'categoryIds': f'["{str(cat1._id)}", "{str(cat2._id)}"]',
                'tagIds': f'["{str(cat1._id)}"]',
                'authorId': '683b3771a6b031d7d73735d7',
                'status': 'scheduled'
            }
        }
    ]
    
    # Run tests
    for test_case in test_cases:
        print_section(f"Test Case: {test_case['name']}")
        print("Input data:", json.dumps(test_case['data'], indent=2, default=str))
        
        try:
            # Create post
            post = BlogPostPayload.objects.create(**test_case['data'])
            print("\n✅ Post created successfully!")
            
            # Display results
            print("\nPost Details:")
            print(f"  ID: {post._id}")
            print(f"  Title: {post.title}")
            print(f"  Status: {post.status}")
            print(f"  Category IDs: {[str(cat_id) for cat_id in post.categoryIds]}")
            print(f"  Tag IDs: {[str(tag_id) for tag_id in post.tagIds]}")
            print(f"  Author ID: {str(post.authorId) if post.authorId else 'None'}")
            
            # Convert to dict to test JSON serialization
            post_dict = {
                'id': str(post._id),
                'title': post.title,
                'categoryIds': [str(cat_id) for cat_id in post.categoryIds],
                'tagIds': [str(tag_id) for tag_id in post.tagIds],
                'authorId': str(post.authorId) if post.authorId else None
            }
            
            print("\nSerialized to JSON:", json.dumps(post_dict, indent=2))
            
            # Clean up
            post.delete()
            print("\n✅ Test cleanup complete")
            
        except Exception as e:
            print(f"\n❌ Error: {str(e)}")
            import traceback
            traceback.print_exc()
    
    # Clean up categories
    cat1.delete()
    cat2.delete()
    
    print_section("Test Completed")

if __name__ == "__main__":
    test_blog_post_creation()
