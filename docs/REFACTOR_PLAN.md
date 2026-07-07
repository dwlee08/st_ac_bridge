# st_ac_bridge `app/` 리팩토링 계획서

| 항목 | 값 |
|---|---|
| 대상 | `app/` (12개 모듈, 1742줄) |
| 기준 커밋 | `8e793ce` (branch `plus`) |
| 작성일 | 2026-07-07 |
| 개정 | v1.1 (2026-07-07) — `REFACTOR_PLAN_REVIEW.md` 교차 검토 반영. 회신 내역은 부록 A |
| 구현 현황 | v1.2 (2026-07-07) — **T0·R1(+D1)·R2·R4·R5(D2)·R6·R7 구현 완료.** `tests/` 63건 통과. 잔여: R3(실기기 C016 캡처 대기), R5의 실기기 수용 확인 게이트(off 코드 동봉 패킷), R8·N1·N2(보류) |
| 목적 | 코드 리뷰에서 도출된 동작 결함·중복·성능 개선안을 실행 계획으로 확정하고, 별도 agent가 교차 검증할 수 있도록 근거·검증 기준을 명시 |
| 상태 범례 | ✅ 적용 확정 · 🔧 리팩토링 확정 · 💬 추가 논의 필요 · ⏸ 보류 · ❓ 사용자 결정 대기 |

---

## 교차 검증 agent를 위한 안내

각 항목은 **독립적으로 검증 가능**하도록 다음을 포함한다: (a) 근거 위치(파일·심볼), (b) 문제 주장, (c) 제안 변경, (d) **검증 기준**(수락 조건), (e) 리스크. 검증 agent는 다음을 수행한다:

1. 각 항목의 "근거"가 현재 코드(`8e793ce`)에서 주장대로 존재하는지 확인한다. 라인 번호는 이동할 수 있으므로 **심볼(함수/변수)명 기준**으로 찾는다.
2. "문제 주장"이 실제로 성립하는지 반례를 시도한다(특히 R1·R2·R3).
3. "검증 기준"이 변경의 정확성을 충분히 보장하는지, 누락된 회귀 시나리오가 없는지 평가한다.
4. R3(💬)와 R2의 외부 의존(엣지 드라이버 계약)에 대해서는 **결론이 아니라 검토 의견**을 남긴다.

---

## 요약 표

| ID | 분류 | 상태 | 근거 파일 | 위험도 | 한 줄 요약 |
|----|------|------|-----------|--------|-----------|
| T0 | 테스트 | 🔧 | `tests/` (신규) | 낮음 | 리팩토링 선행 단위 테스트 스캐폴드 (리뷰 반영 신규) |
| R1 | 버그 | ✅ | `session.py` | 낮음 | 동작 불가능한 SET_FAN 검증 가드(`"fan"` → `"fanOnly"`) + D1(자동 보정) 확정 |
| R2 | 정리 | ✅ | `session.py` | 낮음 | `_default_unit` 제거, `unit_id` 필수화. resolver가 uid 반환 |
| R3 | 버그 | 💬 | `ew11_client.py` | 중간 | ACK가 유닛/seq와 무관 — 해결 시 예상 문제 선검토 필요 |
| R4 | 리팩토링 | 🔧 | `packet_builder.py`, `state_decoder.py`, `protocol.py` | 낮음 | 모드/풍량 enum 3중 정의 → 단일 진실원 |
| R5 | 리팩토링 | 🔧 | `packet_builder.py`, `ac_controller.py` | 중간 | 연동 필드 규칙 3중 **중복 및 구현 간 불일치** 정리 + D2(wire 명시) 확정 |
| R6 | 리팩토링 | 🔧 | `packet_builder.py`, `ac_controller.py` | 중간 | 개별 `build_set_*` 빌더를 배치 경로로 수렴 (R5 후행) |
| R7 | 최적화 | ✅ | `state_store.py` | 낮음 | 핫패스 `asdict` 재구성 → `replace`/얕은 복사 |
| R8 | 최적화 | ⏸ | `packet_parser.py` | 낮음 | `extract_packets` 잔여 버퍼 복사 — 보류 |
| N1 | 참고 | ⏸ | `ew11_client.py` | 낮음 | reconcile 이중 발화 — 보류 |
| N2 | 참고 | ⏸ | `*_loop` | 낮음 | 고정 sleep 드리프트 — 보류 |

