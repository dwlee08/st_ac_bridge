# Android AC Bridge - Handoff Document

## Overview

AC Bridge Android implementation은 Samsung System AC를 SmartThings와 연동하기 위한 Foreground Service입니다. Python Bridge의 핵심 로직(icool, afterblow, 프로토콜)을 Kotlin으로 포팅하여, Android 기기를 AC 제어 서버로 동작시킵니다.

```
Samsung System AC
      ↕ RS485
   EW11 WiFi Bridge
      ↕ TCP
 AC Bridge (Android)  ← 현재 구현 완료
      ↕ TCP
SmartThings Edge Driver
```

## Architecture

### Layers

```
┌─────────────────────────────────────────┐
│         MainActivity / SettingsActivity │
│         (UI + Configuration)            │
└─────────────────────────────────────────┘
                    ↑
┌─────────────────────────────────────────┐
│         BridgeService (Foreground)      │
│  (lifecycle + initialization)           │
└─────────────────────────────────────────┘
                    ↑
    ┌───────────────┼───────────────┐
    ↓               ↓               ↓
 TcpServer      IcoolManager   AfterBlowManager
 (Edge Driver   (Temperature   (Smart drying
  protocol)      control)       on power off)
    ↓               ↓               ↓
    └───────────────┼───────────────┘
                    ↑
┌─────────────────────────────────────────┐
│         AcController (abstract)         │
│  RealAcController    MockAcController   │
└─────────────────────────────────────────┘
                    ↑
┌─────────────────────────────────────────┐
│      PacketBuilder + PacketParser       │
│      (C013 command, C014 status)        │
└─────────────────────────────────────────┘
                    ↑
┌─────────────────────────────────────────┐
│      EW11Client + StateStore            │
│  (TCP communication + state management) │
└─────────────────────────────────────────┘
```

### Package Structure

```
com.samsung.ac.bridge/
├── MainActivity.kt                  # UI 진입점
├── SettingsActivity.kt              # 설정 화면
├── config/ConfigManager.kt          # SharedPreferences 관리
├── protocol/
│   ├── AcStatus.kt                  # 데이터 클래스
│   ├── PacketProtocol.kt            # 상수 + 코드 매핑
│   ├── PacketParser.kt              # C014/C016 파싱
│   ├── PacketBuilder.kt             # C013 생성
│   └── StateDecoder.kt              # 코드→필드 변환
├── state/StateStore.kt              # 상태 저장 (reported + desired)
├── ac/AcController.kt               # 실제/테스트 AC 제어
├── ew11/EW11Client.kt               # EW11 TCP 통신
├── icool/IcoolManager.kt            # 온도 제어 루프
├── afterblow/AfterBlowManager.kt     # 송풍 건조
├── network/TcpServer.kt             # SmartThings Edge 프로토콜
└── service/BridgeService.kt         # Foreground Service
```

## Completed Features

### ✅ Phase 1: Core Protocol
- **CRC16-XMODEM** 검증
- **C014 Status Packet** 파싱 (AC 상태 수신)
- **C016 ACK Packet** 처리
- **C013 Command Packet** 생성 (AC 명령 전송)
- Code-value 매핑 (power, mode, fan_mode, temperature, vane, wind_free 등)

### ✅ Phase 2: State Management
- **StateStore**: reported (기기 실제 상태) + desired (사용자 명령) 이원화
- **Auto-discovery**: C014 수신 시 새 유닛 자동 등록
- **Map-based update**: StateStore.update(Map) 단일 인터페이스

### ✅ Phase 3: Device Communication
- **EW11Client**: TCP 수신/송신 + 패킷 추출
- **onUnitDiscovered callback**: 유닛 등록 시 컨트롤러 생성
- **Packet routing**: C014→StateDecoder→StateStore

### ✅ Phase 4: Control Managers
- **IcoolManager** (인텔리전트 냉방)
  - 실측 온도 + 습도 보정으로 체감온도 계산
  - 목표온도 기준 ±margin 히스테리시스로 무풍/강풍 전환
  - 타이머 (ON 시 카운트, OFF 시 일시정지)
  - 외부 조작 감지 시 자동 종료
  
- **AfterBlowManager** (스마트 송풍 건조)
  - 전원 OFF 시 자동 송풍 건조 (최대 시간/최소 동작시간 설정)
  - icool 동작 중 종료 시 icool 정지
  - 송풍 중 원격 조작 감지 시 이전 상태 복원
  - 자동건조 on/off 제어

