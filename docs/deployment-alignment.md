# Deployment Alignment Preparation

이 문서는 실제 Ubuntu 운영 Agent를 최신 Poppy-agent baseline으로 정렬하기 위한 준비 감사다. Audit date는 `2026-09-29` (Asia/Seoul)이며, 이번 Issue에서는 repository 문서와 software-only 검증만 수행한다. production deployment, systemd service, EnvironmentFile, dependency 설치, Robot network와 physical operation은 변경하지 않는다.

## Audit Snapshot

이 문서의 SHA와 drift 값은 audit 실행 시점의 snapshot이다. 이 문서가 develop에 merge되면 latest develop은 새 merge commit으로 이동하므로, 실제 controlled deployment 직전에 target SHA와 drift를 다시 계산해야 한다.

| 항목 | 값 |
| --- | --- |
| deployed Agent SHA | `d6fc2f1acab258c200583f1fc946a44eea29fb42` |
| target Agent develop SHA at audit | `c0cf65c219751cefafff29719427829f0d28e400` |
| target Poppy-Server develop SHA at audit | `3951e51dfe453dc215d6eeb190997235b3aeaabb` |
| merge-base | `d6fc2f1acab258c200583f1fc946a44eea29fb42` |
| commits behind | `55` |
| commits ahead | `0` |
| changed commits | `55` |
| changed files | `86` |
| diff size | `15,183` insertions, `50` deletions |
| deployed Poppy-Server SHA | `UNAVAILABLE` in this evidence run |

The deployed Agent is a direct ancestor of the audit target. The 55 commit count was calculated with `git rev-list --count deployed..target`; no earlier 53 or 54 commit snapshot is used for this audit.

## Change Inventory

Impact is migration impact for a controlled software change. It is not a physical-readiness approval.

| Category | Impact | Evidence |
| --- | --- | --- |
| Runtime lifecycle | `HIGH` | `src/poppy_agent/main.py`, `src/poppy_agent/server/runtime.py`, `src/poppy_agent/operational_status.py`; startup, loop, shutdown, degraded and recovery states changed across `0c100bd`, `f9a3be9`, `0f19d10`, `0621d39` |
| Server communication | `HIGH` | `src/poppy_agent/server/client.py`, `server/config.py`, `server/runtime.py`; execution delivery/status, reconnect and retry behavior changed in `987c65c`, `0c100bd`, `8106400` |
| Agent credential/auth | `MEDIUM` | credential support and compatibility changes in `d7f4ea0`, `f9e6ee5`, `c345afb`, stale credential fencing in `722481d`, `8b5b83d`; existing token key is retained |
| Execution polling | `HIGH` | polling, cancellation and executor integration in `0c100bd`, `a289890`, `src/poppy_agent/execution`, `server/runtime.py` |
| Status reporting | `HIGH` | operational snapshot and lifecycle publication in `64f3de2`, `f9a3be9`, `src/poppy_agent/operational_status.py` |
| Recovery/reconciliation | `HIGH` | interrupted execution recovery and reconnect reconciliation in `b0e717b`, `8106400`, `src/poppy_agent/server/runtime.py` |
| Duplicate prevention | `MEDIUM` | stale-agent fencing and ownership checks in `722481d`, `8b5b83d`, `src/poppy_agent/server/runtime.py` |
| Unitree adapter | `HIGH` | command boundary and lazy SDK client in `f32099f`, `be3e41d`, `36c7100`, `efee990`, `790bcd9` |
| PhysicalExecutionGate | `HIGH` | readiness gate and fail-closed executor construction in `a1359a8`, `efee990`, `src/poppy_agent/execution/readiness.py`, `src/poppy_agent/hardware/factory.py` |
| Physical preflight | `HIGH` | software-only preflight and replay/motion validation in `cc27460`, `d364c4a`, `26fc7cc`, `scripts/physical_execution_preflight.py` |
| Safety/readiness | `HIGH` | Physical Readiness contract, validation plan and evidence docs in `521cdb6`, `deed39a`, `f340420`, `5e174d3`, `c1bdbe5` |
| Config/env | `MEDIUM` | new optional execution, reconnect, status and physical-execution settings in `.env.example`, `deploy/systemd/poppy-agent.env.example`, `src/poppy_agent/config`, `src/poppy_agent/server/config.py` |
| systemd | `MEDIUM` | `RuntimeDirectory=poppy-agent` and mode `0750` added by `64f3de2`; User, WorkingDirectory, EnvironmentFile and ExecStart remain the same |
| Dependency | `LOW / NOTES` | `pyproject.toml` is unchanged; Python requirement and optional CycloneDDS requirement remain explicit, but Unitree SDK is external editable runtime state and not pinned by the project |
| Documentation | `LOW` | deployment, configuration, safety and validation documents; no runtime behavior by themselves |
| Test/harness | `LOW` | mock, preflight, recovery and hermetic SDK tests; no production deployment behavior by themselves |

