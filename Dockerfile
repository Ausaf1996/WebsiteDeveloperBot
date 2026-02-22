FROM python:3.11-slim

WORKDIR /app

COPY . .
RUN pip install --no-cache-dir .

CMD exec gunicorn --bind :${PORT:-8080} --workers 1 --threads 4 --timeout 300 local_server:app
