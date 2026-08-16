FROM python:3.11-slim
WORKDIR /app
COPY app/ .
RUN find /app -name "*.pyc" -delete && find /app -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
# 기본 config.json (CONFIG_FROM_ENV=false 로 마운트 없이 쓸 때의 폴백)
COPY config.json .
# 시작 시 환경 변수로 config.json 을 생성하는 entrypoint
COPY entrypoint.sh .
RUN chmod +x /app/entrypoint.sh

# 이미지에 포함되는 기본 환경 변수. 실행 시 -e 로 덮어쓸 수 있다.
# EW11_HOST 는 반드시 각자 환경의 EW11 IP 로 바꿔야 동작한다(192.168.x.x 는 플레이스홀더).
ENV EW11_HOST=192.168.x.x \
    EW11_PORT=8899 \
    SERVER_HOST=0.0.0.0 \
    SERVER_PORT=8888 \
    REST_PORT=8082 \
    AC_MODE=real \
    LOG_LEVEL=INFO

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["python", "main.py"]
