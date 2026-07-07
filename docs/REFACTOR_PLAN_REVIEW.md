# `app/` 리팩토링 계획 검토 의견

| 항목 | 값 |
|---|---|
| 대상 문서 | `docs/REFACTOR_PLAN.md` |
| 대상 코드 | `app/` |
| 기준 커밋 | `8e793ce` |
| 검토일 | 2026-07-07 |
| 검토 목적 | 리팩토링 계획의 근거, 문제 주장, 검증 기준이 현재 코드와 일치하는지 확인하고 구현 전 보완 사항을 명시 |

---

## 종합 의견

리팩토링 계획의 큰 방향은 타당하다. R1, R2, R4, R7은 현재 코드에서 근거가 확인되며, 작은 단위로 진행 가능한 항목이다. 다만 R5와 R6은 현재 계획대로 진행하면 "동작 보존 리팩토링"이 아니라 wire behavior 변경으로 이어질 수 있다. 따라서 R5/R6은 구현 전에 현재 패킷 출력과 desired 상태의 차이를 명시적으로 정리하고, 변경 의도 여부를 확정해야 한다.

또한 현재 저장소에는 `tests/` 디렉터리가 없다. 계획서의 검증 기준을 실제 완료 조건으로 삼으려면 최소한 `packet_builder`, `state_decoder`, `state_store`, `session`에 대한 단위 테스트를 먼저 추가해야 한다.

---

## 주요 보완 필요 사항

### F1. R5는 "중복 제거"가 아니라 "동작 차이 정리" 항목으로 재정의 필요

**관련 계획 항목:** R5  
**관련 코드:** `app/packet_builder.py`, `app/ac_controller.py`

계획서는 vane, wind_free, long_wind 상호배타 규칙이 3곳에 중복되어 있다고 설명한다. 그러나 현재 코드는 단순 중복 상태가 아니라 구현 간 차이가 있다.

- `packet_builder.build_set_vane()`은 vane이 켜질 때 `wind_free=False`, `long_wind=False`에 해당하는 코드를 함께 보낸다.
- `packet_builder.build_set_wind_free()`는 `wind_free=True`일 때 vane 두 축을 끄지만, `long_wind=False` 코드는 보내지 않는다.
- `packet_builder.build_set_long_wind()`는 `long_wind=True`일 때 vane 두 축을 끄지만, `wind_free=False` 코드는 보내지 않는다.
- `RealAcController.set_wind_free()`와 `set_long_wind()`는 desired 상태에서는 서로를 끄도록 기록한다.
- `MockAcController.set_wind_free()`와 `set_long_wind()`는 해당 상호배타 처리를 하지 않는다.

따라서 R5는 "동일 규칙의 중복 제거"로만 처리하면 안 된다. 현재 차이가 의도된 동작인지, AC 펌웨어가 암묵적으로 상호배타 처리를 하는지, 아니면 실제 버그인지 먼저 확정해야 한다.

**권고 수정:**

1. R5의 문제 주장을 "상호배타 규칙의 중복 및 구현 간 불일치"로 변경한다.
2. 정규화 함수 도입 전에 현재 setter별 desired 변경과 packet item 목록을 표로 작성한다.
3. `MockAcController`와 `RealAcController`의 상태 변화 동등성을 검증 기준에 추가한다.
4. `wind_free=True` 시 `long_wind=False`를 실제 패킷에 추가할지, `long_wind=True` 시 `wind_free=False`를 실제 패킷에 추가할지 명시적으로 결정한다.

---

### F2. R6의 byte 출력 동일성 검증 기준은 현재 구조와 맞지 않음

**관련 계획 항목:** R6  
**관련 코드:** `app/packet_builder.py`

계획서는 모든 단일 필드에 대해 `build_set_X(v)`와 `build_reconcile({X: v})`의 byte 출력이 동일해야 한다고 제안한다. 그러나 이 기준은 현재 코드 기준으로 그대로 성립할 수 없다.

주요 이유는 다음과 같다.

- `_seq`가 패킷 생성마다 증가하며 CRC 계산에 포함된다. 따라서 동일 의미의 패킷도 raw byte는 달라질 수 있다.
- `build_set_target_temp()`는 target temperature 외에 power code도 함께 보낸다.
- `build_set_vane()`은 vane code 외에 `wind_free=False`, `long_wind=False` code를 함께 보낼 수 있다.
- `build_set_power(on=True, target_temp=...)`는 optional target temperature를 포함할 수 있다.
- `build_reconcile({"target_temp": v})`는 현재 target temperature code만 만든다.

**권고 수정:**

1. raw byte 전체 동일성 대신 seq를 고정하거나 packet payload item 목록 기준으로 비교한다.
2. 단일 필드별 비교가 아니라 "명령별 의미 동등성"으로 검증 기준을 바꾼다.
3. 각 wrapper가 `build_reconcile()`에 넘겨야 하는 companion field를 명령별로 정의한다.
4. R6은 R5에서 상호배타 규칙을 확정한 뒤 진행한다.

---

### F3. R1은 `SET_FAN`만 수정하면 invariant가 완전히 보장되지 않음

**관련 계획 항목:** R1  
**관련 코드:** `app/session.py`

`SET_FAN` 분기의 `"fan"` 비교는 실제로 죽은 가드이며 `"fanOnly"`로 수정해야 한다. 이 주장은 현재 코드에서 확인된다.

다만 "fanOnly 모드에서 fan auto 금지"가 실제 invariant라면 `SET_FAN`만 막는 것으로는 충분하지 않다. 현재 fan mode가 `auto`인 상태에서 `SET_MODE {"mode":"fanOnly"}`를 호출하면 동일한 금지 조합이 만들어질 수 있다.

