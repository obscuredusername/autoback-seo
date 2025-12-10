from django.core.management.base import BaseCommand
from django.db import connections
from bson import ObjectId
import pymongo

class Command(BaseCommand):
    help = 'Copy categories from source collection to keyword_content_categories and news_content_categories'

    def add_arguments(self, parser):
        parser.add_argument(
            '--source-db',
            type=str,
            default='default',
            help='Name of the source database connection in settings.DATABASES',
        )
        parser.add_argument(
            '--source-collection',
            type=str,
            required=True,
            help='Name of the source collection to copy categories from',
        )
        parser.add_argument(
            '--target-db',
            type=str,
            default='default',
            help='Name of the target database connection in settings.DATABASES',
        )

    def handle(self, *args, **options):
        # Get MongoDB connections
        source_db_alias = options['source_db']
        target_db_alias = options['target_db']
        source_collection_name = options['source_collection']
        
        # Get database connections
        source_connection = connections[source_db_alias]
        target_connection = connections[target_db_alias]
        
        # Get database clients
        source_client = source_connection.client
        target_client = target_connection.client
        
        # Get database names (you might need to adjust this based on your settings)
        source_db_name = source_connection.settings_dict['NAME']
        target_db_name = target_connection.settings_dict['NAME']
        
        # Get the collections
        source_db = source_client[source_db_name]
        target_db = target_client[target_db_name]
        
        source_collection = source_db[source_collection_name]
        target_collections = {
            'keyword_content_category': target_db['keyword_content_category'],
            'news_content_newscategory': target_db['news_content_newscategory']
        }
        
        # Get all categories from source
        categories = list(source_collection.find())
        
        if not categories:
            self.stdout.write(self.style.WARNING(f'No categories found in source collection {source_collection_name}'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'Found {len(categories)} categories to copy'))
        
        # Process each target collection
        for target_name, target_collection in target_collections.items():
            self.stdout.write(f'\nProcessing target collection: {target_name}')
            
            # Get existing slugs to avoid duplicates
            existing_slugs = set(target_collection.distinct('slug'))
            
            # Prepare documents for bulk insert
            docs_to_insert = []
            for doc in categories:
                # Skip if slug already exists
                if 'slug' in doc and doc['slug'] in existing_slugs:
                    self.stdout.write(f'  - Skipping duplicate slug: {doc.get("slug")}')
                    continue
                    
                # Prepare the document for insertion
                new_doc = {
                    'name': doc.get('name', ''),
                    'slug': doc.get('slug', ''),
                    'description': doc.get('description', ''),
                }
                
                # Handle different field names for news category if needed
                if target_name == 'news_content_newscategory':
                    new_doc['is_active'] = True
                
                docs_to_insert.append(new_doc)
            
            if not docs_to_insert:
                self.stdout.write('  No new categories to insert')
                continue
                
            # Insert documents in bulk
            try:
                result = target_collection.insert_many(docs_to_insert)
                self.stdout.write(self.style.SUCCESS(
                    f'  Successfully inserted {len(result.inserted_ids)} categories into {target_name}'
                )
            except Exception as e:
                self.stdout.write(self.style.ERROR(
                    f'  Error inserting into {target_name}: {str(e)}'
                ))
        
        self.stdout.write(self.style.SUCCESS('\nCategory copy process completed!'))
