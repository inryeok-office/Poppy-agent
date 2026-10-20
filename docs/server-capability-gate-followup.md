# Follow-up: server capability evidence for physical execution

## Background

The Agent registration request sends capability codes and the heartbeat response
only acknowledges the Agent ID and timestamp.  The Agent client has no
read-only endpoint that returns an administrator-verified capability state.
Consequently `TELEMETRY:VERIFIED` cannot currently be used as runtime evidence
for physical execution.

## Required contract decision

The Server must define a read-only Agent-scoped capability-evidence response,
including Robot ID, capability code, verification state, revision/timestamp,
and authorization behavior.  It must not let an Agent approve its own
capability.  `TELEMETRY:VERIFIED` must remain distinct from an approval for
motion/command capability.

## Non-goals

- no capability PATCH from the Agent;
- no database update or migration in this follow-up;
- no reuse of telemetry verification as a motion approval;
- no change to GO2EDU002.

## Completion conditions

1. Server target contract and authorization are reviewed.
2. A read-only internal endpoint or signed registration/heartbeat evidence is
   specified with backward compatibility.
3. Agent parses only its bound Robot's evidence and fails closed for missing,
   unknown, stale, or unverified data.
4. Admin authorization, idempotency, null/legacy payload, and cross-Robot
   isolation tests pass.