**권고 수정:**

1. 제품 스펙상 `fanOnly + fan auto`가 금지인지 확정한다.
2. 금지 조합이 맞다면 `SET_MODE fanOnly` 진입 시 현재 fan mode가 `auto`인 경우의 정책을 정한다.
3. 가능한 정책은 에러 반환 또는 fan mode 자동 보정이다. 자동 보정을 선택하면 실제 전송 패킷과 desired 상태 갱신 순서를 별도로 설계해야 한다.

---

### F4. R3의 대안 A/B는 ACK 오인 가능성을 완전히 제거하지 못함

**관련 계획 항목:** R3  
**관련 코드:** `app/ew11_client.py`, `app/packet_parser.py`

단일 `_ack_event`가 모든 C016 ACK에 의해 set되는 구조이므로, ACK가 유닛 또는 seq와 상관되지 않는다는 문제 주장은 타당하다.

다만 계획서의 대안 A("모든 전송을 ACK 대기 경로로 통일")와 대안 B("대기창 밖 ACK 폐기")는 문제를 완전히 해결하지 못한다. ACK timeout 이후 늦게 도착한 ACK가 다음 `send_with_ack()`의 대기창에 들어오면 여전히 조기 성공 처리될 수 있다. 또한 다중 유닛 환경에서는 다른 유닛의 ACK가 현재 명령의 ACK로 오인될 수 있다.

**권고 수정:**

1. C016의 `seq`가 원 C013의 seq인지 실기기 캡처로 먼저 확인한다.
2. seq 상관이 확인되면 `src/dst + seq` 기준으로 ACK를 매칭한다.
3. seq 상관이 불가능한 경우, 대안 A/B는 완화책으로만 문서화하고 "정확한 해결"로 표현하지 않는다.
4. timeout 후 늦은 ACK가 다음 명령을 해제하지 않는 재현 테스트를 검증 기준에 추가한다.

---

### F5. R2 구현 시 `_resolve_controller()`가 `unit_id`를 반환해야 함

**관련 계획 항목:** R2  
**관련 코드:** `app/session.py`

`_default_unit` 제거 및 `unit_id` 필수화 방향은 타당하다. 특히 auto-register 전에 생성된 세션에서 `_default_unit`이 `None`으로 고정될 수 있다는 분석도 현재 구조와 맞다.

다만 `_dispatch()`의 중복 `uid` 계산을 제거하면 이후 로직에서 사용할 `uid`를 보존해야 한다. 현재 `STATUS` 응답, `icool.status(uid)`, `icool.start(uid, ...)`, `icool.stop(uid)`, `icool.set_duration(uid, ...)`는 resolved `unit_id`를 필요로 한다.

**권고 수정:**

1. `_resolve_controller()` 반환형을 `(ctrl, uid, err)` 형태로 변경하는 방안을 계획에 명시한다.
2. `unit_id`가 없는 유닛 대상 명령은 `"missing required param: unit_id"`를 반환하도록 한다.
3. `unit_id`가 알 수 없는 값인 경우는 기존처럼 `"unknown unit_id: <uid>"`를 반환하도록 구분한다.

---

## 항목별 검토 결과

| ID | 검토 결과 | 의견 |
|----|-----------|------|
| R1 | 수정 필요 | 죽은 가드 수정은 타당하나 `SET_MODE fanOnly` 경로까지 검토 필요 |
| R2 | 보완 후 진행 | 방향은 타당하나 `_resolve_controller()`가 resolved `uid`를 반환해야 함 |
| R3 | 선결 조사 필요 | C016 seq 의미 확인 전 구현 보류가 맞음. 대안 A/B는 완화책으로만 취급 |
| R4 | 진행 가능 | enum 단일 진실원 방향 타당. import 방향만 주의 |
| R5 | 재정의 필요 | 중복 제거가 아니라 구현 간 불일치 정리 항목으로 보아야 함 |
| R6 | R5 이후 재작성 | raw byte 동일성 기준 부적절. payload item/의미 동등성 기준 필요 |
| R7 | 진행 가능 | `replace()` 적용 방향 타당. dataclass 필드가 스칼라라는 전제 주석 권장 |
| R8 | 보류 타당 | 현재 트래픽 규모에서는 우선순위 낮음 |
| N1 | 보류 가능 | 기능 무해 주장 가능하나 조작음 중복이 사용자 경험에 영향 있으면 재평가 |
| N2 | 보류 가능 | 기능 영향 낮음 |

---

## 권고 실행 순서

1. R1, R2, R7을 1차로 진행하되 R1은 `SET_MODE fanOnly` 정책을 함께 결정한다.
2. R4를 적용해 enum 정의를 단일화한다.
3. R5를 먼저 "현재 동작 표 작성 및 정책 결정" 단계로 수행한다.
4. R5 정책이 확정된 뒤 R6의 wrapper 수렴 작업을 진행한다.
5. R3는 실기기 C016 캡처 결과를 문서에 첨부한 뒤 별도 설계로 진행한다.

---

## 테스트 보강 권고

현재 저장소에는 테스트 디렉터리가 없으므로, 다음 테스트를 추가한 뒤 리팩토링을 진행하는 것이 안전하다.

- `state_decoder`: mode/fan code 왕복 및 unknown fallback 검증
- `packet_builder`: seq를 제외한 payload item 검증
- `state_store`: `get()` 반환 객체 격리, desired override, settled desired 제거 검증
- `session`: `unit_id` 누락/unknown, `SET_FAN`, `SET_MODE fanOnly` 정책 검증
- `ac_controller`: mock/real desired 상태 변화 동등성 검증
- `ew11_client`: ACK timeout, late ACK, cross-unit ACK 오인 재현 테스트

