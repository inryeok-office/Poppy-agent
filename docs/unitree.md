# Unitree SDK2 read-only integration

Phase 5 uses the official [`unitree_sdk2_python`](https://github.com/unitreerobotics/unitree_sdk2_python)
interface only for Go2 state subscription. The official README lists Python >= 3.8,
`cyclonedds==0.10.2`, NumPy, and OpenCV as dependencies. It also documents Linux
installation and requires `CYCLONEDDS_HOME` or `CMAKE_PREFIX_PATH` when CycloneDDS is
built from source.

The official Go2 examples initialize DDS with a supplied Linux network interface and
subscribe to `rt/lowstate` using `LowState_`:

```python
ChannelFactoryInitialize(0, "enp2s0")
subscriber = ChannelSubscriber("rt/lowstate", LowState_)
subscriber.Init(handler, 10)
```

The repository exposes the optional dependency set with:

```bash
python -m pip install -e ".[unitree]"
```

The SDK itself must be installed from the official repository following its Linux
instructions. This project does not install CycloneDDS, change host network settings,
or infer an interface automatically.

## Read-only boundary

`UnitreeGo2Adapter` subscribes to `rt/lowstate` only. It does not create publishers,
instantiate `SportClient` or `MotionSwitcherClient`, or call any command API.

The official `LowState_` exposes voltage/current (`power_v`/`power_a`), not a battery
percentage. Poppy-Agent therefore reports `battery_percent=None` rather than applying
an unverified conversion. It also reports operation status as `UNAVAILABLE` until a
documented read-only source proves a stronger state.

## Runtime evidence

실제 Ubuntu systemd runtime에서 확인한 Unitree SDK는 다음과 같다.

- distribution: `unitree_sdk2py 1.0.1`
- checkout: `/home/poppy/poppy/unitree_sdk2_python`
- base commit: `65691c8a8bc53b98d3976dba4dbf9d5d20b2e7f5`
- checkout state: `DIRTY`
- dirty file: `unitree_sdk2py/test/lowlevel/read_lowstate.py`
- dirty scope: telemetry helper NIC 이름 `enp2s0` → `enp3s0`, 총 2줄 변경
- production runtime library affected: `NO`
- runtime import path affected: `NO`
- patch SHA256: `087ffbeb362f8453397484d0205c1bf8719c7322ad94a6e9992a19ae80f4205d`
- classification: `PROVIDED_WITH_DIRTY_NON_RUNTIME_HELPER`

CycloneDDS는 Unitree SDK version과 별도의 runtime distribution이며 version은
`0.10.2`다. 이 evidence는 package/runtime metadata를 증명하지만 clean upstream
checkout을 의미하지 않는다.

사용자가 제공한 device evidence는 `Unitree GO2 EDU`, Robot Software Version `V1.0.24`,
Hardware Version `V1.0`, SN verified/redacted다. `V1.0.24`는 device 화면의
`Software Version` label이므로 Firmware Version으로 재명명하지 않는다. Firmware
exact version은 `MISSING`이다.

Hardware validation status: **NOT TESTED ON HARDWARE**.

## Command integration boundary

Telemetry and command execution remain separate concerns:

```text
Read-only UnitreeGo2Adapter telemetry
    -> separate concern
CommandExecutionTarget
    ->
HardwareCommandPort
    ->
MotionExecutionStrategy (MOVE/TURN only, explicit profile)
    ->
UnitreeCommandBackend
    ->
FakeUnitreeCommandClient (software-only tests)
    ->
UnitreeSdkCommandClient (optional, readiness-gated)
```

The current fake backend records hardware-neutral typed intents in memory and can
inject deterministic failures for tests. It does not import the Unitree SDK or
open a network, socket, or DDS publisher. `UnitreeGo2Adapter` remains read-only,
and Unitree production execution remains disabled.

## Motion execution strategy

Poppy `MOVE` is distance-in-meters and `TURN` is angle-in-degrees. The official
Go2 high-level `SportClient.Move(vx, vy, vyaw)` operation is velocity-shaped, so
the Agent does not perform an implicit distance-to-velocity or angle-to-yaw-rate
conversion. `MotionExecutionStrategy` requires an explicitly injected
`MotionProfile` and creates a `MotionPlan` for fake-only deterministic tests.
Production rates and physical limits have no defaults and remain TBD.

The fake client records the plan and a fake sleeper records the requested duration
without waiting. No Unitree SDK command object, DDS publisher, or physical robot
is involved in these tests. The optional real adapter exists, but
`ROBOT_MODE=unitree` remains execution-disabled while Physical Readiness is
blocked.

Physical execution readiness is tracked separately in
[`physical-readiness.md`](physical-readiness.md). The readiness evaluator treats
the Fake Unitree client and test-only MotionProfile as insufficient evidence, and
the enablement request remains disabled by default.

## High-level mapping contract (not enabled)

The official Go2 Python `SportClient` source registers and exposes `Move`,
`StopMove`, `StandUp`, `StandDown`, and `Sit`; its `Move` signature is velocity
shaped as `(vx, vy, vyaw)`. The corresponding official C++ header lists the same
high-level operation shapes. See the [official Python client source](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/unitree_sdk2py/go2/sport/sport_client.py),
[official Python example](https://github.com/unitreerobotics/unitree_sdk2_python/blob/master/example/go2/high_level/go2_sport_client.py),
and [official C++ Go2 SportClient header](https://github.com/unitreerobotics/unitree_sdk2/blob/main/include/unitree/robot/go2/sport/sport_client.hpp).

Poppy's current contract deliberately records the following decisions:

| Poppy command | Client contract | Direct mapping | Decision |
| --- | --- | --- | --- |
| WAIT | no client operation | execution-level only | handled without hardware call |
| MOVE | `Move(vx, vy, vyaw)` shape | no | explicit fake-only planning is possible; physical distance-to-velocity mapping remains unresolved |
| TURN | `Move(vx, vy, vyaw)` yaw component | no | explicit fake-only planning is possible; physical angle-to-yaw-rate mapping remains unresolved |
| STOP | no client operation | no physical mapping | program STOP terminates dispatch; it is not `StopMove` or E-stop |
| POSTURE/SIT | `Sit`-shaped client operation | contract only | Fake client records the mapping; hardware enablement remains gated |
| POSTURE/STAND | `StandUp`-shaped client operation | contract only | Fake client records the mapping; hardware enablement remains gated |
| PRESET | no defined official mapping | no | explicit policy/allow-list required; default unsupported |

The `UnitreeCommandClient` protocol is injected into `UnitreeCommandBackend`.
It returns a normalized success boolean so the backend never silently ignores a
client failure. The official SDK source returns an operation status code, which
`UnitreeSdkCommandClient` normalizes without exposing raw SDK values. The adapter
imports the optional SDK lazily and is constructed only after
`PhysicalExecutionGate` passes. No command publisher, semantic conversion, or
hardware safety limit is defined.

Hardware validation status: **NOT TESTED ON HARDWARE**.
