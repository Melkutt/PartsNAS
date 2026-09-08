# PartsNAS - single image: FastAPI serves the API and the static frontend.
# Targets linux/amd64 (Synology DS224+, Intel Celeron J4125).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PARTSNAS_DATA_DIR=/data \
    PARTSNAS_SEED_DIR=/app/seed \
    PARTSNAS_FRONTEND_DIR=/app/frontend

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY seed/ ./seed/

WORKDIR /app/backend
EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health').status==200 else 1)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
