FROM python:3.12-slim

WORKDIR /app

# deps first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app source
COPY src ./src

EXPOSE 8000
ENV ENVIRONMENT=production PORT=8000

# uvicorn src.main:app — the FastAPI app lives at src/main.py
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
