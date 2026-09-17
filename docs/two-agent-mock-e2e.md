# Two-Robot / Two-Agent Concurrent Full Mock E2E

## Scope

This harness verifies that two independent Poppy-agent runtimes can process
two executions concurrently through the local Poppy-Server and PostgreSQL
pipeline without crossing credentials, Robot ownership, or lifecycle state.
It is an integration test, separate from the normal unit-test harness.

The scenario is mock-only. It does not connect to a Unitree GO2, import a
command SDK, publish DDS commands, call SportClient, or move a physical Robot.

## Prerequisites

Use a local Docker Desktop Linux engine and the documented local Poppy-Server
compose environment. The Server must expose `http://localhost:8080` and use an
ephemeral local PostgreSQL database. Set the same local bootstrap token in the
Server and Agent process environment:

```powershell
$env:POPPY_AGENT_TOKEN = "local-two-agent-e2e-token"
$env:POPPY_E2E_SERVER_URL = "http://localhost:8080"
$env:POPPY_E2E_AGENT_TOKEN = "local-two-agent-e2e-token"
```

Run the Server from its repository, wait until PostgreSQL is healthy and the
application is accepting HTTP requests, then run from this repository:

```powershell
python scripts/two_agent_mock_e2e.py
```

For repeatability, use a fresh ephemeral Poppy PostgreSQL volume for a new
run. Only the local Poppy compose project volume may be reset; do not remove
unrelated Docker volumes.

## Scenario and assertions

The harness creates Robot A and Robot B and registers Agent A and Agent B with
separate runtime credentials. It then exercises:

- credential cross-access rejection;
- two executions concurrently RUNNING and completing independently;
- Agent/Robot polling and ownership isolation;
- cancellation of one execution while the other completes;
- interrupted execution recovery for one Agent without command replay;
- Robot release and `active_execution_id` cleanup for both runtimes; and
- final no-work polling on both Agents.

Assignment assertions follow the Server allocation contract: the test requires
the two executions to use different compatible Robots and requires each Agent
to process only the execution for its bound Robot. It does not rely on a
particular queue ordering detail.

Network interruption classification and reconnect behavior remain covered by
the existing deterministic runtime connectivity tests. This harness does not
change host networking or cut a real network interface.

## Safety boundary

The fixture uses Mock execution targets and fake executors only. It does not
enable production Unitree execution, define physical motion limits, configure
PRESET hardware mapping, or perform a physical hardware test.
