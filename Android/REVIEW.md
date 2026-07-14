# Code Review — android 브랜치 (b04cb42..ae2a142)

Python Bridge(`/app`)를 Kotlin/Android로 포팅한 5개 커밋에 대한 리뷰. Python 원본과 라인 단위로 대조하며 검토했고, **실제 빌드를 시도한 적이 없는 상태로 커밋된 것으로 보이는 컴파일 에러**가 다수 발견됨. 하드웨어 테스트 이전에 반드시 수정 필요.

리뷰 대상 커밋:
```
b04cb42 android: initial bridge implementation
b078d69 android: implement protocol, packet parsing, and service layers
3914f5a android: implement packet builder and AC controller layer
2f24ec6 android: connect afterblow to AC controller and implement auto-discovery
ae2a142 android: implement settings UI and handoff documentation
```

---

## 치명적 — 컴파일 자체가 안 됨

### 1. `object PacketParser` 중복 선언
**파일**: `protocol/PacketParser.kt:5`, `protocol/PacketProtocol.kt:83`

첫 커밋(b04cb42)에서 만든 스텁 파일 `PacketParser.kt`(`parseC014`/`encodeC013` 미완성 구현)를 삭제하지 않은 채, 3번째 파일 작업(b078d69)에서 `PacketProtocol.kt`에 실제 구현인 `object PacketParser`(`extractPackets` 등)를 또 추가했다. 같은 패키지(`com.samsung.ac.bridge.protocol`)에 동명의 top-level object가 두 개 존재 → `Redeclaration: PacketParser` 컴파일 에러로 **모듈 전체가 빌드 불가**.

```kotlin
// protocol/PacketParser.kt (구 스텁, 삭제되지 않음)
object PacketParser {
    fun parseC014(bytes: ByteArray, store: StateStore) { ... }
    fun encodeC013(settings: Map<String, Any>): ByteArray { ... }
}

// protocol/PacketProtocol.kt (실제 구현)
object PacketParser {
    fun extractPackets(buf: ByteArray): Pair<List<ParsedPacket>, ByteArray> { ... }
    ...
}
```

**조치**: `protocol/PacketParser.kt` 파일 삭제 (내용이 전부 `PacketProtocol.kt`의 `PacketParser`/`PacketBuilder`로 대체됨).

---

### 2. `AfterBlowManager.resume()` — 잘못된 필드명 + 잘못된 함수 호출
**파일**: `afterblow/AfterBlowManager.kt:101, 104`

```kotlin
suspend fun resume(uid: String): Boolean {
    val st = states[uid] ?: return false
    if (!st.drying) return false

    val saved = st.savedState
    val savedAuto = st.savedAuto
    st.drying = false
    st.dry_deadline = null        // ← AfterBlowState의 필드명은 dryDeadline (camelCase)
    st.savedState = null

    restore(uid, saved, savedAuto, "app power ON")   // ← restore()는 (uid, ctrl, saved, savedAuto, why) 5개 인자
    return true
}
```

- `st.dry_deadline` → `Unresolved reference` 컴파일 에러 (존재하는 필드는 `dryDeadline`).
- `restore(uid, saved, savedAuto, "app power ON")` → 실제 시그니처는 `restore(uid: String, ctrl: AcController, saved: AcStatus?, savedAuto: Boolean, why: String)`. `ctrl` 인자 누락 + `AcStatus?`가 `AcController` 자리에 잘못 들어감 → 타입 불일치 컴파일 에러.

앱 전원 ON 시 건조 사이클을 취소/복원하는 핵심 경로가 애초에 빌드되지 않는다.

**조치**: `ctrl = controllers[uid] ?: return false`를 추가하고 `st.dryDeadline = null`, `restore(uid, ctrl, saved, savedAuto, "app power ON")`로 수정.

---

### 3. `BridgeService`의 `EW11Client` 생성자 호출 불일치
**파일**: `service/BridgeService.kt:55`

```kotlin
ew11 = EW11Client(stores, onUnitDiscovered = { uid, address -> ... })
```

`EW11Client`의 실제 생성자는 `EW11Client(host: String, port: Int, stores: MutableMap<String, StateStore>, onUnitDiscovered: ...)`. `stores`(Map)를 `host: String` 자리에 넘기므로 타입 불일치 컴파일 에러.

