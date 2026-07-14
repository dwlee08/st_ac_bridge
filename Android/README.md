# AC Bridge Android Implementation

Samsung System AC ↔ SmartThings 연동을 위한 **Android Foreground Service** 기반 브릿지 서버입니다.

```
Samsung System AC
      ↕ RS485
   EW11 WiFi Bridge
      ↕ TCP
 AC Bridge (Android App)  ← 이 프로젝트
      ↕ TCP
SmartThings Edge Driver
```

## 구조

### 패키지 구성

```
com.samsung.ac.bridge/
├── protocol/          # 프로토콜 정의 (AcStatus, OutdoorStatus)
├── state/             # 상태 저장소 (StateStore)
├── ew11/              # EW11 TCP 클라이언트 (EW11Client)
├── icool/             # 인텔리전트 냉방 제어 루프 (IcoolManager)
├── network/           # TCP 서버 (TcpServer, 세션 처리)
├── service/           # Foreground Service (BridgeService)
└── MainActivity.kt    # UI 진입점
```

### 핵심 컴포넌트

- **BridgeService**: Foreground Service로 TCP 서버 + EW11 클라이언트 + icool 루프 실행
- **TcpServer**: SmartThings Edge Driver로부터의 요청(STATUS, SET_ICOOL 등) 처리
- **EW11Client**: EW11 장치와의 TCP 통신 (패킷 송수신)
- **IcoolManager**: 인텔리전트 냉방 제어 루프 (온도 기반 풍량/무풍 자동 조절)
- **StateStore**: 각 유닛의 AC 상태 저장소 (reported + desired override)

## 빌드 및 실행

### 사전 요구사항

- Android Studio (Arctic Fox 이상)
- Android SDK 24+ (타겟 SDK 34)
- Kotlin 1.9+
- Gradle 8.0+

### 빌드

```bash
cd Android
./gradlew assembleDebug
```

### 설치

```bash
./gradlew installDebug
```

또는 Android Studio에서 직접 "Run" 클릭.

## 설정

### EW11 연결 정보

`MainActivity.kt`에서 EW11 호스트 및 포트 설정:

```kotlin
val intent = Intent(this, BridgeService::class.java).apply {
    putExtra("ew11_host", "192.168.0.38")
    putExtra("ew11_port", 8899)
    putExtra("server_port", 8888)
}
```

나중에 Shared Preferences나 설정 화면으로 확장 가능.

## 프로토콜

### SmartThings Edge Driver → AC Bridge

- **STATUS**: 유닛 상태 조회
  ```json
  {"cmd":"STATUS","id":1,"uid":"200000"}
  ```

- **SET_ICOOL**: 인텔리전트 냉방 시작/종료
  ```json
  {"cmd":"SET_ICOOL","id":2,"uid":"200000","on":true,"target":24.0,"config":{}}
  ```

- **SET_ICOOL_DURATION**: 타이머 설정
  ```json
  {"cmd":"SET_ICOOL_DURATION","id":3,"uid":"200000","duration":60}
  ```

### AC Bridge → SmartThings Edge Driver

```json
{"id":1,"status":"ok","data":{"power":true,"mode":"cool",...}}
```

## 주의사항

### 권한

- **INTERNET**: EW11 및 SmartThings Edge Driver와 통신
- **ACCESS_NETWORK_STATE**: 네트워크 상태 모니터링
- **FOREGROUND_SERVICE**: 백그라운드 서비스 실행 (Android 12+)

권한 설정은 `AndroidManifest.xml`에 명시되어 있으며, **런타임 권한은 필요 없음** (네트워크 접근은 설치 시점에 자동 승인).

### 배터리

Foreground Service는 지속적으로 실행되며, 배터리 소비가 있습니다. **AC 제어용 고정 기기(콘센트 연결)**에 설치하기를 권장합니다.

### 네트워크

- Android 기기와 EW11이 **같은 로컬 네트워크**에 있어야 함
- WiFi 끊김 시 자동 재연결 로직 포함

## 포팅 진행률

### Phase 1: 기본 구조 ✅
- [x] StateStore (상태 저장소)
- [x] EW11Client (TCP 클라이언트)
- [x] AcStatus, OutdoorStatus (데이터 클래스)

### Phase 2: 제어 로직 ✅
- [x] IcoolManager (인텔리전트 냉방 루프)
- [x] TcpServer (세션 처리)
- [x] BridgeService (Foreground Service 래퍼)

### Phase 3: 프로토콜 (진행 중)
- [ ] PacketParser (C014, C016 등 파싱)
- [ ] PacketBuilder (C013 구성)
- [ ] EW11 패킷 송수신 루프

### Phase 4: UI 및 통합
- [x] MainActivity (기본 UI)
- [ ] 설정 화면 (EW11 호스트, 포트 설정)
- [ ] 상태 모니터링 (연결 상태, 로그)
- [ ] 테스트 (Python Bridge와 병행 테스트)

## 참고

기존 Python 브릿지는 `/app` 디렉토리에 그대로 보존되며, 이 Android 구현과 병행 가능합니다.

Kotlin 포팅은 기존 Python 로직의 **1:1 변환**을 목표로 하므로, `icool.py`, `afterblow.py`, `protocol.py` 등의 Python 코드를 참고하면서 진행하면 됩니다.
