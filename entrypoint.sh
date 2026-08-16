#!/bin/sh
# 환경 변수(-e)로 받은 값들로 /app/config.json 을 실행 시점에 동적 생성한다.
#
# 방법 2(환경 변수 주입)가 기본 동작이다. config.json 파일을 직접 마운트해서
# 쓰고 싶으면(방법 1) CONFIG_FROM_ENV=false 로 실행하면 이 생성 단계를 건너뛴다.
set -e

CONFIG_PATH="${CONFIG_PATH:-/app/config.json}"

if [ "${CONFIG_FROM_ENV:-true}" = "false" ]; then
    echo "[entrypoint] CONFIG_FROM_ENV=false → 기존 ${CONFIG_PATH} 를 그대로 사용"
else
    # 기본값 설정 (미지정 env 는 아래 기본값 사용)
    SERVER_HOST="${SERVER_HOST:-0.0.0.0}"
    SERVER_PORT="${SERVER_PORT:-8888}"
    REST_PORT="${REST_PORT:-8082}"   # REST API 포트. 0이면 REST 비활성(TCP 전용)
    EW11_HOST="${EW11_HOST:-}"          # real 모드에서 미지정이면 앱이 명확한 에러로 종료
    EW11_PORT="${EW11_PORT:-8899}"
    AC_MODE="${AC_MODE:-real}"
    LOG_LEVEL="${LOG_LEVEL:-INFO}"
    UNITS="${UNITS:-[]}"                # 실내기 사전등록용 JSON 배열(선택). 예: '[{"id":"200000","address":"200000"}]'
    IGNORE_ADDRESSES="${IGNORE_ADDRESSES:-[]}"  # 자동등록 제외 주소 JSON 배열(선택). 예: '["200003"]'

    cat > "${CONFIG_PATH}" <<EOF
{
  "server": {
    "host": "${SERVER_HOST}",
    "port": ${SERVER_PORT},
    "rest_port": ${REST_PORT}
  },
  "ew11": {
    "host": "${EW11_HOST}",
    "port": ${EW11_PORT}
  },
  "controller_mode": "${AC_MODE}",
  "log_level": "${LOG_LEVEL}",
  "units": ${UNITS},
  "ignore_addresses": ${IGNORE_ADDRESSES}
}
EOF

    echo "[entrypoint] 환경 변수로 ${CONFIG_PATH} 생성 완료:"
    cat "${CONFIG_PATH}"
fi

# 원래 실행하려던 메인 프로세스 실행 (Dockerfile 의 CMD)
exec "$@"
