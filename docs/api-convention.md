# API convention

Poppy-Agent has no server API client in Phase 1. When the client is added, its request,
response, headers, status handling, and error mapping must be derived from the current
Poppy-Server `develop` implementation and tests. No DTO or endpoint contract may be
written from memory or inference alone.

Authentication values must come from environment configuration and must never appear
in logs, fixtures, or committed documentation.