더 심각한 문제: 이 줄 위에서 인텐트로부터 읽은 `ew11Host`(40행)/`ew11Port`(41행) — 즉 **설정 화면에서 사용자가 입력한 EW11 IP/포트** — 가 이 호출에 전혀 전달되지 않는다. 시그니처를 맞춰도 host/port를 다시 채워 넣지 않으면 SettingsActivity 자체가 무의미해진다.

**조치**: `EW11Client(ew11Host, ew11Port, stores, onUnitDiscovered = {...})`로 수정.

---

### 4. `EW11Client.send()` — `synchronized` 블록 안에서 suspend 함수 호출
**파일**: `ew11/EW11Client.kt:50-63`

```kotlin
suspend fun send(data: ByteArray) = withContext(Dispatchers.IO) {
    synchronized(sendLock) {
        if (!isConnected) throw RuntimeException("EW11 not connected")
        try {
            waitBusIdle()   // ← suspend 함수, synchronized 람다는 non-suspend 함수 타입
            writer?.write(data)
            ...
```

Kotlin은 `synchronized(){}`(non-suspend 함수 타입의 람다)에서 suspend 함수 호출을 허용하지 않는다(inline 여부와 무관하게 컴파일러가 문맥으로 막음). `send()`가 컴파일되지 않는다.

이는 동시에 Python 원본의 `_send_lock` + `_wait_bus_idle()` 조합(전송 직렬화 + 버스 idle 대기)이 Kotlin에서 아직 올바르게 이식되지 않았다는 의미이기도 하다 — `synchronized`는 코루틴을 블로킹하므로 애초에 `Mutex`(kotlinx.coroutines.sync.Mutex)로 바꿔야 한다.

**조치**: `synchronized(sendLock) {}` → `mutex.withLock { }` (`kotlinx.coroutines.sync.Mutex` 사용)로 교체.

---

## 기능적 단절 / 회귀

### 5. `TcpServer`에 `SET_POWER` 커맨드가 없음 — AfterBlow가 네트워크 경로에서 절대 트리거되지 않음
**파일**: `network/TcpServer.kt` (`processCommand`의 `when(cmd)` 전체)

Python 원본은 `session.py`의 `SET_POWER` 핸들러가 실제 전원을 끄기 *전에* `afterblow.on_power_off()`를 호출해 건조 사이클로 가로채고, 전원 ON 시 `afterblow.resume()`으로 복원한다. Kotlin `TcpServer`에는 `SET_POWER` 케이스 자체가 없다 — `STATUS`/`SET_ICOOL`/`SET_ICOOL_DURATION`/`SET_ICOOL_CONFIG`/`SET_AFTERBLOW`/`SUBSCRIBE`뿐이다.

즉 `AfterBlowManager.onPowerOff()`/`resume()`은 (2번 항목이 고쳐지더라도) SmartThings Edge Driver로부터의 실제 전원 제어 흐름에서는 **호출될 방법이 없는 죽은 코드**다.

**조치**: `SET_POWER` 커맨드 추가, `on=false`일 때 `afterblowManager.onPowerOff(uid)`가 `true`를 반환하면 실제 `ctrl.setPower(false)` 호출을 생략, `on=true`일 때 `afterblowManager.resume(uid)`를 우선 시도.

---

### 6. `IcoolManager.deviated()` — 강풍 단계 vane(풍향) 불일치 검사 누락
**파일**: `icool/IcoolManager.kt:212-216` (Python `app/icool.py:386-394`와 대조)

```python
# Python 원본
else:
    if status.wind_free: return True
    v, h = _VANE_MODES.get(st.blow_vane, (True, True))
    if status.vane_vertical != v or status.vane_horizontal != h:
        return True                      # ← 이 검사가 Kotlin에 없음
    if status.fan_mode != st.blow_fan: return True
    if abs(status.target_temp - st.cool_sp()) > 0.05: return True
```

```kotlin
// Kotlin 포팅본 — vane 비교가 통째로 빠짐
} else {
    if (status.windFree) return true
    if (status.fanMode != st.blowFan) return true
    if (abs(status.targetTemp - st.target + st.blowOffset) > 0.05f) return true
}
```