## Runtime Dependency Compatibility

| Item | Runtime evidence | Latest develop contract | Result |
| --- | --- | --- | --- |
| Python | Python 3.11 | `requires-python = >=3.11,<3.12` | `COMPATIBLE` |
| Unitree SDK | `unitree_sdk2py 1.0.1`, base commit `65691c8a8bc53b98d3976dba4dbf9d5d20b2e7f5`, editable checkout | imported lazily behind adapter boundaries; SDK is not a `pyproject.toml` dependency or lockfile entry | `COMPATIBLE_WITH_NOTES` |
| SDK checkout state | dirty only in `unitree_sdk2py/test/lowlevel/read_lowstate.py`; `enp2s0` to `enp3s0`; production runtime affected `NO` | source code does not depend on that helper change | `COMPATIBLE_WITH_NOTES` |
| CycloneDDS | runtime distribution `0.10.2` | optional dependency `cyclonedds==0.10.2` | `COMPATIBLE` |
| Poppy-Agent dependencies | runtime package metadata was not changed by this audit | `httpx>=0.27,<1`; dev constraints in `pyproject.toml`; no lockfile | `COMPATIBLE_WITH_NOTES` |
| Systemd Python path | `/home/poppy/projects/Poppy-agent/.venv/bin/python` at deployed runtime | unit keeps the same absolute `ExecStart` path | `COMPATIBLE_WITH_NOTES` |

No package install, upgrade, uninstall or dependency resolution was performed. Unitree SDK exact compatibility is supported by the observed runtime metadata, but it is not reproducible from a project lockfile.

## Environment Configuration Migration

The actual `/etc/poppy-agent/poppy-agent.env` was not readable during this audit: ownership is `root:root`, mode `600`, and the current user did not print or bypass its secret contents. Actual values are therefore `UNAVAILABLE`. Example files and source defaults are not treated as actual deployment values.

