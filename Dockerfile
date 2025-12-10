# FROM python:3.9-slim
FROM mirror.gcr.io/library/python:3.9-slim
# Global environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies + bash
RUN apt-get update && apt-get install -y --no-install-recommends build-essential bash \
 && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Copy project
COPY . .

# Set correct Python path (so that Celery finds all modules)
ENV PYTHONPATH="/app/autopublish:/app"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser \
 && mkdir -p /app/staticfiles /app/mediafiles \
 && chown -R appuser:appuser /app

USER appuser

# Expose Django port
EXPOSE ${DJANGO_PORT}

# Start Django + Celery worker + Celery beat
CMD bash -c "python autopublish/manage.py makemigrations && \
             python autopublish/manage.py migrate && \
             gunicorn autopublish.wsgi:application \
               --bind 0.0.0.0:${DJANGO_PORT} \
               --workers ${GUNICORN_WORKERS:-2} \
               --timeout ${GUNICORN_TIMEOUT:-60} & \
             celery -A autopublish worker --loglevel=info & \
             celery -A autopublish beat --loglevel=info & \
             wait -n"