강풍 단계에서 사용자가 리모컨/패널로 풍향(vane)만 바꾸는 경우, Python은 이를 외부 개입으로 인지해 icool을 종료하지만, Kotlin은 이 변경을 감지하지 못해 icool이 계속 "제어 중"이라고 착각한 채 다음 tick에서 설정을 되돌릴 수 있다 — 사용자가 리모컨으로 바꾼 값이 icool에 의해 무시/복구되는 체감상의 오작동.

**조치**: `vaneModePair(st.blowVane)`로 얻은 `(v, h)`와 `status.vaneVertical`/`status.vaneHorizontal`을 비교하는 분기를 복원.

---

### 7. `SET_ICOOL_CONFIG`/`SET_ICOOL`의 config가 전부 문자열화되어 숫자 튜닝값이 항상 무시됨
**파일**: `network/TcpServer.kt:92-94, 113-115` ↔ `icool/IcoolManager.kt:238-242`

```kotlin
// TcpServer: 모든 값이 무조건 String으로 변환됨
val config = req.getAsJsonObject("config")?.let {
    it.entrySet().associate { (k, v) -> k to v.asString }
}
```

```kotlin
// IcoolManager.applyConfig: Number 캐스팅을 기대
(config["margin"] as? Number)?.let { st.margin = ... }
(config["blow_offset"] as? Number)?.let { st.blowOffset = ... }
(config["hum_low"] as? Number)?.let { ... }
```

`v.asString`으로 넘어온 값은 항상 `String`이므로 `as? Number`는 항상 `null`이 되어 `margin`/`blow_offset`/`hum_low`/`hum_high`/`hum_bias_max`는 **절대 반영되지 않는다**. `blow_fan`/`blow_vane`(String 필드)만 우연히 정상 동작.

추가로 `SET_ICOOL_CONFIG` 핸들러(`TcpServer.kt:116`)는 `// TODO: icoolManager.setConfig(uid, config)`로 실제 연결이 아예 안 되어 있어, 이 커맨드는 현재 상태 조회 외에는 아무 일도 하지 않는다 (이건 스스로 TODO로 명시되어 있어 "알려진 미완성"이지만, `SET_ICOOL`의 인라인 config 전달 경로는 완성된 것처럼 보이면서 실제로는 숫자값이 조용히 드롭되는 게 더 위험).

**조치**: config 값을 원래 JSON 타입 그대로(Number는 Number로) 넘기도록 `TcpServer`를 수정하고, `IcoolManager.setConfig()`를 실제로 노출/연결.

---

## 설계 회귀 / 잠재 리스크 (당장 컴파일엔 영향 없음)

### 8. 유닛별 락(`asyncio.Lock`) 제거로 인한 동시성 안전성 후퇴
**파일**: `icool/IcoolManager.kt:36`, `afterblow/AfterBlowManager.kt:31`, `service/BridgeService.kt:28-29`

Python `IcoolState`/`AfterBlowState`는 "한 유닛의 AC 명령 대기가 다른 유닛의 tick/start/stop을 막지 않도록" 유닛별 `asyncio.Lock`을 명시적으로 두었다. Kotlin 포팅에서는 이 락이 전부 빠졌고, `states`/`stores`/`controllers`는 평범한 `mutableMapOf`다.

Python은 단일 스레드 협조적 asyncio라 이 구조여도 데이터 레이스가 없었지만, Kotlin 코루틴은 `Dispatchers.IO`(TcpServer 세션)와 `Dispatchers.Default`(icool/afterblow 루프, EW11 수신 루프)에 걸쳐 **진짜 멀티스레드**로 실행된다. 즉 `states.toList()`로 순회하는 도중 다른 스레드가 `states[uid] = ...`를 실행하면 `ConcurrentModificationException`이나 맵 손상이 발생할 수 있다.

**조치**: 최소한 `ConcurrentHashMap` 사용, 이상적으로는 Python처럼 유닛별 `Mutex`를 `IcoolState`/`AfterBlowState`에 추가해 start/stop/tick을 감싸기.

### 9. `PacketBuilder.seq`의 동시성 미보호
**파일**: `protocol/PacketBuilder.kt:9-15`

전역 싱글턴 `object PacketBuilder`의 `var seq`가 동기화 없이 증감된다. 여러 유닛의 `AcController`가 동시에 명령을 보내면(Kotlin은 실제 병렬 실행) 시퀀스 번호가 경합해 중복되거나 건너뛸 수 있다. Python은 단일 스레드라 문제되지 않았던 부분.

