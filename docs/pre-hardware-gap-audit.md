# Pre-hardware Gap Audit

## 목적과 기준

이 문서는 Poppy-Agent `origin/develop` (`8ec2ac232f1664acedfe4c3bc5b0dbdb18baf9e8`)의
Physical Readiness blocker를 현재 코드, 테스트, 운영 문서 evidence로 재감사한 결과다.
이 감사의 `RESOLVED`는 물리 실행 승인을 뜻하지 않는다. 실제 장비 검증과 책임자 승인이
끝나기 전까지 Physical Readiness는 `BLOCKED`이며 `NOT READY FOR PHYSICAL EXECUTION`이다.

분류는 다음 의미를 사용한다.

- `RESOLVED`: 현재 범위의 software/contract 요구가 evidence로 충족됨.
- `PARTIALLY_RESOLVED`: software 경계는 구현됐지만 물리 또는 승인 evidence가 남음.
- `UNRESOLVED`: 추가 software 구현 또는 명시적 contract가 필요함.
- `REQUIRES_HARDWARE`: 실제 장비 evidence 없이는 판단할 수 없음.
- `REQUIRES_OWNER_APPROVAL`: 장비 소유자·운영 책임자의 결정 또는 승인이 필요함.

## Blocker matrix

| Blocker | Status | Current evidence | Remaining gap | Next issue |
| --- | --- | --- | --- | --- |
| `PHYSICAL_EXECUTION_DISABLED` | `PARTIALLY_RESOLVED` | `PhysicalReadinessEvaluator`와 `PhysicalExecutionGate`가 enable flag와 모든 evidence를 함께 검사하며, 기본 flag는 `false`다. `tests/test_physical_readiness.py`가 flag만으로 gate를 통과할 수 없음을 검증한다. | 비활성화는 의도된 안전 상태다. 물리 실행을 안전하게 활성화할 근거는 아직 없다. | #76, #77, #78 순차 검토 |
| `REAL_COMMAND_CLIENT_MISSING` | `RESOLVED` | `src/poppy_agent/hardware/unitree_sdk.py`에 optional lazy `UnitreeSdkCommandClient` adapter와 공식 `SportClient` factory seam이 있다. `tests/test_unitree_sdk.py`가 SDK double lifecycle, posture/status mapping, unavailable/error 처리를 검증하고 `tests/test_main.py`가 blocked Unitree startup을 검증한다. | readiness evidence는 여전히 explicit input이며, SDK 설치·실제 장비 검증·물리 enablement는 남아 있다. | #77, #78 |
| `PRODUCTION_MOTION_PROFILE_UNAPPROVED` | `REQUIRES_OWNER_APPROVAL` | `MotionProfile`은 명시적으로 주입되는 test planning 값이고 production default가 없다. `tests/test_motion_strategy.py`는 deterministic planning만 검증한다. | 실제 운영 profile, 속도·가감속·완료 semantics의 authoritative 결정과 승인 필요. | #76, #78 |
| `PHYSICAL_LIMITS_UNDEFINED` | `REQUIRES_OWNER_APPROVAL` | safety/readiness 문서가 거리·속도·각도·가속·제동·배터리·장애물·토크·latency 값을 `TBD`로 유지한다. 코드에는 이를 production limit로 가장하는 default가 없다. | 장비·제품 source 기반의 제한값과 승인 필요. | #78 |
| `PRESET_POLICY_UNDEFINED` | `REQUIRES_OWNER_APPROVAL` | `ExecutionSafetyValidator`와 Unitree backend는 명시적 allow-list가 없으면 PRESET을 fail-closed한다. Fake trace는 policy evidence로 취급하지 않는다. | allow-list, mapping, unsupported 동작의 정책 결정과 승인 필요. | #77, #78 |
| `EMERGENCY_PROCEDURE_UNCONFIRMED` | `REQUIRES_OWNER_APPROVAL` | 문서가 Program STOP, Execution Cancellation, Administrative Stop, Physical Emergency Stop을 분리하며 physical E-stop을 구현·시뮬레이션하지 않는다. | 실제 장비·운영자의 emergency procedure와 책임 확인 필요. | #78 |
| `TELEMETRY_REQUIREMENTS_UNMET` | `PARTIALLY_RESOLVED` | `MockRobotAdapter`와 `UnitreeGo2Adapter`가 Robot identity/status/capabilities 경계를 제공하고, Unitree adapter는 `rt/lowstate` read-only 구독과 명시적 `UNAVAILABLE`/`None` 값을 사용한다. | 실제 hardware telemetry의 의미·품질·threshold와 enablement evidence가 없음. | #77, #78 |
| `OBSERVABILITY_REQUIREMENTS_UNMET` | `PARTIALLY_RESOLVED` | structured lifecycle/transport/recovery logging, connectivity state, execution ownership, operational snapshot과 atomic status publication이 구현됐다. 관련 observability·operational status 테스트가 이를 검증한다. | 물리 검증 중 필요한 관찰 항목의 현장 적합성·책임자 검토와 hardware evidence가 남음. | #77, #78 |
| `EQUIPMENT_OWNER_APPROVAL_MISSING` | `REQUIRES_OWNER_APPROVAL` | `physical-readiness.md`는 limits, stop responsibility, operating policy, validation evidence가 responsible owner/operator 승인을 필요로 한다고 명시한다. 저장소에는 승인 자료가 없다. | 장비 소유자와 supervising operator의 실제 승인 필요. | #78 |
| `HARDWARE_VALIDATION_NOT_COMPLETED` | `REQUIRES_HARDWARE` | readiness 문서와 Unitree 문서가 hardware validation status를 `NOT TESTED ON HARDWARE`로 명시한다. 현재 adapter/command backend 테스트는 fake SDK·in-memory double만 사용한다. | controlled hardware validation과 evidence 기록 필요. | #78 |

