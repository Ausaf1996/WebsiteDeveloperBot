FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir .

COPY . .

CMD exec gunicorn --bind :${PORT:-8080} --workers 1 --threads 4 --timeout 120 local_server:app