**사용자 결정 사항 (2026-07-07 확정)**:
- **D1** (R1 부속) — **확정: 풍량 자동 보정.** `SET_MODE fanOnly` 진입 시 현재 풍량이 `auto`면 `low`로 보정하고, 모드+풍량을 `apply_settings` 한 패킷으로 전송(조작음 1회).
- **D2** (R5 부속) — **확정: 패킷에도 명시.** `wind_free=True` 패킷에 `long_wind=off` 코드 동봉(반대도 동일). desired와 wire 정렬. 실기기 수용 1회 확인을 구현 게이트로 유지.

---

## T0 — 리팩토링 선행 테스트 스캐폴드  🔧 (리뷰 반영 신규)

**근거.** 저장소에 `tests/` 디렉터리가 없다(확인: 2026-07-07). 본 계획의 검증 기준 다수가 "전후 동등성 비교"인데, 비교를 실행할 테스트 기반이 없으면 완료 조건이 선언에 그친다.

**제안.** 리팩토링 착수 전에 최소 단위 테스트를 추가한다(리뷰 권고 수용):
- `state_decoder`: mode/fan 코드 왕복, unknown fallback(`cool`/`auto`) 검증
- `packet_builder`: seq 제외 payload item 검증(R6 기준의 실행 수단)
- `state_store`: `get()` 반환 격리, desired override, settled 제거, 외부 전원 ON 시 pending 클리어
- `session`: `unit_id` 누락/unknown 구분, `SET_FAN` 가드(R1), (D1 확정 후) `SET_MODE fanOnly` 정책
- `ac_controller`: Mock/Real desired 상태 변화 동등성(R5 기준의 실행 수단)
- `ew11_client`: ACK timeout·late ACK·교차 유닛 ACK 재현(R3 구현 단계 진입 시)

**검증 기준.** 기준 커밋(`8e793ce`)에서 전부 통과하는 상태로 작성(현행 동작의 스냅샷 역할). 이후 각 R 항목은 해당 테스트의 전후 통과로 완료를 증명.

---

## R1 — SET_FAN 검증 가드가 동작하지 않음  ✅ 적용

**근거.** `session.py`, `_dispatch()` 내 `SET_FAN` 분기:
```python
if status.mode == "fan" and fan == "auto":
    return err_response(req.id, "fan mode auto is not allowed when mode=fan")
```

**문제 주장.** 모드 문자열은 코드 전체에서 `"fanOnly"`만 사용된다:
- `protocol.py`: `VALID_MODES = {"auto", "cool", "dry", "fanOnly"}`
- `state_decoder.py`: `_MODE_MAP = {0: "auto", 1: "cool", 2: "dry", 3: "fanOnly"}`

`"fan"` 리터럴은 이 비교 외에 어디에도 등장하지 않는다(`grep '"fan"'` 결과: `session.py`의 `p.get("fan")`와 본 비교뿐). 따라서 `status.mode == "fan"`은 **항상 거짓**이고, 송풍 모드에서 풍량 auto를 막으려던 가드는 죽어 있다.

**제안 변경.** 비교 대상을 `"fanOnly"`로 수정한다.
```python
if status.mode == "fanOnly" and fan == "auto":
```

**검증 기준.**
- 모드가 `fanOnly`인 상태에서 `SET_FAN {fan:"auto"}` → 에러 응답 반환.
- 모드가 `cool`인 상태에서 `SET_FAN {fan:"auto"}` → 정상 통과(기존 정상 케이스 회귀 없음).
- `grep -rn '"fan"' app/`에 송풍 모드를 뜻하는 다른 리터럴이 없음을 재확인.

