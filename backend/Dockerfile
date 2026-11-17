FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends libpq5 && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd -m app && mkdir -p /app/media /app/staticfiles && chown -R app /app
USER app
ENV DEBUG=0 MEDIA_ROOT=/app/media
RUN SECRET_KEY=build python manage.py collectstatic --noinput
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
# api (default). worker/beat override CMD in docker-compose.yml
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--threads", "2", "--access-logfile", "-"]