**조치**: `AtomicInteger` 사용 또는 `synchronized`(suspend 호출 없는 순수 계산이므로 여기는 안전)로 보호.

### 10. targetSdk 34에서 `foregroundServiceType="specialUse"`에 필요한 property 누락 가능성
**파일**: `AndroidManifest.xml` (`<service android:name=".service.BridgeService" ... android:foregroundServiceType="specialUse" />`)

Android 14(API 34)부터 `specialUse` 타입의 포그라운드 서비스는 `<service>` 내부에 `<property android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE" android:value="..."/>`를 선언해야 한다. 없으면 `startForeground()` 호출 시 런타임 크래시 가능성 — 이 앱의 핵심 전제인 "상주 서버" 자체가 실기기에서 뜨지 못할 수 있다.

**조치**: 매니페스트에 해당 property 추가.

---

## 종합 평가

1~4번은 **컴파일 자체가 불가능한 수준**이라, 지금 이 브랜치를 그대로 Android Studio에서 열면 빌드가 실패한다. HANDOFF.md에는 "하드웨어 테스트 대기" 상태로 기록되어 있지만, 실제로는 하드웨어는커녕 **빌드조차 시도되지 않은 채 커밋된 것으로 보인다.**

5~7번은 컴파일이 통과하도록 고친 뒤에도 남는 **기능 회귀**로, 특히 5번(AfterBlow가 네트워크 경로에서 트리거 불가)과 6번(강풍 단계 vane 외부개입 미감지)은 Python 원본이 의도적으로 구현한 동작을 조용히 잃어버리는 문제라 우선순위가 높다.

8~10번은 당장 빌드/동작을 막지는 않지만, "Python은 단일 스레드 asyncio였고 Kotlin은 진짜 멀티스레드 코루틴"이라는 근본적 실행 모델 차이에서 비롯된 리스크라 릴리즈 전에 반드시 짚어야 한다.

---

**리뷰 일자**: 2026-07-14
**리뷰 대상**: `android` 브랜치, 커밋 b04cb42..ae2a142 (5개)
**리뷰어**: Claude (Sonnet 5)

---

# 수정 결과 (Fix)

리뷰 10개 항목 + 리뷰가 놓친 추가 결함을 Opus 4.8이 일괄 수정했다. (테스트 환경 부재로 이 저장소에서 컴파일 검증은 불가 — 수동 대조 기반.)

## 리뷰 항목 처리

| # | 항목 | 처리 |
|---|------|------|
| 1 | `PacketParser` 중복 선언 | 스텁 파일 `protocol/PacketParser.kt` **삭제** (구현은 `PacketProtocol.kt`) |
| 2 | `resume()` 필드명/호출 오류 | `dryDeadline`로 수정, `ctrl` 추가, `restore(uid, ctrl, saved, savedAuto, why)` 시그니처로 교정 |
| 3 | `EW11Client` 생성자 불일치 | `EW11Client(host, port, stores, outdoorStore){cb}`로 교정 — 설정 화면의 host/port가 실제 전달됨 |
| 4 | `synchronized` 안 suspend 호출 | `synchronized` 제거, `kotlinx...Mutex`(`sendMutex.withLock`)로 전송 직렬화 |
| 5 | `SET_POWER` 커맨드 부재 | TcpServer 전면 재작성 시 `SET_POWER` 추가 — off→`onPowerOff`, on→`resume` 위임 |
| 6 | `deviated()` 강풍 vane 검사 누락 | 강풍 분기에 `vaneModePair` 기반 vane 불일치 검사 복원 |
| 7 | config 문자열화로 숫자 무시 | JSON 타입 보존(`jsonToMap`), `setConfig()` 실제 연결(TODO 제거) |
| 8 | 유닛별 락 제거 | `IcoolState`/`AfterBlowState`에 `Mutex` 부활 + 매니저 맵을 `ConcurrentHashMap`로 |
| 9 | `PacketBuilder.seq` 경합 | `AtomicInteger`로 교체 |
| 10 | FGS `specialUse` property 누락 | 매니페스트에 `PROPERTY_SPECIAL_USE_FGS_SUBTYPE` + `FOREGROUND_SERVICE_SPECIAL_USE` 권한 추가 |

## 리뷰가 놓친 추가 결함 (직접 수정)