**보완(리뷰 F3 반영).** `SET_FAN`만 막으면 invariant가 완전하지 않다 — 풍량이 `auto`인 상태에서 `SET_MODE {"mode":"fanOnly"}`를 호출하면 동일한 금지 조합이 만들어진다. 따라서:
- 가드 한 줄 수정(`"fan"`→`"fanOnly"`)은 그대로 진행한다(죽은 코드 소생, 무해).
- `SET_MODE fanOnly` 진입 경로: **D1 확정(2026-07-07) — 풍량 자동 보정.** 현재 풍량이 `auto`면 `low`로 보정하고, 모드+풍량을 `apply_settings` 한 패킷으로 전송한다(desired 갱신·조작음 1회 모두 배치 경로가 해결).

**리스크.** 가드 수정 자체는 없음. 자동 보정은 사용자가 명시하지 않은 풍량 변경이므로, 응답 데이터에 보정 사실을 포함할지 구현 시 검토(예: `{"fan_corrected": "low"}`).

---

## R2 — `_default_unit` 제거 및 `unit_id` 필수화  ✅ 적용

**근거.**
- `session.py` `__init__`: `self._default_unit = next(iter(controllers), None)`
- `_resolve_controller()`: `uid = params.get("unit_id", self._default_unit)`
- `_dispatch()`: `uid = p.get("unit_id", self._default_unit)` — **동일 계산이 한 번 더 중복**됨.

**결정 근거(사용자 확인).** 엣지 드라이버가 보내는 유닛 대상 명령은 **항상 `unit_id`를 포함**한다. 따라서 기본 유닛 fallback은 실제로 사용되지 않는 경로다. 또한 `_default_unit`은 세션 생성 시점에 `next(iter(controllers))`로 **고정 캡처**되어, auto-register보다 먼저 접속한 세션에서는 값이 `None`으로 굳는 잠재 결함까지 안고 있다 — 즉 존재 이유가 불분명하며 오히려 위험 요소다.

**제안 변경.**
1. `_default_unit` 필드와 두 곳의 fallback 사용을 제거.
2. `_resolve_controller()`의 반환형을 `(ctrl, uid, err)`로 변경(리뷰 F5 반영). `_dispatch()` 이후 로직(`STATUS` 응답의 `unit_id` 필드, `icool.status/start/stop/set_duration(uid, ...)`)이 resolved `uid`를 필요로 하므로, 중복 `uid` 계산을 제거하려면 resolver가 uid를 함께 반환해야 한다.
3. 에러 메시지 구분(리뷰 F5 반영): `unit_id` 자체가 없으면 `"missing required param: unit_id"`, 있으나 미등록 값이면 기존처럼 `"unknown unit_id: <uid>"`.

**유닛 비대상 명령 영향 분석.** 다음 명령은 `_resolve_controller`를 타지 않으므로 영향 없음:
- `PING`, `SUBSCRIBE`(hub), `LIST_UNITS`(controllers 순회), `STATUS_OUTDOOR`(outdoor_store).

**검증 기준.**
- `unit_id` 없는 유닛 대상 명령(STATUS/SET_* 등) → 명확한 에러 응답(정적 크래시·`None` 조회 없음).
- `unit_id` 포함 명령 → 기존과 동일 동작.
- 유닛 비대상 명령 4종 → 회귀 없음.
- **외부 의존 검증(교차 검증 agent 필수 확인)**: 엣지 드라이버 저장소에서 유닛 대상 명령이 예외 없이 `unit_id`를 채워 보내는지 확인. 이 계약이 깨지면 R2는 회귀를 유발하므로, 확인 전에는 병합 금지.

**리스크.** 엣지가 `unit_id`를 생략하는 경로가 하나라도 존재하면 회귀. → 위 외부 의존 검증이 게이트.

---

## R3 — ACK가 유닛/시퀀스와 무관하게 처리됨  💬 추가 논의

