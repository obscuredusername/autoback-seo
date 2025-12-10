from django.core.management.base import BaseCommand
from django.utils import timezone
from bson import ObjectId
from keyword_content.models import BlogPostPayload, Category

class Command(BaseCommand):
    help = 'Test the BlogPostPayload model with different ID formats'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('=== Starting BlogPostPayload Test ==='))
        
        # Create test categories
        self.stdout.write('\nCreating test categories...')
        try:
            cat1 = Category.objects.create(
                name="Test Category 1",
                slug="test-category-1"
            )
            cat2 = Category.objects.create(
                name="Test Category 2",
                slug="test-category-2"
            )
            self.stdout.write(self.style.SUCCESS(f'Created categories: {cat1.name} ({cat1._id}), {cat2.name} ({cat2._id}'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error creating categories: {str(e)}'))
            return
        
        # Test data
        test_cases = [
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
        
        # Run tests
        for i, test_data in enumerate(test_cases, 1):
            self.stdout.write(f'\n=== Test Case {i} ===')
            self.stdout.write(f'Input data: {test_data}')
            
            try:
                # Create post
                post = BlogPostPayload.objects.create(**test_data)
                self.stdout.write(self.style.SUCCESS('Post created successfully!'))
                
                # Display results
                self.stdout.write(f'Post ID: {post._id}')
                self.stdout.write(f'Title: {post.title}')
                self.stdout.write(f'Status: {post.status}')
                self.stdout.write(f'Category IDs: {post.categoryIds} (type: {type(post.categoryIds[0]) if post.categoryIds else "None"})')
                self.stdout.write(f'Tag IDs: {post.tagIds} (type: {type(post.tagIds[0]) if post.tagIds else "None"})')
                self.stdout.write(f'Author ID: {post.authorId} (type: {type(post.authorId)})')
                
                # Clean up
                post.delete()
                self.stdout.write(self.style.SUCCESS('Test cleanup complete'))
                
            except Exception as e:
                self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
        
        # Clean up categories
        cat1.delete()
        cat2.delete()
        
        self.stdout.write(self.style.SUCCESS('\n=== Test Completed Successfully ==='))