| Key | Deployed baseline | Latest develop | Migration impact | Required before controlled deployment |
| --- | --- | --- | --- | --- |
| `ROBOT_MODE` | existing, example `unitree` | unchanged; supports explicit `mock`/`unitree` | `LOW` | confirm actual value by secret-safe whitelist read |
| `POPPY_ROBOT_ID` | existing | unchanged and required | `LOW` | confirm presence and UUID validity without recording raw value |
| `UNITREE_NETWORK_INTERFACE` | existing | unchanged and required for `unitree` | `LOW` | confirm presence; do not change it in this task |
| `POPPY_ROBOT_MODEL` / `POPPY_ROBOT_EDITION` | existing | unchanged and required for `unitree` | `LOW` | confirm presence |
| `POPPY_ROBOT_FIRMWARE_VERSION` | existing example `unknown` | unchanged and required for `unitree` config parsing | `MEDIUM` | exact actual firmware remains a separate evidence blocker; do not use `unknown` as firmware evidence |
| `UNITREE_SDK_VERSION` / `POPPY_SDK_VERSION` | existing | unchanged | `LOW` | compare metadata to recorded SDK evidence; no install |
| `POPPY_AGENT_VERSION` / `POPPY_AGENT_PLATFORM` | existing | unchanged | `LOW` | confirm registration metadata |
| `POPPY_SERVER_URL` | existing | unchanged | `MEDIUM` | confirm approved endpoint without printing credentials or contacting it in this task |
| `POPPY_AGENT_TOKEN` | existing secret key | unchanged key and compatibility path | `MEDIUM` | preserve value outside repository; validate only in a separate controlled software task |
| `POPPY_ENABLE_PHYSICAL_EXECUTION` | absent from deployed baseline example | new optional boolean, default `false` | `HIGH` safety significance, low startup migration | explicitly confirm absent means false; never enable during deployment preparation |
| `POPPY_EXECUTION_POLL_INTERVAL_SECONDS` | absent | optional, default `1` | `LOW` | retain default or set an approved software value |
| `POPPY_SERVER_RECONNECT_INITIAL_DELAY_SECONDS` | absent | optional, default `1` | `LOW` | retain default or set an approved software value |
| `POPPY_SERVER_RECONNECT_MAX_DELAY_SECONDS` | absent | optional, default `30` | `LOW` | retain default or set an approved software value |
| `POPPY_RUNTIME_STATUS_PATH` | absent | optional; systemd example uses `/run/poppy-agent/status.json` | `MEDIUM` | if enabled, deploy the matching `RuntimeDirectory` unit and verify permissions |

No existing production auth key was renamed or removed. `POPPY_E2E_*`, `POPPY_SERVER_RESTART_*`, `POPPY_PREFLIGHT_*` and `POPPY_SYSTEMD_REHEARSAL*` are test/rehearsal-only variables in scripts and are not production EnvironmentFile migration keys.

## Safety Boundary Delta

| Boundary | Latest develop | Deployed `d6fc2f1...` | Evidence |
| --- | --- | --- | --- |
| `PhysicalExecutionGate` | `PRESENT` | `MISSING` | `src/poppy_agent/execution/readiness.py`; `d6` has no current readiness gate |
| `UnitreeSdkCommandClient` | `PRESENT` | `MISSING` | `src/poppy_agent/hardware/unitree_sdk.py`; added by `efee990` |
| Physical execution preflight | `PRESENT` | `MISSING` | `scripts/physical_execution_preflight.py` and `docs/physical-execution-preflight.md`; added after `d6` |
| PRESET fail-closed policy | `PRESENT` | `MISSING` | current command safety/readiness tests and preflight; no equivalent current boundary at `d6` |
| MOVE/TURN explicit mapper boundary | `PRESENT` | `MISSING` | `src/poppy_agent/execution/motion.py` and Unitree mapper; no current boundary at `d6` |
| Physical execution default-disabled gate | `PRESENT` | `MISSING` | `AgentConfig` defaults `POPPY_ENABLE_PHYSICAL_EXECUTION` to `false`; factory evaluates the gate before client construction |
| Software STOP vs physical emergency stop distinction | `PRESENT` | `MISSING` | current safety and validation docs explicitly separate them; no current contract at `d6` |

The latest source creates the real Unitree command executor only when the physical flag is true, and `create_unitree_execution_executor` evaluates `PhysicalExecutionGate` before calling the SDK client factory. The deployed baseline does not contain this current boundary and must not be used as evidence for current physical-readiness software.

## Deployment Migration Risks

