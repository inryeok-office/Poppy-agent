# API convention

Poppy-Agent's Phase 3 client follows the Poppy-Server `develop` implementation at the
time of the Phase 3 contract review. The reviewed server commit was `cef9cc7`.

- `POST /api/v1/internal/agents/register` returns HTTP 201.
- `POST /api/v1/internal/agents/{agentId}/heartbeat` returns HTTP 200.
- Both requests send `X-Agent-Token`.
- Both responses use `{ "success": true, "data": ..., "error": null }`.
- Register uses `agentName`, `agentVersion`, `sdkVersion`, `platform`, and UUID-based
  robot metadata.
- Heartbeat uses UTC `sentAt`, `ONLINE`/`OFFLINE`, `READY`/`UNAVAILABLE`, nullable
  `batteryPercent`, and the server's null-versus-omitted `currentExecutionId` meaning.

When the server contract changes, review its current implementation and tests before
changing these models. No DTO or endpoint contract may be written from memory or
inference alone.

Authentication values must come from environment configuration and must never appear
in logs, fixtures, or committed documentation.
