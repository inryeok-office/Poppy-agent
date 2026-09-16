from __future__ import annotations

from threading import Event
from uuid import UUID

import pytest

import poppy_agent.main as main_module
from poppy_agent.server import AgentServerRuntimeError, ServerClientError

AGENT_ID = UUID("00000000-0000-0000-0000-000000000002")


class FakeRegistration:
    agent_id = AGENT_ID


class FakeRuntime:
    instances: list[FakeRuntime] = []
    start_error: Exception | None = None
    loop_error: Exception | None = None

    def __init__(self, agent: object, server: object, config: object) -> None:
        self.calls: list[str] = []
        self.executors: list[object] = []
        self.__class__.instances.append(self)

    def start(self) -> FakeRegistration:
        self.calls.append("start")
        if self.start_error is not None:
            raise self.start_error
        return FakeRegistration()

    def run_heartbeat_loop(self, stop_event: Event) -> None:
        self.calls.append("run_heartbeat_loop")
        if self.loop_error is not None:
            raise self.loop_error
        stop_event.set()

    def run_loop(self, stop_event: Event, executor: object) -> None:
        self.calls.append("run_loop")
        self.executors.append(executor)
        stop_event.set()

    def shutdown(self) -> None:
        self.calls.append("shutdown")


@pytest.fixture(autouse=True)
def reset_fake_runtime() -> None:
    FakeRuntime.instances.clear()
    FakeRuntime.start_error = None
    FakeRuntime.loop_error = None


def patch_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main_module.AgentConfig,
        "from_environment",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(
        main_module.ServerConfig,
        "from_environment",
        classmethod(lambda cls: object()),
    )
    monkeypatch.setattr(main_module, "create_agent", lambda config: object())
    monkeypatch.setattr(main_module, "ServerClient", lambda config: object())
    monkeypatch.setattr(main_module, "AgentServerRuntime", FakeRuntime)
    monkeypatch.setattr(main_module, "register_signal_handlers", lambda event: None)


def test_main_runs_and_shuts_down_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_dependencies(monkeypatch)

    assert main_module.main() == 0
    assert FakeRuntime.instances[0].calls == ["start", "run_heartbeat_loop", "shutdown"]


def test_main_stops_after_registration_failure_without_heartbeat(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_dependencies(monkeypatch)
    FakeRuntime.start_error = ServerClientError("registration failed")

    assert main_module.main() == 1
    assert FakeRuntime.instances[0].calls == ["start", "shutdown"]
    assert "registration failed" in capsys.readouterr().err


def test_main_shuts_down_after_heartbeat_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_dependencies(monkeypatch)
    FakeRuntime.loop_error = AgentServerRuntimeError("heartbeat failed")

    assert main_module.main() == 1
    assert FakeRuntime.instances[0].calls == ["start", "run_heartbeat_loop", "shutdown"]


def test_signal_handlers_set_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    handlers: dict[object, object] = {}
    monkeypatch.setattr(
        main_module.signal,
        "signal",
        lambda signum, handler: handlers.update({signum: handler}),
    )
    stop_event = Event()

    main_module.register_signal_handlers(stop_event)

    assert set(handlers) == {main_module.Signals.SIGINT, main_module.Signals.SIGTERM}
    for handler in handlers.values():
        assert callable(handler)
        handler(0, None)
    assert stop_event.is_set()


def test_main_does_not_print_token_on_unexpected_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch_dependencies(monkeypatch)
    FakeRuntime.start_error = RuntimeError("request contained POPPY_AGENT_TOKEN=secret")

    assert main_module.main() == 1
    assert "secret" not in capsys.readouterr().err


def test_main_wires_mock_executor_only_for_mock_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_dependencies(monkeypatch)
    monkeypatch.setattr(
        main_module.AgentConfig,
        "from_environment",
        classmethod(lambda cls: type("MockConfig", (), {"robot_mode": "mock"})()),
    )

    assert main_module.main() == 0
    assert FakeRuntime.instances[0].calls == ["start", "run_loop", "shutdown"]
    assert isinstance(FakeRuntime.instances[0].executors[0], main_module.MockExecutionExecutor)


def test_main_keeps_unitree_mode_on_heartbeat_without_executor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_dependencies(monkeypatch)
    monkeypatch.setattr(
        main_module.AgentConfig,
        "from_environment",
        classmethod(
            lambda cls: type(
                "UnitreeConfig",
                (),
                {"robot_mode": "unitree", "enable_physical_execution": True},
            )()
        ),
    )

    assert main_module.main() == 0
    assert FakeRuntime.instances[0].calls == ["start", "run_heartbeat_loop", "shutdown"]
    assert FakeRuntime.instances[0].executors == []