## Evidence 해석

`PhysicalReadinessEvidence`의 boolean은 승인된 evidence를 주입하기 위한 입력이며,
현재 저장소가 실제 evidence를 보유한다는 뜻이 아니다. 모든 기본값은 보수적으로
미충족이고, evaluator는 `PhysicalExecutionReadiness.BLOCKED`와 ordered blocker tuple을
반환한다. synthetic complete evidence를 평가하는 단위 테스트는 evaluator의 결정성을
검증할 뿐 실제 승인이나 hardware validation을 대체하지 않는다.

Fake hardware backend, Fake Unitree client, `RecordingSleeper`, test-only `MotionProfile`은
command boundary와 계획 계산을 검증하는 software test double이다. 이들은 실제 SDK,
SportClient, DDS publisher, Robot network 또는 physical movement를 사용하지 않는다.
`UnitreeGo2Adapter` 역시 `rt/lowstate` read-only telemetry 경계이며 command publisher나
physical command client가 아니다.

Operational readiness는 별도 개념이다. Agent operational snapshot의 `READY` 또는
`operationalReady=true`는 Server와의 software 협업 상태만 의미하며 Physical Readiness를
승격하지 않는다.

## Roadmap 정합성

- #76은 real command client와 gate 뒤의 production adapter 경계가 대상이다. 실제 GO2
  연결과 physical execution은 제외되어 있다.
- #77은 #76 이후 fake/recording transport를 이용한 software-only preflight와 fail-closed
  rehearsal이 대상이다.
- #78은 owner approval, limits, emergency procedure, telemetry/observability evidence,
  controlled hardware validation 계획을 문서화하는 대상이다. 문서 완료가 hardware 승인이나
  실제 검증 완료를 의미하지 않는다.

따라서 #76 완료로 real command client software boundary만 `RESOLVED`로 갱신한다.
나머지 물리 실행 전제 조건은 해제하지 않는다. 이 PR에서는 #77~#78과 중복되는 새
Issue를 만들지 않았고, Issue body도 변경하지 않았다.

## 안전 경계

이번 감사와 evidence 수집은 software-only다. Physical Readiness는 계속 `BLOCKED`다.
actual GO2, SportClient, DDS command publisher, physical movement, physical emergency stop,
hardware network 접속은 수행하지 않는다.