**근거.**
- `ew11_client.py`: `self._ack_event = asyncio.Event()` (단일 이벤트)
- `_handle_packet()`: `if pkt.msg_type == MSG_TYPE_ACK: self._ack_event.set()` — **출처 주소·seq 무검사**.
- `send_with_ack()`: 전송 직전 `_ack_event.clear()` 후 `wait_for(self._ack_event.wait(), timeout)`.
- reconcile 경로(`_reconcile`)는 `send()`(ACK 대기 없음)로 전송하되 `create_task`로 비동기 실행.

**문제 주장.** 전송은 `_send_lock`으로 직렬화되지만 **ACK 수신은 순서·출처 보장이 없다**. AC는 reconcile용 C013에도 C016을 돌려주므로, 그 ACK가 마침 다른 명령의 `send_with_ack` 대기창에 도착하면 **엉뚱한 명령의 ACK로 오인**되어 조기 성공 처리될 수 있다. 다중 유닛이 단일 EW11(공유 RS485)을 쓰므로 모든 유닛의 ACK가 같은 채널로 뒤섞여 들어온다.

**제안 방향(초안).** 전송 패킷의 seq와 수신 C016의 상관 필드를 대조하여, 일치하는 ACK만 대기 해제.

**⟶ 추가 논의: 해결 시 예상되는 문제점 (교차 검증 agent 검토 요청)**

seq 기반 상관을 구현하기 전에 다음이 선결되어야 한다. 이것이 본 항목을 💬(논의)로 남긴 이유다.

1. **[블로커] C016이 원 명령의 seq를 실어 오는가?**
   현재 `packet_parser.ParsedPacket`은 `seq`를 파싱하지만, 그 값이 *ACK가 응답하는 C013의 seq*인지 *ACK 자신의 독립 카운터*인지 코드만으로 알 수 없다. **실기기 패킷 캡처로 검증 필요.**
   - 실어 온다면 → seq 매칭이 깔끔하게 성립(참고: `packet_builder._seq`는 모듈 전역이라 유닛 간에도 seq가 유일 → 상관에 유리).
   - 실어 오지 않는다면 → seq 매칭 불가. 아래 대안 필요.

2. **[대안 A] 모든 전송을 ACK 대기 경로로 통일 — 완화책이며 완전 해결이 아님(리뷰 F4 반영).**
   reconcile의 fire-and-forget `send()`를 `send_with_ack`로 바꾸면 대기창 밖을 떠도는 ACK의 주요 출처는 사라진다. 그러나 **timeout으로 포기한 명령의 늦은 ACK**가 다음 `send_with_ack` 대기창에 도착하는 경로는 여전히 남으므로 오인 가능성을 완전히 제거하지 못한다. 또한 reconcile이 blocking·재시도를 타게 되어 타이밍과 버스 점유가 달라진다(주기 reconcile 지연 가능). 영향 평가 필요.

3. **[대안 B] 대기창 밖 ACK 폐기 + 창 진입 시 이벤트 배수(drain) — 역시 완화책.**
   `clear()`는 이미 하고 있으나, 창 진입 직전 잔여 ACK 상태를 확실히 비우고 창 종료 후 도착분은 무시. seq 정보가 없어도 오인 빈도를 낮출 수 있으나 **근본 해결은 아님**(경합창 잔존).

4. **다중 유닛 상관 정확성.**
   대안 A/B는 "어느 유닛의 ACK인가"를 구분하지 못한다. 유닛 A 명령 대기 중 유닛 B의 늦은 ACK가 오면 여전히 오인 가능. C016은 `ParsedPacket.src`(유닛 주소)를 가지므로 **src 매칭만으로도 교차 유닛 오인은 제거 가능**하나, 같은 유닛의 늦은 ACK 오인은 seq 상관 없이는 못 막는다. **정확한 해결은 `src/dst + seq` 매칭(1번)이 유일**하며, 1번 검증 결과가 이 항목의 실행 가능성을 좌우한다.

**결론(잠정).** R3는 **패킷 캡처로 C016↔C013 seq 상관을 먼저 확인**한 뒤 실행 여부·방식을 결정한다. 캡처 결과를 이 문서에 첨부하고 재검토한다. seq 상관이 불가능하면 대안 A/B는 "완화책"으로만 문서화한다(리뷰 F4 반영). 그 전까지 코드 변경 없음.

