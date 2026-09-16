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

This environment has no installed Unitree SDK, CycloneDDS runtime, or physical Go2.
Hardware validation status: **NOT TESTED ON HARDWARE**.

## Future command integration boundary

Telemetry and command execution remain separate concerns:

```text
Read-only UnitreeGo2Adapter telemetry
    -> separate concern
CommandExecutionTarget
    ->
HardwareCommandPort
    ->
FakeHardwareBackend (current phase)
    ->
Real Unitree backend (future, disabled)
```

The current fake backend records hardware-neutral typed intents in memory and can
inject deterministic failures for tests. It does not import the Unitree SDK or
open a network, socket, or DDS publisher. `UnitreeGo2Adapter` remains read-only,
and Unitree production execution remains disabled.

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
| MOVE | `Move(vx, vy, vyaw)` shape | no | distance-to-velocity strategy is unresolved; fail closed |
| TURN | `Move(vx, vy, vyaw)` yaw component | no | angle-to-angular-velocity strategy is unresolved; fail closed |
| STOP | no client operation | no physical mapping | program STOP terminates dispatch; it is not `StopMove` or E-stop |
| POSTURE/SIT | `Sit`-shaped client operation | contract only | Fake client records the mapping; hardware enablement remains gated |
| POSTURE/STAND | `StandUp`-shaped client operation | contract only | Fake client records the mapping; hardware enablement remains gated |
| PRESET | no defined official mapping | no | explicit policy/allow-list required; default unsupported |

The `UnitreeCommandClient` protocol is injected into `UnitreeCommandBackend`.
It returns a normalized success boolean so the backend never silently ignores a
client failure. The official SDK source returns an operation status code; a future
real client must translate that code according to a separately reviewed policy.
Only `FakeUnitreeCommandClient` is implemented in this phase. No real client, SDK
import, SportClient instance, command publisher, semantic conversion, or hardware
safety limit is defined.

Hardware validation status: **NOT TESTED ON HARDWARE**.
