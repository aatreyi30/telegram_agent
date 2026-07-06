FROM python:3.12-slim

WORKDIR /app

# deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app source
COPY src ./src

EXPOSE 8000
ENV ENVIRONMENT=production PORT=8000

# Railway/Render inject $PORT at runtime; shell form lets it expand (falls back to 8000).
# One worker only — the cron scheduler must run on a single process (leader lock).
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