**검증 기준(구현 단계 진입 시).**
- reconcile ACK가 진행 중 `send_with_ack`를 조기 해제하지 못함을 재현 테스트로 확인.
- 유닛 A 대기 중 유닛 B ACK 주입 시 A가 해제되지 않음(src 또는 seq 매칭).
- **timeout 후 늦게 도착한 ACK가 다음 명령의 대기창을 해제하지 않음**(리뷰 F4 반영, late-ACK 재현 테스트).
- ACK 유실 시 기존 재시도(최대 3회) 동작 유지.

---

## R4 — 모드/풍량 enum 단일 진실원  🔧 리팩토링

**근거.** 동일 개념이 3개 파일에 독립 정의:
- `packet_builder.py`: `_MODE_CODE`, `_FAN_CODE` (name→code)
- `state_decoder.py`: `_MODE_MAP`, `_FAN_MAP` (code→name, 역방향)
- `protocol.py`: `VALID_MODES`, `VALID_FAN_MODES` (유효 집합)

**문제 주장.** 세 표현이 수동 동기화 상태다. 값 추가·변경 시 3곳을 함께 고쳐야 하며, 어긋나면 R1과 같은 부류의 버그가 발생한다.

**제안 변경.** `protocol.py`에 정방향 매핑 한 벌을 단일 정의하고 나머지를 파생:
```python
MODE_CODES = {"auto": 0, "cool": 1, "dry": 2, "fanOnly": 3}
FAN_CODES  = {"auto": 0, "low": 1, "medium": 2, "high": 3}
MODE_BY_CODE = {v: k for k, v in MODE_CODES.items()}
FAN_BY_CODE  = {v: k for k, v in FAN_CODES.items()}
VALID_MODES = set(MODE_CODES)
VALID_FAN_MODES = set(FAN_CODES)
```
`packet_builder`/`state_decoder`는 위를 import하여 사용.

**검증 기준.**
- 각 모드/풍량에 대해 `MODE_BY_CODE[MODE_CODES[m]] == m` 왕복 일치(전 항목).
- 리팩토링 전후 `decode_codes`·`build_set_mode`·`build_set_fan_mode` 출력이 동일(기존 값으로 회귀 테스트).
- `state_decoder`의 미지값 fallback(`mode`→`"cool"`, `fan`→`"auto"`) 동작 보존.
- import 순환 없음(`protocol`은 최하위 의존이어야 함).

**리스크.** 낮음. `protocol.py`가 `packet_builder`/`state_decoder`를 역으로 import하지 않도록 의존 방향만 준수.

---

## R5 — 연동 필드 규칙의 중복 및 구현 간 불일치 정리  🔧 리팩토링 (리뷰 F1 반영 재정의)

**근거 및 문제 주장(재정의).** 당초 "동일 규칙의 3중 중복"으로 기술했으나, 교차 검토(F1) 결과 **단순 중복이 아니라 구현 간 불일치**임이 확인되었다. 현재 동작 대조표(코드 `8e793ce` 기준, 켜는(on) 경로만):

| 진입점 | desired 기록 (Real) | 패킷에 실리는 코드 | Mock store 반영 |
|---|---|---|---|
| `set_vane(v, h)` (v or h) | vane=v,h + `wind_free=F` + `long_wind=F` | vane 2코드 + `0x4060=00`(wf off) + `0x4007=0E`(lw off) | vane + wf off + lw off ✅ 일치 |
| `set_wind_free(True)` | `wind_free=T` + **`long_wind=F`** + vane off | `0x4060=09` + vane off 2코드. **`long_wind` 코드 없음** ⚠️ | **`wind_free`만 갱신** ⚠️ 상호배타 없음 |
| `set_long_wind(True)` | `long_wind=T` + **`wind_free=F`** + vane off | `0x4007=10` + vane off 2코드. **`wind_free` 코드 없음** ⚠️ | **`long_wind`만 갱신** ⚠️ 상호배타 없음 |