- **TcpServer** (SmartThings Edge Driver 연동)
  - STATUS: 유닛 상태 조회
  - SET_ICOOL: 인텔리전트 냉방 시작/종료
  - SET_ICOOL_DURATION: 타이머 설정
  - SET_ICOOL_CONFIG: 파라미터 조정
  - SET_AFTERBLOW: 송풍 건조 on/off
  - SUBSCRIBE: 상태 변경 푸시 (TODO)

### ✅ Phase 5: UI & Configuration
- **MainActivity**: 서비스 시작/종료 버튼
- **SettingsActivity**: EW11 호스트/포트, 서버 포트, Mock 모드 설정
- **ConfigManager**: SharedPreferences 자동 저장/로드
- **Foreground Service**: 백그라운드 지속 실행 (FOREGROUND_SERVICE 권한)

## Remaining Work

### 🔲 Priority 1: Integration & Testing
1. **실제 하드웨어 테스트**
   - EW11 연결 검증
   - C014/C016 패킷 실제 수신 확인
   - AC 명령(C013) 전송 동작 확인

2. **Python Bridge와의 비교 테스트**
   - 동일한 EW11에 대해 둘 다 연결 후 상태 일치 확인
   - icool 온도 제어 동작 검증
   - afterblow 타이머/복원 동작 검증

3. **SmartThings Edge Driver 연동 테스트**
   - TcpServer 포트 개방 및 연결 확인
   - STATUS 응답 형식 검증
   - SET_ICOOL 명령 수신/처리 확인

### 🔲 Priority 2: StreamHub (상태 변경 푸시)
현재 TcpServer는 요청-응답만 처리. SUBSCRIBE는 미구현.

**구현 필요:**
```kotlin
class StreamHub(
    private val stores: Map<String, StateStore>,
    private val icoolManager: IcoolManager,
    private val afterblowManager: AfterBlowManager,
) {
    private val subscribers = mutableSetOf<Socket>()
    
    suspend fun subscribe(socket: Socket) {
        // 1. snapshot 전송
        // 2. 주기적으로 상태 변경 감지 후 diff 푸시
    }
}
```

**Python 참고:**
- `app/stream.py` (전체 구현)
- `SWEEP_INTERVAL = 1.0` (1초마다 상태 확인)
- `_unit_state()`: icool_active, timer_min, after_blow_enabled 추가

### 🔲 Priority 3: 추가 기능 (선택사항)

#### Logging & Monitoring
- Timber 라이브러리 추가 (이미 build.gradle에 의존 선언됨)
- 로그 파일 저장 (Logcat만으로는 부족)
- 대시보드: 연결 상태, icool/afterblow 활성 여부

#### Error Handling & Recovery
- EW11 연결 재시도 로직 (지수 백오프)
- Packet 파싱 에러 처리
- AC 명령 전송 실패 시 재시도

#### Device Configuration UI
- 유닛별 이름 설정 (label)
- icool 파라미터 (margin, blow_offset, humidity thresholds)
- afterblow 파라미터 (ratio, max_min, min_min)

#### Database (Room)
현재는 메모리에 상태 저장. 영구 저장 필요시:
```kotlin
@Entity
data class AcStatusEntity(
    @PrimaryKey val uid: String,
    val power: Boolean,
    val mode: String,
    // ...
)
```

---

## Implementation Notes

### State Flow
```
EW11 수신 → extractPackets() → ParsedPacket
  ↓
handleStatus() → StateDecoder.decodeCodes() → Map
  ↓
StateStore.update() → reported 갱신
  ↓
IcoolManager.tick() / AfterBlowManager.tick() → 컨트롤 로직 실행
  ↓
AcController.applySettings() → PacketBuilder.buildApplySettings()
  ↓
EW11Client.send() → C013 패킷 전송
```

### Control Loop Timing
- **IcoolManager.runLoop()**: 5초마다 tick (TICK_SEC = 5L)
- **AfterBlowManager.runLoop()**: 5초마다 tick
- **TcpServer**: 비동기 세션 처리 (요청 수신 시마다)

