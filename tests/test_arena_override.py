"""Server arena settings can only narrow the Agent's approved limits (fakes only, no hardware)."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from threading import Event
from typing import Any

import pytest

from poppy_agent.command import (
    CommandType,
    HighLevelCommand,
    HighLevelCommandProgram,
    MoveDirection,
    MoveParameters,
    TurnDirection,
    TurnParameters,
)
from poppy_agent.config import OpenMotionSettings
from poppy_agent.config.arena_override import narrow_arena
from poppy_agent.config.open_motion import load_open_motion_settings
from poppy_agent.execution.arena_sync import ArenaSettingsSync
from poppy_agent.execution.open_motion import OpenMotionGuard, OpenMotionGuardError

KST = timezone(timedelta(hours=9))
START = datetime(2026, 10, 28, 20, 20, tzinfo=KST)
EXPIRES = START + timedelta(hours=2)
OPEN_ENV = {
    "POPPY_PHYSICAL_TRIAL_MODE": "controlled_motion_open",
    "POPPY_PHYSICAL_LINEAR_SPEED_M_PER_S": "0.5",
    "POPPY_PHYSICAL_MAX_MOVE_M_PER_COMMAND": "3.0",
    "POPPY_PHYSICAL_ARENA_WIDTH_M": "6.0",
    "POPPY_PHYSICAL_ARENA_DEPTH_M": "6.0",
    "POPPY_PHYSICAL_ARENA_MARGIN_M": "0.4",
    "POPPY_PHYSICAL_START_X_M": "5.6",
    "POPPY_PHYSICAL_START_Y_M": "0.4",
    "POPPY_PHYSICAL_START_HEADING": "+Y",
    "POPPY_PHYSICAL_TURN_RATE_DEG_PER_S": "45",
    "POPPY_PHYSICAL_MAX_TURN_DEG_PER_COMMAND": "360",
    "POPPY_PHYSICAL_MAX_TOTAL_SECONDS": "120",
    "POPPY_PHYSICAL_POSTURE_SETTLE_SECONDS": "3",
    "POPPY_PHYSICAL_PRESET_SETTLE_SECONDS": "5",
    "POPPY_PHYSICAL_ALLOWED_COMMANDS": "MOVE,TURN,POSTURE,PRESET",
    "POPPY_PHYSICAL_ALLOWED_PRESETS": "HELLO,STRETCH,HEART,DANCE1",
    "POPPY_PHYSICAL_TURN_LEFT_YAW_SIGN": "+1",
    "POPPY_PHYSICAL_APPROVAL_REF": "test-arena-approval",
    "POPPY_PHYSICAL_TRIAL_EXPIRES_AT": EXPIRES.isoformat(),
}

EXPO_ENV = {
    "POPPY_PHYSICAL_ARENA_WIDTH_M": "6.0",
    "POPPY_PHYSICAL_ARENA_DEPTH_M": "6.0",
    "POPPY_PHYSICAL_ARENA_MARGIN_M": "0.4",
    "POPPY_PHYSICAL_START_X_M": "5.6",
    "POPPY_PHYSICAL_START_Y_M": "0.4",
}
BOOTH_ENV = {
    "POPPY_PHYSICAL_ARENA_WIDTH_M": "3.0",
    "POPPY_PHYSICAL_ARENA_DEPTH_M": "3.0",
    "POPPY_PHYSICAL_ARENA_MARGIN_M": "0.5",
    "POPPY_PHYSICAL_START_X_M": "2.5",
    "POPPY_PHYSICAL_START_Y_M": "0.5",
}


def baseline(env: dict[str, str]) -> OpenMotionSettings:
    settings, issues = load_open_motion_settings({**OPEN_ENV, **env}, now=lambda: START)
    assert issues == () and settings is not None
    return settings


def payload(**overrides: Any) -> dict[str, Any]:
    """Server ``GET /api/v1/arena-settings`` data for the 3x3-부스 preset."""
    value: dict[str, Any] = {
        "presetCode": "3x3-부스",
        "widthM": 3.0,
        "depthM": 3.0,
        "marginM": 0.5,
        "startXM": 2.5,
        "startYM": 0.5,
        "startHeading": "+Y",
        "limits": {
            "usableWidthM": 2.0,
            "usableDepthM": 2.0,
            "maxMovePerCommandM": 1.2,
            "defaultMoveDistanceM": 0.5,
        },
    }
    value.update(overrides)
    return value


def move(meters: float, direction: MoveDirection = MoveDirection.FORWARD) -> tuple:
    return (CommandType.MOVE, MoveParameters(direction, meters))


def turn(direction: TurnDirection, degrees: float = 90.0) -> tuple:
    return (CommandType.TURN, TurnParameters(direction, degrees))


def program(*commands: tuple) -> HighLevelCommandProgram:
    built = tuple(
        HighLevelCommand(index, f"block-{index}", command_type, parameters)
        for index, (command_type, parameters) in enumerate(commands)
    )
    return HighLevelCommandProgram(1, built)


def guard_for(settings: OpenMotionSettings) -> OpenMotionGuard:
    return OpenMotionGuard(settings, telemetry_fresh=lambda: True, now=lambda: START)


def admits(guard: OpenMotionGuard, *commands: tuple) -> bool:
    try:
        guard.admit(program(*commands))
    except OpenMotionGuardError:
        return False
    guard.release()
    return True


# --- narrowing is accepted ------------------------------------------------------------------


def test_expo_baseline_narrowed_to_the_3x3_booth() -> None:
    decision = narrow_arena(baseline(EXPO_ENV), payload())
    assert decision.accepted and decision.reason is None
    narrowed = decision.settings
    assert (narrowed.arena_width_meters, narrowed.arena_depth_meters) == (3.0, 3.0)
    assert narrowed.arena_margin_meters == 0.5
    assert (narrowed.start_x_meters, narrowed.start_y_meters) == (2.5, 0.5)
    assert narrowed.max_move_meters_per_command == pytest.approx(1.2)


def test_only_arena_fields_change_everything_else_stays_the_baseline() -> None:
    base = baseline(EXPO_ENV)
    narrowed = narrow_arena(base, payload()).settings
    for name in (
        "mode", "linear_speed_meters_per_second", "turn_rate_degrees_per_second",
        "max_turn_degrees_per_command", "max_total_seconds", "posture_settle_seconds",
        "preset_settle_seconds", "allowed_commands", "allowed_presets", "turn_left_yaw_sign",
        "approval_ref", "expires_at",
    ):  # fmt: skip
        assert getattr(narrowed, name) == getattr(base, name), name
    assert narrowed.expires_at == EXPIRES


def test_same_size_as_the_baseline_is_accepted() -> None:
    expo = payload(
        widthM=6.0, depthM=6.0, marginM=0.4, startXM=5.6, startYM=0.4,
        limits={"maxMovePerCommandM": 3.0},
    )  # fmt: skip
    decision = narrow_arena(baseline(EXPO_ENV), expo)
    assert decision.accepted
    assert decision.settings.max_move_meters_per_command == pytest.approx(3.0)


# --- widening is rejected (the core safety property) ----------------------------------------


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"widthM": 3.5}, "wider"),
        ({"depthM": 3.5}, "deeper"),
        ({"marginM": 0.4}, "margin"),
        ({"marginM": 0.3}, "margin"),
        ({"widthM": 8.0, "depthM": 8.0}, "wider"),
        ({"startXM": 0.2}, "wall margin"),
        ({"startYM": 3.0}, "wall margin"),
        (
            {"widthM": 2.0, "depthM": 2.0, "marginM": 0.5, "startXM": 1.5, "startYM": 0.5},
            "too small",
        ),
        ({"startHeading": "up"}, "startHeading"),
        ({"widthM": math.nan}, "not finite"),
        ({"widthM": -3.0}, "not finite"),
        ({"widthM": True}, "not finite"),
        ({"widthM": "3.0"}, "not finite"),
        ({"limits": {"maxMovePerCommandM": -1}}, "invalid"),
    ],
)  # fmt: skip
def test_booth_baseline_rejects_anything_wider_or_malformed(
    overrides: dict[str, Any], fragment: str
) -> None:
    booth = baseline(BOOTH_ENV)
    decision = narrow_arena(booth, payload(**overrides))
    assert not decision.accepted
    assert fragment in (decision.reason or "")
    assert decision.settings is booth  # nothing changed


def test_a_server_that_asks_for_6x6_cannot_widen_a_3x3_agent() -> None:
    booth = baseline(BOOTH_ENV)
    expo_payload = payload(
        widthM=6.0, depthM=6.0, marginM=0.4, startXM=5.6, startYM=0.4,
        limits={"maxMovePerCommandM": 3.0},
    )  # fmt: skip
    decision = narrow_arena(booth, expo_payload)
    assert not decision.accepted
    guard = guard_for(booth)
    sync = ArenaSettingsSync(baseline=booth, guard=guard, fetch=lambda: expo_payload)
    assert sync.refresh_once() is False
    assert guard.settings is booth
    assert not admits(guard, move(2.1))  # still the 3x3 area: 2.1 m leaves it


@pytest.mark.parametrize("payload_value", [None, [], "x", 3, {}, {"widthM": 3.0}])
def test_non_object_or_incomplete_payload_is_rejected(payload_value: object) -> None:
    base = baseline(EXPO_ENV)
    decision = narrow_arena(base, payload_value)
    assert not decision.accepted and decision.settings is base


def test_remote_move_limit_can_only_lower_never_raise() -> None:
    base = baseline({**EXPO_ENV, "POPPY_PHYSICAL_MAX_MOVE_M_PER_COMMAND": "1.0"})
    # Server says 1.2 m (and the geometry allows it) but the Agent's approved limit is 1.0 m.
    assert narrow_arena(base, payload()).settings.max_move_meters_per_command == pytest.approx(1.0)
    # Server claims 3 m in a 3x3 arena: the Agent derives its own cap from the geometry (1.2).
    greedy = payload(limits={"maxMovePerCommandM": 3.0})
    assert narrow_arena(baseline(EXPO_ENV), greedy).settings.max_move_meters_per_command == (
        pytest.approx(1.2)
    )
    # No limits object at all: still derived from the geometry.
    bare = payload()
    del bare["limits"]
    assert narrow_arena(baseline(EXPO_ENV), bare).settings.max_move_meters_per_command == (
        pytest.approx(1.2)
    )


def test_move_limit_never_exceeds_the_hard_cap_of_three_meters() -> None:
    big = baseline(EXPO_ENV)
    decision = narrow_arena(
        big, payload(widthM=6.0, depthM=6.0, marginM=0.4, startXM=5.6, startYM=0.4)
    )
    assert decision.settings.max_move_meters_per_command <= 3.0


def test_the_agent_hard_caps_stay_below_the_cloud_values() -> None:
    # The 6 m hard cap and the 0.4 m minimum wall margin are enforced when the baseline loads,
    # so no remote value can get past them either.
    issues = load_open_motion_settings(
        {**OPEN_ENV, "POPPY_PHYSICAL_ARENA_WIDTH_M": "8.0"}, now=lambda: START
    )[1]
    assert any("exceeds the approved limit" in issue for issue in issues)
    issues = load_open_motion_settings(
        {**OPEN_ENV, "POPPY_PHYSICAL_ARENA_MARGIN_M": "0.3"}, now=lambda: START
    )[1]
    assert any("below the approved minimum" in issue for issue in issues)


# --- the guard enforces the narrowed arena ----------------------------------------------------


def test_guard_enforces_the_3x3_arena_after_apply() -> None:
    guard = guard_for(baseline(EXPO_ENV))
    assert admits(guard, move(3.0))  # 6x6: 3 m is fine
    guard.apply_arena(narrow_arena(baseline(EXPO_ENV), payload()).settings)
    assert admits(guard, move(1.2))
    assert not admits(guard, move(1.3))  # per-command limit 1.2 m
    assert not admits(guard, move(1.2), move(1.2))  # second move leaves the 2.0 m area
    assert not admits(guard, turn(TurnDirection.RIGHT), move(1.0))  # +x from the corner
    assert admits(guard, turn(TurnDirection.LEFT), move(1.0))
    assert not admits(guard, move(1.0, MoveDirection.BACKWARD))  # behind the start corner


def test_square_walk_fits_the_3x3_booth_with_left_turns() -> None:
    guard = guard_for(narrow_arena(baseline(EXPO_ENV), payload()).settings)
    square = [move(1.0), turn(TurnDirection.LEFT)] * 4
    assert admits(guard, *square)


def test_arena_update_during_an_execution_waits_for_release() -> None:
    guard = guard_for(baseline(EXPO_ENV))
    guard.admit(program(move(1.0)))
    narrowed = narrow_arena(baseline(EXPO_ENV), payload()).settings
    assert guard.apply_arena(narrowed) is False
    assert guard.settings.arena_width_meters == 6.0  # running Execution keeps its values
    guard.release()
    assert guard.settings.arena_width_meters == 3.0


# --- sync: fall back to the baseline, never to the last received value ------------------------


def test_sync_falls_back_to_the_baseline_not_the_last_received_value() -> None:
    base = baseline(EXPO_ENV)
    guard = guard_for(base)
    responses: list[Any] = [payload(), ConnectionError("tunnel down"), payload(widthM=9.0)]

    def fetch() -> Any:
        item = responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    sync = ArenaSettingsSync(baseline=base, guard=guard, fetch=fetch)
    assert sync.refresh_once() is True
    assert guard.settings.arena_width_meters == 3.0 and sync.last_source == "server"
    assert sync.refresh_once() is False  # connection lost → baseline, not the stale 3x3
    assert guard.settings.arena_width_meters == 6.0
    assert sync.last_source == "baseline" and "ConnectionError" in (sync.last_reason or "")
    assert sync.refresh_once() is False  # invalid (too wide) → baseline
    assert guard.settings is base


def test_sync_run_stops_with_the_event_and_survives_errors() -> None:
    base = baseline(EXPO_ENV)
    guard = guard_for(base)
    stop = Event()
    calls: list[int] = []

    def fetch() -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError
        stop.set()
        return payload()

    ArenaSettingsSync(baseline=base, guard=guard, fetch=fetch).run(stop, 0.0)
    assert len(calls) == 2
    assert guard.settings.arena_width_meters == 3.0


def test_expiry_and_approval_are_never_taken_from_the_server() -> None:
    base = baseline(EXPO_ENV)
    hostile = payload(expiresAt="2099-01-01T00:00:00+09:00", approvalRef="x", maxTotalSeconds=9999)
    narrowed = narrow_arena(base, hostile).settings
    assert narrowed.expires_at == base.expires_at == EXPIRES
    assert narrowed.expires_at - START <= timedelta(hours=8, minutes=5)
    assert narrowed.approval_ref == base.approval_ref
    assert narrowed.max_total_seconds == base.max_total_seconds


# --- wiring: off by default, public endpoint --------------------------------------------------


def test_sync_is_off_by_default_so_the_agent_behaves_as_before(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import poppy_agent.main as main_module

    monkeypatch.delenv("POPPY_ARENA_SETTINGS_SYNC", raising=False)
    base = baseline(EXPO_ENV)
    guard = guard_for(base)
    assert main_module._start_arena_sync(base, guard, lambda: payload(), Event()) is None
    assert guard.settings is base
    monkeypatch.setenv("POPPY_ARENA_SETTINGS_SYNC", "false")
    assert main_module._start_arena_sync(base, guard, lambda: payload(), Event()) is None
    assert guard.settings is base


def test_sync_on_applies_the_narrower_arena_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import poppy_agent.main as main_module

    monkeypatch.setenv("POPPY_ARENA_SETTINGS_SYNC", "true")
    base = baseline(EXPO_ENV)
    guard = guard_for(base)
    stop = Event()
    stop.set()  # the background loop exits at once; only the initial refresh matters here
    sync = main_module._start_arena_sync(base, guard, lambda: payload(), stop)
    assert sync is not None and sync.last_source == "server"
    assert guard.settings.arena_width_meters == 3.0


def test_server_client_reads_the_public_arena_endpoint() -> None:
    import httpx

    from poppy_agent.server import ServerClient, ServerConfig

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.method} {request.url.path}")
        return httpx.Response(200, json={"success": True, "data": payload(), "error": None})

    client = ServerClient(
        ServerConfig(
            server_url="https://server.example.test",
            agent_token="dummy-agent-token",
            agent_name="agent-test",
            agent_version="0.1.0",
            sdk_version="not-applicable",
            platform="test",
            max_retries=0,
        ),
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
    )
    assert client.get_arena_settings()["presetCode"] == "3x3-부스"
    assert seen == ["GET /api/v1/arena-settings"]
