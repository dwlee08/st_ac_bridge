FROM python:3.11-slim
WORKDIR /app
COPY app/ .
RUN find /app -name "*.pyc" -delete && find /app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
# 기본 config.json (CONFIG_FROM_ENV=false 로 마운트 없이 쓸 때의 폴백)
COPY config.json .
# 시작 시 환경 변수로 config.json 을 생성하는 entrypoint
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "main.py"]