### Auto-Discovery
1. EW11에서 C014 패킷 수신
2. `PacketParser.extractPackets()` → ParsedPacket 생성
3. `handleStatus()` → StateStore 없으면 자동 생성
4. `onUnitDiscovered(uid, address)` callback 호출
5. BridgeService에서 해당 uid로 RealAcController 또는 MockAcController 생성
6. 이후 모든 명령은 자동으로 라우팅됨

### Mock Mode
테스트 환경에서 EW11 없이 동작:
```kotlin
// MainActivity에서 시작 시
intent.putExtra("mock_mode", true)

// MockAcController: 실제 전송 대신 로그 + StateStore 직접 갱신
// SmartThings Edge Driver로 STATUS 요청 → 메모리 상태 응답
```

---

## Build & Run

### Prerequisites
- Android Studio Arctic Fox+
- Android SDK 24+ (minSdk), Target SDK 34
- Kotlin 1.9+
- Gradle 8.0+

### Build
```bash
cd Android
./gradlew assembleDebug
```

### Install
```bash
./gradlew installDebug
```

또는 Android Studio에서 "Run" 클릭.

### Configuration
앱 시작 → Settings 버튼 → EW11 호스트/포트 설정 → Save

### Start Service
Main 화면 → "Start Service" 버튼 → Foreground Service 활성화

---

## Git & Versioning

### Branch Structure
```
main (Python Bridge, 변경 없음)
└─ plus (기존 작업)
└─ android (이 구현, 4개 커밋)
   b04cb42 android: initial bridge implementation
   b078d69 android: implement protocol, packet parsing, and service layers
   3914f5a android: implement packet builder and AC controller layer
   2f24ec6 android: connect afterblow to AC controller and implement auto-discovery
   (+ settings & config)
```

### Commit Convention
```
android: <feature summary>

<detailed explanation>

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>
```

---

## Troubleshooting

### EW11 연결 실패
1. EW11이 켜져 있고 네트워크에 연결되어 있는지 확인
2. 설정에서 호스트/포트가 올바른지 확인
3. Android 기기와 EW11이 같은 네트워크에 있는지 확인
4. Logcat에서 "EW11 connected" 로그 확인

### AC 명령이 실행되지 않음
1. 자동 등록 이후 5분 정도 기다림 (C014 수신 필요)
2. Logcat에서 "Updated <uid>" 또는 "Auto-registered unit" 로그 확인
3. SmartThings Edge Driver에서 STATUS 요청 후 응답 확인
4. SET_ICOOL 커맨드 정상 수신 확인 (TcpServer 로그)

### Mock Mode에서는 정상인데 Real Mode에서 안 됨
1. EW11 연결 상태 확인
2. C014 패킷 수신 로그 확인
3. PacketParser.extractPackets() 결과 확인
4. StateDecoder 필드 매핑 검증

---

## References

### Python Bridge (참고용)
- `app/icool.py`: IcoolManager 원본 구현
- `app/afterblow.py`: AfterBlowManager 원본 구현
- `app/protocol.py`: 프로토콜 정의
- `app/packet_parser.py`: C014/C016 파싱 (원본)
- `app/packet_builder.py`: C013 생성 (원본)
- `app/stream.py`: StreamHub 구현

### SmartThings Edge Driver
EdgeDriver와의 통신 프로토콜:
- JSON 기반 명령/응답
- TCP 포트 (기본 8888)
- SUBSCRIBE는 미구현 (필요시 stream.py 참고)

### Samsung AC Protocol
- RS485 기반 통신
- EW11: WiFi-RS485 게이트웨이
- 코드 매핑: 0x4000=power, 0x4001=mode, 0x4006=fan_mode 등

---

## Next Steps for Future Developer

1. **테스트 환경 준비**
   - EW11 + AC 실제 연결
   - SmartThings Edge Driver 준비

2. **StreamHub 구현**
   - `/Android/app/src/main/java/com/samsung/ac/bridge/network/StreamHub.kt` 작성
   - TcpServer에 통합
   - BridgeService에서 초기화

3. **실제 테스트**
   - 각 제어 모드 검증 (icool on/off, 온도 변경, 타이머)
   - afterblow 동작 확인 (전원 off 시 송풍, 시간 측정)
   - SmartThings 앱에서 조작 후 Android 로그 확인

4. **배포**
   - Release build 생성
   - 스토어 업로드 또는 APK 직배포

---

**Last Updated**: 2026-07-14
**Status**: Ready for hardware testing
**Contact**: Dongwoo Lee (dwoo08.lee@ax.samsung.com)