| Risk | Evidence | Required before deployment |
| --- | --- | --- |
| Current runtime lifecycle and Server contract changed substantially | 55 commits include polling, status, retry, recovery, ownership and reconciliation changes | run software-only mock/config/contract verification against the target SHA and approved Server compatibility reference |
| Existing EnvironmentFile may omit new optional keys | new defaults exist for physical flag, polling, reconnect and status path | perform a secret-safe whitelist audit; explicitly record absent/defaulted keys |
| Status path requires matching systemd runtime directory | current example uses `/run/poppy-agent/status.json`; unit adds `RuntimeDirectory=poppy-agent` | align the service unit and EnvironmentFile together in the controlled change |
| Physical flag could be misconfigured | current parser accepts only true/false and defaults false; gate remains fail-closed | verify value is absent/false before any controlled software startup; do not enable it |
| Unitree SDK is not pinned by project metadata | runtime has editable `unitree_sdk2py 1.0.1`, but `pyproject.toml` has no exact SDK requirement | record runtime package/checkout evidence and compatibility approval without installing anything here |
| Auth and registration contract changed | credential compatibility and legacy registration tests were added after `d6` | validate token-backed registration in an approved software-only environment; never copy or log the token |
| Actual EnvironmentFile values are unavailable | `/etc/poppy-agent/poppy-agent.env` is root-only and was not read | obtain an authorized secret-safe config audit in the separate controlled task |
| Deployed source lacks current safety boundary | deployed SHA is 55 commits behind and does not contain current gate/preflight/mapper | do not use the deployed process for current physical validation; align software first |

## Rollback Plan

This is a plan only. No rollback or service operation was executed.

1. Record the current deployed Agent SHA `d6fc2f1acab258c200583f1fc946a44eea29fb42` and the controlled target SHA immediately before the change.
2. Preserve a protected backup reference for `/etc/poppy-agent/poppy-agent.env`, its owner/mode, and the deployed systemd unit. Never copy secret values into the repository, issue, PR, or logs.
3. Record the target virtualenv/package metadata and the exact target repository SHA before changing the service.
4. Rollback is indicated by configuration parse failure, authentication/registration incompatibility, repeated startup failure, unexpected lifecycle/recovery behavior, status-path permission failure, or any failure of the fail-closed safety boundary.
5. In a separately approved controlled task, restore the previous software SHA and matching service/config baseline, then use the preserved EnvironmentFile backup without exposing its contents.
6. After rollback, perform only software-only checks: config parser tests, mock Agent/Server registration, mock execution, status/recovery checks, harness, Ruff, mypy and pytest. Do not use Robot network, DDS, SDK initialization or physical commands as rollback checks.

## Software-only Verification

The test boundary was reviewed before execution. Unitree tests use import monkeypatches or fake SDK modules; the physical gate tests assert that a blocked gate does not call the SDK factory; the preflight harness rejects `ROBOT_MODE=unitree`, live transport and real SDK flags. No test in this verification was allowed to initialize the actual SDK or DDS.

Executed in the existing runtime virtualenv, which contains the recorded Unitree SDK and CycloneDDS:

- `python scripts/harness_check.py`: PASS
- `ruff check .`: PASS
- `ruff format --check .`: PASS
- `mypy`: PASS
- `pytest`: 271 passed
- `git diff --check`: PASS

Relevant software-only coverage includes `tests/test_unitree_adapter.py`, `tests/test_unitree_sdk.py`, `tests/test_physical_readiness.py`, `tests/test_physical_execution_preflight.py`, `tests/test_server_runtime.py`, `tests/test_runtime_connectivity.py` and `tests/test_systemd_recovery_rehearsal.py`. No Agent service, EnvironmentFile or deployment process was changed.

## Preparation Decision

`DEPLOYMENT_READY_FOR_CONTROLLED_CHANGE`

The audit, migration inventory, compatibility notes, safety delta, rollback plan and software-only verification are complete for a separately approved controlled deployment task. This does not mean the actual deployment was performed, and it does not change Physical Readiness:

```text
Physical Readiness: BLOCKED
Physical execution: NOT READY FOR PHYSICAL EXECUTION
Hardware validation: NOT TESTED ON HARDWARE
```

The controlled deployment task must re-query latest Agent/Server develop, confirm the real EnvironmentFile through an authorized secret-safe audit, obtain human approval, and exclude Robot movement and physical commands.

## Safety

- Robot network accessed: `NO`
- DDS initialized: `NO`
- SportClient: `NO`
- publisher/subscriber: `NO`
- Agent service changed: `NO`
- deployment changed: `NO`
- EnvironmentFile changed: `NO`
- physical execution enabled: `NO`
- physical command: `NO`
- Robot movement: `NO`