- **A. 와이어 프로토콜 전면 불일치 (가장 치명적)**: 기존 `TcpServer`는 `{cmd,uid,on}`/`{status:ok}`라는 자체 포맷이라 실제 Edge Driver(`{id,cmd,params}`/`{id,ok,data}`, `params.unit_id`)와 전혀 통신 불가였다. `session.py`에 맞춰 **TcpServer 전면 재작성**.
- **B. 기본 제어 커맨드 전부 누락**: `SET_POWER/SET_MODE/SET_TEMP/SET_FAN/SET_VANE/SET_WIND_FREE/SET_LONG_WIND/SET_AUTO_CLEAN/SET_SMART_DRY/PING/LIST_UNITS/STATUS_OUTDOOR`를 session.py와 동일 검증 로직으로 이식(fanOnly 풍량 보정, 0.5℃ 반올림/범위, vane 축 독립 유지 등 포함). 기존엔 icool/afterblow만 있어 전원·온도·모드 제어가 네트워크로 불가능했다.
- **C. 빌드 자체를 막는 파일 누락/오류**: 루트 `build.gradle.kts`가 `com.android.application`+`android{}`를 루트에 두어 즉시 실패 → 올바른 top-level(플러그인 `apply false`)로 교정. `gradle.properties`(`android.useAndroidX=true`) **신규 생성**(없으면 AndroidX 빌드 실패). `proguard-rules.pro` 신규. 매니페스트가 없는 리소스(`@mipmap/ic_launcher`, `@xml/*`) 참조 → 벡터 아이콘 생성 + 참조 정리. 미사용 Room/kapt/Timber 의존 제거.
- **D. clamp 범위 오류**: `16/32`(하드코딩) → 프로토콜 유효범위 `18/30`(`PacketProtocol.TEMP_MIN/MAX`).
- **E. `timer_min` 절삭**: `.toInt()`(내림) → `ceil()`로 Python `math.ceil` 일치.
- **F. `deviated` 설정온도 clamp 누락**: 무풍/강풍 두 분기 모두 `clampTemp`/`coolSp()` 사용으로 Python `cool_sp()` 일치.
- **G. 실외기 데이터 유실/오등록**: 실외기(0x10) 패킷이 `StateStore`(AC 필드만 허용)로 가 전부 드롭되고 가짜 AC 유닛으로 자동등록되던 것을, **`OutdoorStore` 신규**로 분리 라우팅(컨트롤러 미생성).
- **H. uid 대소문자**: `%02X`(대문자) → `%02x`(소문자)로 Python `addr.hex()`와 일치 — 기존 Edge Driver 등록 유닛과 id 호환.
- **I. EW11 재연결**: `receiveLoop`가 에러/EOF에 무한 delay-continue 하던 것을 return하여 상위 루프가 재연결하도록, `rxBuffer` 상한(8192) 추가.
- **J. Mock 모드 무동작**: C014가 없어 유닛이 하나도 안 생기던 것을, mock 모드 시 유닛 1개 프리시드 + EW11 미가동으로 실제 테스트 가능하게.
- **K. 알림 권한**: API 33+ `POST_NOTIFICATIONS` 런타임 요청 추가(없으면 FGS 알림 미표시).

## 남은 알려진 한계 (미수정 — 후속)

- **Gradle wrapper 부재**: `gradlew`/`gradle-wrapper.jar`가 없어 CLI 빌드 불가. Android Studio로 import 시 자동 생성되거나 `gradle wrapper`로 생성 필요.
- **SUBSCRIBE/StreamHub 미구현**: `SUBSCRIBE`는 `"stream not available"` 반환(Python의 hub 부재 시 동작과 동일). 실시간 push는 후속.
- **낙관적 상태 모델**: Python의 desired/reconcile 대신 명령 후 AC의 C014 에코로 `reported` 갱신. 명령~에코 사이 짧은 지연 동안 STATUS가 직전 값을 반환할 수 있음(mock은 즉시 반영).
- **실외기 노출 범위**: `STATUS_OUTDOOR`/STATUS의 `system_power_w`만 제공. 유닛 라벨(`unit_labels`) 영구화 미구현.
- **컴파일/실기기 검증 미완**: SDK 부재로 본 저장소에서 빌드 미수행. Android Studio 빌드 및 실기기/실 EW11 테스트 필요.

**수정 일자**: 2026-07-14
**수정**: Claude (Opus 4.8)
