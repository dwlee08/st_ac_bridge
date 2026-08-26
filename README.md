# ST AC Bridge Server

삼성 시스템 에어컨 ↔ SmartThings 연동을 위한 브릿지 서버입니다.

```
Samsung System AC
      ↕ RS485
   EW11 WiFi Bridge
      ↕ TCP
 AC Bridge Server  ← 이 프로젝트
      ↕ REST + SSE (8085)
SmartThings Edge Driver
```

> **이 브랜치는 REST 전용이다.** 엣지 대면 인터페이스는 REST API + SSE 하나뿐이며,
> 예전의 줄단위 JSON TCP(8888) 서버는 제거했다.
>
> | 엣지 드라이버 | 이 브릿지와 호환 |
> |---|---|
> | `plus_v2` (REST) | ✅ |
> | `plus`, `edge` (줄단위 JSON TCP) | ❌ |
>
> `plus`/`edge` 를 계속 쓰려면 이 브랜치 대신 TCP 를 함께 제공하는 브랜치(`android`)를 배포할 것.

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
    "port": 8085
  },
  "ew11": {
    "host": "192.168.0.38",
    "port": 8899
  },
  "controller_mode": "real",
  "log_level": "INFO"
}
```

#### 설정 항목

| 항목 | 설명 |
|------|------|
| `server.host` | 브릿지 서버 수신 주소. 외부 접속 허용 시 `"0.0.0.0"` |
| `server.port` | REST API 포트 (기본 `8085`). plus_v2 드라이버 설정과 일치해야 함 |
| `ew11.host` | EW11 장치 IP 주소 |
| `ew11.port` | EW11 TCP 포트 (기본값 `8899`) |
| `controller_mode` | `real` = 실제 EW11 사용, `mock` = 테스트용 더미 |
| `log_level` | `DEBUG` / `INFO` / `WARNING` |
| `ignore_addresses` | 자동 등록에서 제외할 주소 목록(선택). 예: `["200003"]` |

> 포트를 바꿨는데 반영되지 않으면 예전 `rest_port` / `REST_PORT` 가 남아 있는지 확인할 것.
> 병행 구조 시절의 별칭이라 남아 있으면 `server.port` 를 덮는다(그 경우 시작 로그에 경고가 찍힌다).

#### 실내기 자동 검색

브릿지 서버는 RS485 버스를 모니터링하다가 실내기의 상태 패킷(C014)을 수신하면 자동으로 등록합니다. 별도로 주소를 입력할 필요가 없습니다.

- 등록 순서대로 **에어컨 1**, **에어컨 2**, ... 라벨이 자동 부여됩니다 (SmartThings 앱에서 나중에 변경 가능)
- 서버 시작 후 약 **5분 이내**에 모든 실내기의 상태 패킷이 수신되어 등록이 완료됩니다
- SmartThings 디바이스 디스커버리는 등록이 완료된 뒤 실행하세요

실재하지 않는 유닛이 잡히지 않도록 다음 조건을 **모두** 만족해야 등록됩니다.

1. 주소가 `20.<channel>.<address>` 형태의 **실제 실내기 주소**일 것
   NASA 주소의 `0xFF`는 "미지정"을 뜻하므로 `20ffff`(= 모든 실내기 브로드캐스트)처럼
   channel/address가 `ff`인 주소는 물리 실내기가 아니며 등록하지 않습니다.
2. 패킷에 **실내기 운전 상태 코드**(전원 `0x4000` / 모드 `0x4001` / 풍량 `0x4006` /
   설정온도 `0x4201` / 실내온도 `0x4203`)가 하나 이상 실려 있을 것
3. 같은 주소에서 위 조건을 만족하는 패킷을 **2회 이상** 관측했을 것

제외된 주소는 로그에 아래와 같이 한 번만 남습니다.

```
INFO ew11_client skip auto-register src=20ffff: not a physical indoor address
```

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
2026-01-01T00:00:00 INFO ew11_client EW11 connected: 192.168.0.38:8899
2026-01-01T00:00:05 INFO ew11_client auto-registered unit: id=200000 addr=200000 label=에어컨 1
2026-01-01T00:00:06 INFO ew11_client auto-registered unit: id=200001 addr=200001 label=에어컨 2
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

## REST API

`plus_v2` 엣지 드라이버가 사용하는 유일한 인터페이스다.
응답 봉투는 `{"ok":true,"data":{...}}` / `{"ok":false,"error":"..."}` 이고,
HTTP 상태코드는 400=잘못된 파라미터, 404=없는 유닛/경로, 503=비활성 기능, 500=서버 오류다.

| 메서드 | 경로 (`/api/v1` 접두) | 본문 | 설명 |
|---|---|---|---|
| GET | `/health` | | 생존 확인 + 등록 유닛 수 |
| GET | `/units` | | 유닛 목록 `[{id,label}]` |
| GET | `/units/{id}` | | 유닛 상태 |
| GET | `/outdoor` | | 실외기(시스템) 상태 — 전력/에너지/외기온도 |
| GET | `/events` | | SSE 이벤트 스트림 (아래 참조) |
| POST | `/units/{id}/power` | `{"on":true}` | 전원 |
| POST | `/units/{id}/mode` | `{"mode":"cool"}` | 운전 모드 (`auto`/`cool`/`dry`/`fanOnly`) |
| POST | `/units/{id}/temperature` | `{"temp":24}` | 설정 온도 (18~30, 0.5℃ 단위 반올림) |
| POST | `/units/{id}/fan` | `{"fan":"high"}` | 풍량 (`auto`/`low`/`medium`/`high`) |
| POST | `/units/{id}/vane` | `{"vertical":true,"horizontal":false}` | 풍향 (생략한 축은 현재값 유지) |
| POST | `/units/{id}/wind-free` | `{"on":true}` | 무풍 |
| POST | `/units/{id}/long-wind` | `{"on":true}` | 롱윈드 |
| POST | `/units/{id}/auto-clean` | `{"on":true}` | 자동 건조 |
| POST | `/units/{id}/smart-dry` | `{"on":true,"ratio":...}` | 스마트 애프터 블로우 |
| POST | `/units/{id}/icool` | `{"on":true,"target":24,"config":{}}` | 인텔리전트 냉방 시작/종료 |
| POST | `/units/{id}/icool/duration` | `{"duration":30}` | 전원 끄기 타이머(분) |
| POST | `/units/{id}/icool/config` | `{"config":{...}}` | 인텔리전트 냉방 유닛별 튜닝값 |

```bash
curl http://192.168.0.30:8085/api/v1/units
curl http://192.168.0.30:8085/api/v1/units/200000
curl -X POST http://192.168.0.30:8085/api/v1/units/200000/power -d '{"on":true}'
```

### 이벤트 스트림 (SSE)

`GET /api/v1/events` 에 접속하면 즉시 전체 스냅샷을 받고, 이후에는 상태가 바뀔 때만
변경분을 받는다(폴링 대체). 20초마다 `: ping` 주석이 오므로 끊김을 바로 감지할 수 있다.

```
event: snapshot
data: {"t":"snapshot","units":{"200000":{...}},"outdoor":{...}}

