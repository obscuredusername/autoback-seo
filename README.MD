# AutoPublish Backend

This is the backend service for the AutoPublish application, built with Django and Celery.

## Prerequisites

- Python 3.8+
- MongoDB
- Redis (optional, for Celery broker/result backend)
- Virtual environment (recommended)

## Setup

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd Saas_AutoPublisher/backendnew
   ```

2. **Create and activate virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

## Database Setup

1. **Run migrations**
   ```bash
   python autopublish/manage.py makemigrations
   python autopublish/manage.py migrate
   ```

2. **Create superuser (optional)**
   ```bash
   python autopublish/manage.py createsuperuser
   ```

## Running the Application

### Development Server

1. **Start Django development server**
   ```bash
   python autopublish/manage.py runserver
   ```
   The application will be available at http://127.0.0.1:8000/

### Celery Workers

1. **Start Celery worker** (in a new terminal)
   ```bash
   cd autopublish
   celery -A autopublish worker --loglevel=info
   ```

2. **Start Celery beat** (in another terminal, for scheduled tasks)
   ```bash
   cd autopublish
   celery -A autopublish beat --loglevel=info
   ```

   Or start both worker and beat together:
   ```bash
   cd autopublish
   celery -A autopublish worker --beat --loglevel=info

   PYTHONPATH=$PYTHONPATH:. celery -A autopublish worker --beat --loglevel=info
   ```

## Environment Variables

Create a `.env` file in the project root with the following variables:

```
DEBUG=True
SECRET_KEY=your-secret-key
MONGODB_URI=your-mongodb-connection-string
CELERY_BROKER_URL=redis://localhost:6379/0  # or your broker URL
CELERY_RESULT_BACKEND=redis://localhost:6379/0  # or your result backend URL
```

## API Documentation

### User Management

#### Create a new user
```bash
curl -X POST "http://localhost:8000/user/create/" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "newuser",
    "email": "user@example.com",
    "password": "securepassword123"
  }'
```

#### User Login
```bash
curl -X POST "http://localhost:8000/user/login/" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "testuser",
    "password": "testpass123"
  }'
```

#### List all users (Admin only)
```bash
curl -X GET "http://localhost:8000/user/users/" \
  -H "Authorization: Token YOUR_AUTH_TOKEN"
```

### Keyword Content

#### Generate blog post from keywords
```bash
curl -X POST "http://localhost:8000/keyword/generate/" \
  -H "Content-Type: application/json" \
  -d '{
    "keywords": [
      {"text": "artificial intelligence"},
      {"text": "machine learning"}
    ],
    "tone": "professional",
    "word_count": 1000,
    "language": "en",
    "country": "us",
    "min_words": 1000
  }'
```

**Required Fields:**
- `keywords`: Array of objects with a `text` property containing the keyword (e.g., `[{"text": "keyword1"}, {"text": "keyword2"}]`)
- `language`: Language code (e.g., "en" for English)
- `country`: Country code (e.g., "us" for United States)
- `min_words`: Minimum number of words for the generated content

**Optional Fields:**
- `tone`: Writing tone (default: "professional")
- `word_count`: Target word count (defaults to min_words if not specified)

### Scraper

#### Keyword-based search
```bash
curl -X POST "http://localhost:8000/scraper/keyword/" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "latest technology trends",
    "max_results": 5
  }'
```

#### Get news by category
```bash
curl -X POST "http://localhost:8000/scraper/news/" \
  -H "Content-Type: application/json" \
  -d '{
        "categories": {           # Dictionary of categories and counts
            "technology": 3,      # Category name and number of articles
            "business": 2,
            "science": 2
        },
        "country": "us",         # Optional: country code (default: 'us')
        "language": "en",        # Optional: language code (default: 'en')
        "vendor": "google"       # Optional: 'google' or 'yahoo' (default: 'google')
    }'
```

### News Content

#### Generate news content
```bash
curl -X POST "http://localhost:8000/news/generate/" \
  -H "Content-Type: application/json" \
  -d '{
    "categories": {
      "technology": 2,
      "business": 1
    },
    "language": "en",
    "country": "us",
    "vendor": "google"
  }'
```
gnew category
world
nation
business
technology
entertainment
sports
science
health
#### Check generation status
```bash
curl -X GET "http://localhost:8000/news/generate/TASK_ID_HERE/"
```

Interactive API documentation is also available at:
- Swagger UI: http://127.0.0.1:8000/swagger/
- ReDoc: http://127.0.0.1:8000/redoc/

## Troubleshooting

- **MongoDB connection issues**: Ensure MongoDB is running and the connection string is correct
- **Celery worker not starting**: Check if Redis (or your chosen broker) is running
- **Missing dependencies**: Run `pip install -r requirements.txt`

## License

[crective]
to dos
i wanna make the save and process image th eonly image function with the ability to return the raw link and also the processed link 
basically making a mode
one mode will process the link other will not and just return the image 
if the return link is set to 0 it will just return raw links but if the retrurn links are set to number it will return the processed links in that number, moreover if i give raw links it shoudl be able to save it and process it 