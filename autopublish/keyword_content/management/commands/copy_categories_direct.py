from django.core.management.base import BaseCommand
from pymongo import MongoClient
from bson import ObjectId
import urllib.parse

class Command(BaseCommand):
    help = 'Copy categories from source collection to keyword_content_categories and news_content_categories using direct MongoDB connection'

    def add_arguments(self, parser):
        parser.add_argument(
            '--connection-string',
            type=str,
            required=True,
            help='MongoDB connection string (e.g., mongodb://user:password@host:port)',
        )
        parser.add_argument(
            '--source-db',
            type=str,
            required=True,
            help='Name of the source database',
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
            help='Name of the target database (defaults to source-db if not provided)',
        )

    def handle(self, *args, **options):
        # Get connection parameters
        connection_string = options['connection_string']
        source_db_name = options['source_db']
        target_db_name = options.get('target_db') or source_db_name
        source_collection_name = options['source_collection']
        
        # Parse the connection string to handle special characters in password
        parsed_uri = urllib.parse.urlparse(connection_string)
        if parsed_uri.password:
            # Rebuild the connection string with properly encoded password
            username = urllib.parse.quote_plus(parsed_uri.username)
            password = urllib.parse.quote_plus(parsed_uri.password)
            netloc = f"{username}:{password}@{parsed_uri.hostname}"
            if parsed_uri.port:
                netloc += f":{parsed_uri.port}"
            connection_string = f"{parsed_uri.scheme}://{netloc}"
        
        self.stdout.write(self.style.SUCCESS(f'Connecting to MongoDB at {parsed_uri.hostname}...'))
        
        try:
            # Connect to MongoDB
            client = MongoClient(connection_string)
            
            # Get the source collection
            source_db = client[source_db_name]
            source_collection = source_db[source_collection_name]
            
            # Define target collections
            target_db = client[target_db_name]
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
                    ))
                except Exception as e:
                    self.stdout.write(self.style.ERROR(
                        f'  Error inserting into {target_name}: {str(e)}'
                    ))
            
            self.stdout.write(self.style.SUCCESS('\nCategory copy process completed!'))
            
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error: {str(e)}'))
        finally:
            if 'client' in locals():
                client.close()
