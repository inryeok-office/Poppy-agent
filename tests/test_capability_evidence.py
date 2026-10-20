from uuid import UUID

import pytest

from poppy_agent.execution import (
    CapabilityEvidenceCache,
    CapabilityEvidenceFailure,
    CapabilityEvidencePolicy,
)
from poppy_agent.server import (
    AgentCapabilityEvidenceResponse,
    CapabilityEvidenceStatus,
    RobotCapabilityEvidence,
    ServerApiError,
)

ROBOT_ID = UUID("00000000-0000-0000-0000-000000000001")
AGENT_ID = UUID("00000000-0000-0000-0000-000000000002")


class Clock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value


class EvidenceServer:
    def __init__(self, response: AgentCapabilityEvidenceResponse | Exception) -> None:
        self.response = response
        self.calls = 0
        self.timeout_seconds: float | None = None

    def get_capability_evidence(
        self, agent_id: UUID, robot_id: UUID, *, timeout_seconds: float | None = None
    ) -> AgentCapabilityEvidenceResponse:
        assert agent_id == AGENT_ID
        assert robot_id == ROBOT_ID
        self.calls += 1
        self.timeout_seconds = timeout_seconds
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def policy() -> CapabilityEvidencePolicy:
    return CapabilityEvidencePolicy("COMMAND_MOVE", 2.0, 5.0, 1.0)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True])
def test_policy_rejects_non_finite_or_boolean_timing(value: float | bool) -> None:
    with pytest.raises(ValueError, match="positive finite"):
        CapabilityEvidencePolicy("COMMAND_MOVE", value, 5.0, 1.0)


def response(status: CapabilityEvidenceStatus = CapabilityEvidenceStatus.VERIFIED):
    return AgentCapabilityEvidenceResponse(
        robot_id=ROBOT_ID,
        capabilities=(RobotCapabilityEvidence("COMMAND_MOVE", status),),
    )


def test_verified_evidence_uses_monotonic_ttl_and_request_timeout() -> None:
    clock = Clock()
    cache = CapabilityEvidenceCache(policy(), clock=clock)
    server = EvidenceServer(response())

    cache.refresh(server, AGENT_ID, ROBOT_ID)

    assert server.timeout_seconds == 1.0
    assert cache.ready(ROBOT_ID)
    clock.value = 4.9
    assert cache.ready(ROBOT_ID)
    assert cache.due(ROBOT_ID)
    clock.value = 5.1
    assert not cache.ready(ROBOT_ID)


def test_unverified_and_unknown_capabilities_never_grant_access() -> None:
    clock = Clock()
    cache = CapabilityEvidenceCache(policy(), clock=clock)

    cache.refresh(EvidenceServer(response(CapabilityEvidenceStatus.UNVERIFIED)), AGENT_ID, ROBOT_ID)
    assert not cache.ready(ROBOT_ID)
    cache.refresh(EvidenceServer(AgentCapabilityEvidenceResponse(ROBOT_ID, ())), AGENT_ID, ROBOT_ID)
    assert not cache.ready(ROBOT_ID)


def test_auth_and_identity_failures_clear_an_existing_grant() -> None:
    clock = Clock()
    cache = CapabilityEvidenceCache(policy(), clock=clock)
    cache.refresh(EvidenceServer(response()), AGENT_ID, ROBOT_ID)
    assert cache.ready(ROBOT_ID)

    failed = cache.refresh(EvidenceServer(ServerApiError(403, "DENIED")), AGENT_ID, ROBOT_ID)

    assert failed.failure is CapabilityEvidenceFailure.ACCESS_DENIED
    assert failed.checked_monotonic == 0.0
    assert not cache.ready(ROBOT_ID)
    assert not failed.fresh(now=0.0, ttl_seconds=5.0)
    clock.value = 1.9
    assert not cache.due(ROBOT_ID)
    clock.value = 2.0
    assert cache.due(ROBOT_ID)
    mismatch = AgentCapabilityEvidenceResponse(AGENT_ID, ())
    failed = cache.refresh(EvidenceServer(mismatch), AGENT_ID, ROBOT_ID)
    assert failed.failure is CapabilityEvidenceFailure.IDENTITY_MISMATCH