불일치 2종:
1. **desired ↔ wire 불일치(Real)**: `set_wind_free(True)`는 desired에 `long_wind=False`를 기록하지만 패킷에는 해당 코드를 싣지 않는다(`set_long_wind`도 대칭). AC 펌웨어가 암묵 상호배타 처리를 하지 않으면 reported와 desired가 어긋난다. *완화 요인: 어긋나면 주기적 reconcile(5초)이 `long_wind=False`를 별도 패킷으로 보정하므로 지속 고착은 없다. 즉 사용자 가시 버그가 아니라 "펌웨어 암묵 동작 + 안전망에 의존하는 상태"다.*
2. **Mock ↔ Real 불일치**: Mock의 `set_wind_free`/`set_long_wind`는 상호배타 처리가 전혀 없어, mock 모드 테스트가 real 동작을 대표하지 못한다(테스트 충실도 결함).

**선결 결정 — D2 확정(2026-07-07): 패킷에도 명시.** 상호배타를 wire에 명시한다(`wind_free=True` 패킷에 `0x4007=0E` 동봉, `long_wind=True` 패킷에 `0x4060=00` 동봉). 근거: (a) desired와 wire가 정렬되어 펌웨어 암묵 동작 의존이 사라짐, (b) icool의 `apply_settings` 경로(`_wind_free_fields`)는 이미 이렇게 동작 중, (c) off 코드 동봉은 `build_set_vane`이 이미 하는 검증된 패턴. **구현 게이트: 실기기에서 off 코드 동봉 패킷의 수용을 1회 확인.**

**제안 변경.**
1. 연동 규칙을 단일 함수로 추출(`normalize_airflow(fields: dict) -> dict`, `protocol.py` 권장). D2에서 확정된 진리표를 구현.
2. 빌더·`RealAcController`·`MockAcController`·`apply_settings`가 이 함수를 공유 — Mock의 상호배타 누락도 이 시점에 함께 해소.

**검증 기준.**
- 진리표 기반 테스트: (vane_v, vane_h, wind_free, long_wind) 조합 입력 → 정규화 결과가 D2 확정 진리표와 일치.
- **Mock과 Real의 상태 변화 동등성**(리뷰 F1 반영): 동일 setter 시퀀스 후 Mock store 상태 == Real desired 상태.
- 리팩토링 전후 패킷 **payload item 목록** 비교(D2로 의도 변경된 코드 추가분 제외, seq 제외 — R6 기준과 동일 방식).
- icool 무풍↔강풍 전환 시 `_deviated` 오탐 없음(기존 통합 스모크 재실행).

**리스크.** 중간. D2가 wire behavior를 의도적으로 바꾸는 결정이므로 "동작 보존 리팩토링"이 아님을 명시하고, 실기기 확인을 게이트로 둔다. R6과 함께 진행하면 중복 작업 감소.

---

## R6 — 개별 빌더를 배치 경로로 수렴  🔧 리팩토링

**근거.** `packet_builder.py`의 `build_set_mode`/`build_set_fan_mode`/`build_set_target_temp`/`build_set_vane`/… 개별 빌더와 `build_reconcile`이 **동일 코드-값 매핑을 각자 보유**. 신규 `apply_settings`/`build_reconcile`은 이미 임의 필드셋을 한 패킷으로 만든다.

**문제 주장.** 코드-값 매핑 로직이 개별 빌더와 `build_reconcile`에 이중으로 존재하여 유지보수 지점이 분산.

**제안 변경.** `build_reconcile`을 "필드셋 → C013 패킷"의 **단일 매핑 지점**으로 삼고, 개별 `build_set_*`는 (필요하면) 이를 호출하는 얇은 래퍼로 축소하거나, 컨트롤러의 개별 `set_*`를 점진적으로 `apply_settings` 기반으로 재작성. R4(enum)·R5(연동 규칙) 완료를 전제로 진행.