event: state
data: {"t":"state","u":"200000","d":{"power":true}}

event: outdoor
data: {"t":"outdoor","d":{"power_w":1200}}
```

```bash
curl -N http://192.168.0.30:8085/api/v1/events
```

---

## Edge Driver 연동

SmartThings Edge Driver 설정에서 다음을 입력합니다.

| 항목 | 값 |
|------|----|
| 서버 IP | 브릿지 서버 IP |
| 서버 Port | `config.json`의 `server.port` (기본 `8085`) |

드라이버는 REST 를 쓰는 **`plus_v2`** 여야 한다(위 호환표 참고).

브릿지 서버 시작 후 약 5분 뒤 디바이스 디스커버리를 실행하면 자동 검색된 실내기가 SmartThings에 추가됩니다.

---

## 문제 해결

**EW11에 연결이 안 되는 경우**
- EW11 IP/포트가 `config.json`과 일치하는지 확인
- EW11과 서버가 같은 네트워크에 있는지 확인
- `ping <ew11 IP>`로 네트워크 연결 확인

**에어컨 상태가 SmartThings에 반영되지 않는 경우**
- `docker logs ac-bridge-server`에서 C014 패킷 수신 로그 확인
- Edge Driver 설정의 서버 IP/포트 확인
- REST 가 살아있는지 확인: `curl http://<브릿지IP>:8085/api/v1/health`
- 실시간 반영이 안 되면 SSE 확인: `curl -N http://<브릿지IP>:8085/api/v1/events`
- 드라이버가 `plus`/`edge`(TCP)면 이 브랜치와는 통신되지 않는다 — `plus_v2` 로 교체

**실재하지 않는 실내기가 잡히는 경우**
- 브릿지는 메모리에만 유닛을 등록하므로 `docker restart ac-bridge-server` 로 목록이 초기화됩니다
- SmartThings 앱에 이미 추가된 유령 디바이스는 앱에서 직접 삭제해야 합니다
- 위 필터에도 걸리지 않는 주소가 계속 잡히면 `ignore_addresses` 에 해당 주소를 추가하세요
  (`docker logs` 의 `auto-registered unit: id=...` 로그에서 주소 확인)

**명령이 에어컨에 전달되지 않는 경우**
- 로그에서 `EW11 TX power` 또는 `EW11 TX` 로그 확인
- `controller_mode`가 `real`인지 확인 (`mock`이면 실제 패킷 미전송)
