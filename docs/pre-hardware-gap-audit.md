# Pre-hardware Gap Audit

## 목적과 기준

이 문서는 Poppy-Agent의 Physical Readiness blocker를 코드, 테스트, 운영 문서
evidence로 재감사한 결과다. 최초 감사 기준은
`8ec2ac232f1664acedfe4c3bc5b0dbdb18baf9e8`이며, 이전 검토 기준은
`acba96d34b010db8b1515cc6d48a3ea81f525a31`이다. 이번 evidence collection
snapshot의 Agent 기준은 `c1bdbe5c82fa245916e4519225023fb89279dc63`
(`origin/develop`)이고, Poppy-Server 기준은
`3951e51dfe453dc215d6eeb190997235b3aeaabb`이다.
이 SHA들은 audit 당시의 고정 snapshot이다. 후속 커밋으로 develop이 이동하면
current software 상태를 뜻하지 않으므로 validation 직전에 latest SHA를 다시 확인한다.
이 감사의 `RESOLVED`는 물리 실행 승인을 뜻하지 않는다. 실제 장비 검증과 책임자 승인이
끝나기 전까지 Physical Readiness는 `BLOCKED`이며 `NOT READY FOR PHYSICAL EXECUTION`이다.

분류는 다음 의미를 사용한다.

- `RESOLVED`: 현재 범위의 software/contract 요구가 evidence로 충족됨.
- `PARTIALLY_RESOLVED`: software 경계는 구현됐지만 물리 또는 승인 evidence가 남음.
- `UNRESOLVED`: 추가 software 구현 또는 명시적 contract가 필요함.
- `REQUIRES_HARDWARE`: 실제 장비 evidence 없이는 판단할 수 없음.
- `REQUIRES_OWNER_APPROVAL`: 장비 소유자·운영 책임자의 결정 또는 승인이 필요함.

## Runtime Evidence and Deployment Baseline

실제 Ubuntu systemd runtime에서 다음 Unitree SDK evidence를 확인했다.

- distribution: `unitree_sdk2py 1.0.1`
- checkout: `/home/poppy/poppy/unitree_sdk2_python`
- remote: `https://github.com/unitreerobotics/unitree_sdk2_python.git`
- base commit: `65691c8a8bc53b98d3976dba4dbf9d5d20b2e7f5`
- `describe`: `65691c8-dirty`
- editable install: `YES`
- runtime linkage: `CONFIRMED_RUNTIME_SDK`
- dirty file: `unitree_sdk2py/test/lowlevel/read_lowstate.py`
- dirty diff: telemetry helper NIC 이름 `enp2s0` → `enp3s0`, 총 2줄 변경
- production runtime library affected: `NO`
- runtime import path affected: `NO`
- dirty patch SHA256: `087ffbeb362f8453397484d0205c1bf8719c7322ad94a6e9992a19ae80f4205d`
- exact evidence classification: `PROVIDED_WITH_DIRTY_NON_RUNTIME_HELPER`
- CycloneDDS runtime distribution: `0.10.2`

사용자가 제공한 실제 device evidence는 `Unitree GO2 EDU`, Robot Software Version
`V1.0.24`, Hardware Version `V1.0`, SN verified/redacted이다. `V1.0.24`는 화면의
`Software Version` label이며 Firmware Version으로 재명명하지 않는다. Firmware exact
version은 `MISSING`으로 유지한다.

`/etc/poppy-agent/poppy-agent.env`는 존재하며 `root:root`, mode `600`이지만, 이번
evidence run에서 내용은 확인하지 못했다. 실제 mode, Robot UUID, model/edition,
firmware, SDK metadata, physical execution flag는 `UNAVAILABLE`이다. example 파일의
값은 운영 runtime evidence로 사용하지 않는다.

