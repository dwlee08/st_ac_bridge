FROM python:3.11-slim
WORKDIR /app
COPY app/ .
RUN find /app -name "*.pyc" -delete && find /app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
COPY config.json .
CMD ["python", "main.py"]
