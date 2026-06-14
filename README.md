# ST AC Bridge Server

삼성 시스템 에어컨 ↔ SmartThings 연동을 위한 브릿지 서버입니다.

```
Samsung System AC
      ↕ RS485
   EW11 WiFi Bridge
      ↕ TCP
 AC Bridge Server  ← 이 프로젝트
      ↕ TCP
SmartThings Edge Driver
```

---

## 요구 사항

- Docker, Docker Compose가 설치된 서버 (Linux 권장)
- 삼성 시스템 에어컨에 연결된 **EW11** WiFi-RS485 브릿지 (설치 방법은 "삼성 시스템에어컨 와이파이 킷 셀프 설치" 관련 글을 참조)
- SmartThings 허브에 설치된 **st-ac Edge Driver**

---

## 설치

### 1. 파일 배치

서버에 프로젝트 디렉토리를 복사합니다.

```bash
scp -r st_ac_bridge/ user@<서버IP>:/opt/ac-bridge-server/
```

또는 직접 서버에서 클론합니다.

### 2. config.json 설정

```bash
cd /opt/ac-bridge-server
nano config.json
```

```json
{
  "server": {
    "host": "0.0.0.0",
    "port": 8888
  },
  "ew11": {
    "host": "192.168.0.38",
    "port": 8899
  },
  "units": [
    { "id": "unit_0", "address": "200000", "label": "에어컨 1호기" },
    { "id": "unit_1", "address": "200001", "label": "에어컨 2호기" }
  ],
  "controller_mode": "real",
  "log_level": "INFO"
}
```

#### 설정 항목

| 항목 | 설명 |
|------|------|
| `server.host` | 브릿지 서버 수신 주소. 외부 접속 허용 시 `"0.0.0.0"` |
| `server.port` | 브릿지 서버 포트. Edge Driver 설정과 일치해야 함 |
| `ew11.host` | EW11 장치 IP 주소 |
| `ew11.port` | EW11 TCP 포트 (기본값 `8899`) |
| `units` | 실내기 목록. `id`는 임의 문자열, `address`는 RS485 주소 (hex 6자리), `label`은 SmartThings에 표시될 초기 이름 (앱에서 나중에 변경 가능) |
| `controller_mode` | `real` = 실제 EW11 사용, `mock` = 테스트용 더미 |
| `log_level` | `DEBUG` / `INFO` / `WARNING` |

#### 실내기 RS485 주소

삼성 시스템 에어컨 실내기 주소는 순서대로 할당됩니다.

| 실내기 | address |
|--------|---------|
| 1호기 | `200000` |
| 2호기 | `200001` |
| 3호기 | `200002` |
| 4호기 | `200003` |
| 5호기 | `200004` |

실내기가 2대라면 `units`에 `unit_0`, `unit_1` 두 항목만 남기면 됩니다.

### 3. 실행

```bash
cd /opt/ac-bridge-server
docker compose up -d --build
```

### 4. 로그 확인

```bash
docker logs -f ac-bridge-server
```

정상 동작 시 아래와 같은 로그가 출력됩니다.

```
2026-01-01T00:00:00 INFO main AC Bridge Server starting — mode=real
2026-01-01T00:00:00 INFO main unit registered: id=unit_0 address=200000
2026-01-01T00:00:00 INFO ew11_client EW11 connected: 192.168.0.38:8899
```

---

## 업데이트

설정만 변경하는 경우 Docker 재빌드 없이 재시작만 하면 됩니다.

```bash
# config.json만 변경 시
docker restart ac-bridge-server

# 코드 변경 시
docker compose up -d --build --force-recreate --no-deps
```

---

## Edge Driver 연동

SmartThings Edge Driver 설정에서 다음을 입력합니다.

| 항목 | 값 |
|------|----|
| 서버 IP | 브릿지 서버 IP |
| 서버 Port | `config.json`의 `server.port` (기본 `8888`) |

디바이스 디스커버리 시 `units`에 등록된 실내기가 SmartThings에 자동으로 추가됩니다.

---

## 문제 해결

**EW11에 연결이 안 되는 경우**
- EW11 IP/포트가 `config.json`과 일치하는지 확인
- EW11과 서버가 같은 네트워크에 있는지 확인
- `ping <ew11 IP>`로 네트워크 연결 확인

**에어컨 상태가 SmartThings에 반영되지 않는 경우**
- `docker logs ac-bridge-server`에서 C014 패킷 수신 로그 확인
- Edge Driver 설정의 서버 IP/포트 확인

**명령이 에어컨에 전달되지 않는 경우**
- 로그에서 `EW11 TX power` 또는 `EW11 TX` 로그 확인
- `controller_mode`가 `real`인지 확인 (`mock`이면 실제 패킷 미전송)