**검증 기준(리뷰 F2 반영 — raw 바이트 동일성 기준 폐기).**
당초 "바이트 출력 동일" 기준은 성립 불가하다: `_seq`가 전송마다 증가하고 CRC에 포함되므로 동일 의미 패킷도 raw 바이트가 달라지며, 개별 빌더는 companion 코드를 동봉한다(아래 표). 다음으로 대체한다:
- **payload item 목록 동등성**: seq를 테스트에서 고정(또는 비교에서 제외)하고, `(code, value)` 쌍의 목록을 비교한다.
- **명령별 의미 동등성**: 래퍼가 `build_reconcile`에 넘겨야 하는 companion 필드를 명령별로 정의하고, 그 필드셋 기준으로 전후 동등성을 검증한다:

| 명령 | 주 필드 | companion 필드 (현행 유지 대상) |
|---|---|---|
| SET_POWER(on) | power | target_temp (on일 때 동봉) |
| SET_TEMP | target_temp | power (현재 상태 echo) |
| SET_MODE | mode | (없음) |
| SET_FAN | fan_mode | (없음) |
| SET_VANE | vane_v, vane_h | wind_free=off, long_wind=off (on일 때) |
| SET_WIND_FREE(on) | wind_free | vane 2축 off (+ D2 확정 시 long_wind=off) |
| SET_LONG_WIND(on) | long_wind | vane 2축 off (+ D2 확정 시 wind_free=off) |

- CRC·SIZE 정합: 생성 패킷을 기존 `extract_packets`로 왕복 파싱 성공.
- 기존 세션 명령(SET_MODE 등) 응답·부수효과 회귀 없음.

**리스크.** 중간. companion 필드 표가 곧 계약이므로 표 누락이 없는지 리뷰 필수. 순서: **R4 → R5(D2 확정 포함) → R6**.

---

## R7 — `state_store.get()` 핫패스 최적화  ✅ 적용

**근거.**
- `state_store.py` `StateStore.get()`: `result = AcStatus(**asdict(self._reported))`
- `OutdoorStore.get()`: `OutdoorStatus(**asdict(self._status))`

**문제 주장.** `asdict`는 재귀 딥카피 후 `**` 언팩·재생성으로 비용이 있다. 이 경로는 최다 호출 지점이다: `StreamHub._sweep`(초당 유닛 수만큼) + `IcoolManager._tick`(5초) + 모든 세션 명령. 평면 dataclass이므로 딥카피가 불필요하다.

**제안 변경.** `dataclasses.replace(self._reported)`(얕은 새 인스턴스)로 대체. `get()`은 reported 복사본에 desired override를 setattr하므로 원본 불변성 유지에 얕은 복사로 충분(필드가 모두 immutable 스칼라).
```python
from dataclasses import replace
...
result = replace(self._reported)
for k, v in self._desired.items():
    setattr(result, k, v)
```

**검증 기준.**
- `get()` 반환 객체가 `_reported`와 별개 인스턴스이고, 반환본 수정이 `_reported`에 영향 없음(격리 테스트).
- desired override 결과가 기존과 동일.
- 필드가 모두 스칼라(bool/str/float/int/None)임을 `AcStatus`/`OutdoorStatus` 정의로 확인(가변 필드 추가 시 얕은 복사 안전성 재검토 필요 — 주석 명시).

**리스크.** 낮음. 향후 dataclass에 가변 필드(list/dict) 추가 시 얕은 복사가 공유 참조를 만들 수 있음 → 코드에 주석으로 전제 명시.

---

## R8 — `extract_packets` 잔여 버퍼 복사  ⏸ 보류

**근거.** `packet_parser.extract_packets`: `return packets, bytearray(buf[i:])`.

**문제 주장.** 매 호출마다 남은 바이트를 통째 복사. 부분 패킷이 선두에 걸리면 전체 복사 후 다음 청크에서 재파싱.

**결정.** **보류.** 현재 패킷 크기·트래픽에서 실측 영향 미미. 트래픽 급증 시 `del buf[:i]` 방식으로 재검토.

---

## 참고(보류) 항목