실제 deployed Agent는 evidence collection 당시 Agent develop snapshot보다
`d6fc2f1acab258c200583f1fc946a44eea29fb42`이며 53 commits behind, 0 commits
ahead였다. deployed Agent에는 evidence collection 당시 develop의
`PhysicalExecutionGate`, `UnitreeSdkCommandClient`, physical execution preflight,
hardware validation plan, PRESET fail-closed, current MOVE/TURN mapper boundary 및
physical execution default-disabled gate가 없다.

따라서 deployed Agent 상태는
`STALE / NOT REPRESENTATIVE OF CURRENT_DEVELOP / NOT ELIGIBLE FOR CURRENT HARDWARE
VALIDATION`으로 기록한다. 이 판정은 deployment update를 수행하거나 승인하는 의미가
아니다.

## Blocker matrix

| Blocker | Status | Current evidence | Remaining gap | Next issue |
| --- | --- | --- | --- | --- |
| `PHYSICAL_EXECUTION_DISABLED` | `PARTIALLY_RESOLVED` | `PhysicalReadinessEvaluator`와 `PhysicalExecutionGate`가 enable flag와 모든 evidence를 함께 검사하며, 기본 flag는 `false`다. `tests/test_physical_readiness.py`가 flag만으로 gate를 통과할 수 없음을 검증한다. | 비활성화는 의도된 안전 상태다. 물리 실행을 안전하게 활성화할 근거는 아직 없다. | #78 |
| `REAL_COMMAND_CLIENT_MISSING` | `RESOLVED` | `src/poppy_agent/hardware/unitree_sdk.py`에 optional lazy `UnitreeSdkCommandClient` adapter와 공식 `SportClient` factory seam이 있다. `tests/test_unitree_sdk.py`가 SDK double lifecycle, posture/status mapping, unavailable/error 처리를 검증하고 `tests/test_main.py`가 blocked Unitree startup을 검증한다. #77 preflight가 gate 이후 injected recording 경로와 실제 factory 미호출을 추가로 검증한다. | readiness evidence는 여전히 explicit input이며, SDK 설치·실제 장비 검증·물리 enablement는 남아 있다. | #78 |
| `PRODUCTION_MOTION_PROFILE_UNAPPROVED` | `REQUIRES_OWNER_APPROVAL` | `MotionProfile`은 명시적으로 주입되는 test planning 값이고 production default가 없다. `tests/test_motion_strategy.py`와 #77 preflight는 deterministic test-only planning만 검증한다. | 실제 운영 profile, 속도·가감속·완료 semantics의 authoritative 결정과 승인 필요. | #78 |
| `PHYSICAL_LIMITS_UNDEFINED` | `REQUIRES_OWNER_APPROVAL` | safety/readiness 문서가 거리·속도·각도·가속·제동·배터리·장애물·토크·latency 값을 `TBD`로 유지한다. 코드에는 이를 production limit로 가장하는 default가 없다. | 장비·제품 source 기반의 제한값과 승인 필요. | #78 |
| `PRESET_POLICY_UNDEFINED` | `REQUIRES_OWNER_APPROVAL` | `ExecutionSafetyValidator`와 Unitree backend는 명시적 allow-list가 없으면 PRESET을 fail-closed한다. #77 preflight가 recording dispatch 0을 검증한다. Fake trace는 policy evidence로 취급하지 않는다. | allow-list, mapping, unsupported 동작의 정책 결정과 승인 필요. | #78 |
| `EMERGENCY_PROCEDURE_UNCONFIRMED` | `REQUIRES_OWNER_APPROVAL` | 문서가 Program STOP, Execution Cancellation, Administrative Stop, Physical Emergency Stop을 분리하며 physical E-stop을 구현·시뮬레이션하지 않는다. | 실제 장비·운영자의 emergency procedure와 책임 확인 필요. | #78 |
| `TELEMETRY_REQUIREMENTS_UNMET` | `PARTIALLY_RESOLVED` | `MockRobotAdapter`와 `UnitreeGo2Adapter`가 Robot identity/status/capabilities 경계를 제공하고, Unitree adapter는 `rt/lowstate` read-only 구독과 명시적 `UNAVAILABLE`/`None` 값을 사용한다. #77은 software-only connectivity/reconciliation 관찰을 추가로 검증한다. | 실제 hardware telemetry의 의미·품질·threshold와 enablement evidence가 없음. | #78 |
| `OBSERVABILITY_REQUIREMENTS_UNMET` | `PARTIALLY_RESOLVED` | structured lifecycle/transport/recovery logging, connectivity state, execution ownership, operational snapshot과 atomic status publication이 구현됐다. 관련 observability·operational status 테스트와 #77 preflight가 blocked reason, cancellation, disconnect/reconciliation, disable 상태를 검증한다. | 물리 검증 중 필요한 관찰 항목의 현장 적합성·책임자 검토와 hardware evidence가 남음. | #78 |
| `EQUIPMENT_OWNER_APPROVAL_MISSING` | `REQUIRES_OWNER_APPROVAL` | `physical-readiness.md`는 limits, stop responsibility, operating policy, validation evidence가 responsible owner/operator 승인을 필요로 한다고 명시한다. 저장소에는 승인 자료가 없다. | 장비 소유자와 supervising operator의 실제 승인 필요. | #78 |
| `HARDWARE_VALIDATION_NOT_COMPLETED` | `REQUIRES_HARDWARE` | readiness 문서와 Unitree 문서가 hardware validation status를 `NOT TESTED ON HARDWARE`로 명시한다. 현재 adapter/command backend 테스트는 fake SDK·in-memory double만 사용한다. | controlled hardware validation과 evidence 기록 필요. | #78 |
| `SDK_EXACT_RUNTIME_VERSION` | `RESOLVED` | 실제 runtime distribution `unitree_sdk2py 1.0.1`, base commit `65691c8...`, editable linkage 및 patch fingerprint가 확인됐다. checkout은 non-runtime telemetry helper만 dirty하다. | current deployment는 stale하므로 이 SDK evidence를 current develop physical-readiness baseline으로 해석하지 않는다. | 별도 deployment issue |
| `CYCLONEDDS_RUNTIME_VERSION` | `RESOLVED` | runtime venv의 별도 CycloneDDS distribution `0.10.2`가 확인됐다. | Unitree SDK version과 혼동하지 않는다. | 없음 |
| `GO2_DEVICE_IDENTITY` | `PARTIALLY_RESOLVED` | 사용자 제공 device evidence: `Unitree GO2 EDU`, Robot Software Version `V1.0.24`, Hardware Version `V1.0`, SN verified/redacted. | Firmware exact와 authoritative source, complete hardware health가 남아 있다. | #78 |
| `DEPLOYMENT_CURRENT_SAFETY_BOUNDARY` | `UNRESOLVED` | deployed Agent `d6fc2f1...`는 evidence collection 당시 Agent develop snapshot보다 53 commits behind였으며 그 snapshot의 physical-readiness safety boundary를 포함하지 않았다. | 별도 controlled deployment alignment와 software-only verification 필요. | 별도 deployment issue |

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
  실제 검증 완료를 의미하지 않는다. 계획과 기록 template은
  [`go2-hardware-validation-plan.md`](go2-hardware-validation-plan.md)와
  [`templates/go2-hardware-validation-record.md`](templates/go2-hardware-validation-record.md)에
  있다.

따라서 #76 완료로 real command client software boundary만 `RESOLVED`로 갱신한다.
나머지 물리 실행 전제 조건은 해제하지 않는다. 이전 audit에서는 #77~#78과 중복되는
새 Issue를 만들지 않았고, Issue body도 변경하지 않았다. 현재 deployment drift는 이
문서의 별도 unresolved baseline으로 기록하며, controlled deployment alignment는
별도 작업으로 다룬다.

## 안전 경계

이번 감사와 evidence 수집은 software-only다. Physical Readiness는 계속 `BLOCKED`다.
actual GO2, SportClient, DDS command publisher, physical movement, physical emergency stop,
hardware network 접속은 수행하지 않는다.
