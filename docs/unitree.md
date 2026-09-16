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