### N1 — reconcile 이중 발화  ⏸ 보류
C014 수신 트리거(`_handle_packet`)와 5초 주기 루프(`_periodic_reconcile_loop`)가 겹치면 동일 diffs로 reconcile 태스크가 중복 생성될 수 있음(중복 가드 없음). 내용 동일이라 상태 무해, 다만 조작음 1회 추가 가능. **보류.**

### N2 — 고정 sleep 드리프트  ⏸ 보류
`run_loop`/`_periodic_reconcile_loop`/`_sweep`의 `sleep(간격)`이 처리시간을 무시하여 미세 드리프트. 기능 영향 없음. **보류.**

---

## 실행 순서 권고 (v1.1 갱신)

0. **0차(선행)**: T0 테스트 스캐폴드 — 기준 커밋에서 전부 통과 상태로 작성.
1. **1차(저위험·독립)**: R1(가드 수정 + D1 자동 보정), R2*, R7. (*R2는 엣지 드라이버 `unit_id` 계약 확인 후)
2. **2차(구조, 순서 의존)**: R4 → R5(D2: wire 명시, 실기기 수용 확인 게이트) → R6.
3. **선결 조사**: R3 — 실기기 C016 패킷 캡처로 seq 상관 확인 후 재검토.
4. **보류**: R8, N1, N2.
5. ~~사용자 결정 대기~~ → D1·D2 모두 확정됨(2026-07-07, 요약 표 아래 결정 사항 참조).

## 완료 정의(DoD)

- 각 실행 항목의 "검증 기준"을 통과(T0 테스트로 실행).
- 기존 icool 통합 스모크(강풍/무풍 전환, `_deviated` 정합, 시작 단계 결정) 재실행 통과.
- 리팩토링 항목은 **payload item·상태 동등성**을 전후 대조(동작 불변 증명). 단 D1·D2로 의도 변경되는 부분은 "의도된 변경 목록"으로 별도 명시.

---

## 부록 A — 교차 검토(REFACTOR_PLAN_REVIEW.md) 회신 내역 (v1.1)

| 리뷰 | 판정 | 반영 내용 |
|------|------|-----------|
| F1 (R5 재정의) | **수용** | R5를 "중복 및 구현 간 불일치 정리"로 재정의, 현재 동작 대조표 수록, Mock/Real 동등성 기준 추가, D2 결정 항목 신설. *부분 이견: desired↔wire 불일치는 주기적 reconcile 안전망이 5초 내 보정하므로 사용자 가시 고착 버그는 아님 — 심각도 서술에 완화 요인으로 명시함. 재정의 필요성 자체에는 동의.* |
| F2 (R6 검증 기준) | **수용** | raw 바이트 동일성 기준 폐기. seq 고정/제외 + payload item 목록 비교 + 명령별 companion 필드 표로 대체. |
| F3 (R1 invariant 불완전) | **수용** | `SET_MODE fanOnly` 경로 보완을 R1에 추가하되, 스펙 확정·정책 선택은 D1로 분리(사용자 결정 대기). 가드 한 줄 수정은 독립 진행. |
| F4 (R3 대안 불완전) | **수용(부분 정정 포함)** | 대안 A의 "오인 자체가 성립하지 않게 된다"는 과잉 서술이었음 — timeout 후 late ACK 경로가 남는다는 지적이 맞아 정정. late-ACK 재현 테스트를 검증 기준에 추가. src 매칭으로 교차 유닛 오인은 제거 가능하다는 세부를 보강. *참고: 원 계획도 "정확한 해결은 seq 매칭이 유일"로 이미 명시했으므로 '정확한 해결로 표현하지 말라'는 권고는 대안 A 서술에만 해당.* |
| F5 (R2 uid 반환) | **수용** | `_resolve_controller()` 반환형 `(ctrl, uid, err)` 및 에러 메시지 구분(missing/unknown)을 제안 변경에 명시. |
| 테스트 보강 | **수용** | T0 항목 신설, 실행 순서 0차로 배치. |

**반박/기각 사항: 없음.** 리뷰의 사실 주장은 전수 코드 대조로 확인되었으며 오류가 발견되지 않았다. 위 표의 이탤릭 두 건은 기각이 아니라 서술 정밀화다.
