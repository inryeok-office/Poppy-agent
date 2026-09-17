"""Run the localhost-only Agent restart recovery scenario with real HTTP transport."""

from __future__ import annotations

import os
import sys
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid4

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "src"))

from full_mock_e2e import (  # noqa: E402
    COMMAND_CAPABILITIES,
    E2EConfig,
    E2EHttpClient,
    _block_program,
    _find_robot,
    _required_string,
    _wait_for,
)

from poppy_agent.agent import create_agent  # noqa: E402
from poppy_agent.config import AgentConfig  # noqa: E402
from poppy_agent.server import AgentServerRuntime, ServerClient, ServerConfig  # noqa: E402


class SimulatedProcessCrashExecutor:
    """Stop at the first execution boundary without sending a terminal report."""

    def execute(self, _task: object) -> object:
        raise KeyboardInterrupt("simulated Agent process interruption")


def main() -> int:
    config = E2EConfig.from_environment()
    if urlparse(config.server_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("execution recovery E2E only permits localhost")
    http = E2EHttpClient(config.server_url, config.http_timeout_seconds, config.agent_token)
    run_id = uuid4().hex
    robot_id: UUID | None = None
    first_runtime: AgentServerRuntime | None = None
    second_runtime: AgentServerRuntime | None = None
    try:
        robot = http.post(
            "/api/v1/admin/robots",
            {
                "alias": f"recovery-e2e-{run_id}",
                "model": "mock",
                "edition": "development",
                "firmwareVersion": "mock",
                "sdkVersion": "not-applicable",
                "agentId": None,
                "capabilities": [],
                "safetyProfileId": None,
                "isExternal": False,
            },
            expected_status=201,
        )
        robot_id = UUID(_required_string(robot, "robotId"))
        session = http.post("/api/v1/sessions", {}, expected_status=201)
        session_id = UUID(_required_string(session, "sessionId"))
        session_token = _required_string(session, "sessionToken")
        revision = http.post(
            f"/api/v1/sessions/{session_id}/block-revisions",
            {"document": _block_program()},
            expected_status=201,
            session_token=session_token,
        )
        block_version = revision["blockVersion"]
        http.post(
            f"/api/v1/sessions/{session_id}/simulation-passes",
            {"blockVersion": block_version},
            expected_status=201,
            session_token=session_token,
        )
        execution = http.post(
            f"/api/v1/sessions/{session_id}/executions",
            {"blockVersion": block_version},
            expected_status=201,
            session_token=session_token,
        )
        execution_id = UUID(_required_string(execution, "executionId"))

        server_config = ServerConfig(
            server_url=config.server_url,
            agent_token=config.agent_token,
            agent_name=f"poppy-recovery-e2e-{run_id}",
            agent_version="0.1.0",
            sdk_version="not-applicable",
            platform="recovery-e2e",
            heartbeat_interval_seconds=30.0,
            execution_poll_interval_seconds=config.poll_interval_seconds,
            connect_timeout_seconds=config.http_timeout_seconds,
            read_timeout_seconds=config.http_timeout_seconds,
            max_retries=0,
        )
        first_runtime = AgentServerRuntime(
            create_agent(AgentConfig(robot_mode="mock", robot_id=str(robot_id))),
            ServerClient(server_config),
            server_config,
        )
        first_runtime.start()
        capabilities = [{"code": "telemetry", "status": "UNVERIFIED"}]
        capabilities.extend(
            {"code": code, "status": "VERIFIED"} for code in sorted(COMMAND_CAPABILITIES)
        )
        http.patch(f"/api/v1/admin/robots/{robot_id}", {"capabilities": capabilities})
        first_runtime.heartbeat_once()
        _wait_for(
            "Robot ready",
            lambda: _find_robot(http, robot_id),
            lambda value: (
                value.get("connectionStatus") == "ONLINE"
                and value.get("operationalStatus") == "READY"
            ),
            config,
        )
        _wait_for(
            "Execution assigned",
            lambda: http.get(f"/api/v1/executions/{execution_id}", session_token=session_token),
            lambda value: (
                value.get("status") == "ASSIGNED" and value.get("assignedRobotId") == str(robot_id)
            ),
            config,
        )
        delivery_probe = first_runtime.server.fetch_next_execution(first_runtime.agent_id, robot_id)
        if delivery_probe is None or delivery_probe.execution_id != execution_id:
            execution_snapshot = http.get(
                f"/api/v1/executions/{execution_id}", session_token=session_token
            )
            robot_snapshot = _find_robot(http, robot_id)
            raise RuntimeError(
                "assigned execution was not delivered to the restarting Agent: "
                f"delivery={delivery_probe}, "
                f"execution={execution_snapshot}, "
                f"robot={robot_snapshot}"
            )

        try:
            first_runtime.execution_once(SimulatedProcessCrashExecutor())  # type: ignore[arg-type]
        except KeyboardInterrupt:
            pass
        active_before = http.get(f"/api/v1/executions/{execution_id}", session_token=session_token)
        if active_before.get("status") != "RUNNING":
            raise RuntimeError(
                "simulated crash did not leave the execution RUNNING: "
                f"status={active_before.get('status')}, "
                f"active_execution_id={first_runtime.active_execution_id}"
            )
        occupied_before = _find_robot(http, robot_id)
        if occupied_before.get("currentExecutionId") != str(execution_id):
            raise RuntimeError("simulated crash did not preserve Robot ownership")
        print(f"Interrupted execution preserved on Server: {execution_id}")
        first_runtime.shutdown()
        first_runtime = None

        second_runtime = AgentServerRuntime(
            create_agent(AgentConfig(robot_mode="mock", robot_id=str(robot_id))),
            ServerClient(server_config),
            server_config,
        )
        second_runtime.start()
        recovered = _wait_for(
            "Execution recovery",
            lambda: http.get(f"/api/v1/executions/{execution_id}", session_token=session_token),
            lambda value: value.get("status") == "FAILED",
            config,
        )
        if recovered.get("status") != "FAILED":
            raise RuntimeError("interrupted execution was not reconciled as FAILED")
        released = _find_robot(http, robot_id)
        if released.get("occupied") is not False or released.get("currentExecutionId") is not None:
            raise RuntimeError("recovery did not release Robot ownership")
        if second_runtime.active_execution_id is not None:
            raise RuntimeError("recovery left active_execution_id set")
        second_runtime.heartbeat_once()
        if second_runtime.execution_once(_no_work_executor()) is not None:
            raise RuntimeError("recovered execution was delivered again")
        print("Crash Recovery E2E PASSED: no replay, FAILED reconciliation, Robot release, no work")
        return 0
    finally:
        if first_runtime is not None:
            first_runtime.shutdown()
        if second_runtime is not None:
            second_runtime.shutdown()


def _no_work_executor() -> Any:
    return SimulatedProcessCrashExecutor()


if __name__ == "__main__":
    raise SystemExit(main())
