# GO2 Hardware Validation Record Template

> 이 template은 기록 양식일 뿐이다. 체크하지 않은 항목을 승인된 것으로 해석하지
> 않는다. 실제 hardware validation은 별도의 승인된 환경과 supervising adult/operator
> 하에서만 수행한다. Raw credential, HTTP auth header, SDK packet/payload는 기록하지 않는다.

## Decision

- Date/time:
- Validation record reference:
- Final decision: `NOT STARTED` / `PASSED` / `FAILED` / `ABORTED`
- Remaining blockers:

## Approval Checklist

- [ ] equipment owner approval received (reference only):
- [ ] supervising operator confirmed (role/reference only):
- [ ] 담당 교사 또는 책임 있는 성인 confirmed (role/reference only):
- [ ] software operator confirmed (role/reference only):
- [ ] approved validation environment confirmed:
- [ ] authoritative equipment information reviewed:
- [ ] authoritative physical limits reviewed and approved:
- [ ] production motion profile reviewed and approved:
- [ ] PRESET policy reviewed, or PRESET remains explicitly excluded:
- [ ] physical emergency responsibility and official procedure confirmed:
- [ ] telemetry expectations reviewed:
- [ ] observability expectations reviewed:
- [ ] rollback/disable path verified:
- [ ] evidence storage and incident reference prepared:

## Version and Equipment Identity

- Agent commit SHA:
- Server commit SHA:
- Hardware identity/model:
- Firmware version:
- SDK version:
- Hardware/network environment reference (no secret):

## Validation Scope

- Approved validation scope:
- Explicitly excluded commands or profiles:
- Physical limits source/reference:
- Motion profile source/reference:
- PRESET policy source/reference:

## Software Preconditions

- pytest result/reference:
- ruff/mypy/harness result/reference:
- Physical Readiness status before validation:
- Software-only preflight result/reference:
- Replay/duplicate dispatch evidence:
- Disable/rollback evidence:

## Telemetry Observations

- Robot connection state:
- Agent connection/operational state:
- execution ownership:
- execution lifecycle:
- telemetry availability:
- battery/status availability and interpretation reference:
- disconnect/recovery observations:

## Observability Observations

- startup/readiness:
- dispatch attempt/result:
- cancellation:
- connectivity degradation:
- reconciliation/recovery:
- shutdown/cleanup:
- disable/rollback:

## Command and Result Observations

- Approved command scope observed:
- Command/result agreement:
- Unexpected command or dispatch: `NO` / `YES` (incident reference):
- Duplicate/replay: `NO` / `YES` (incident reference):
- Physical values: record only from approved authoritative source; do not invent values.

## Abort and Incident Record

- Abort event: `NONE` / `YES`
- Abort reason/category:
- Requesting role/reference:
- Incident reference:
- Environment safety observation:
- Cancellation/stop observation:
- Cleanup result:

## Final Review

- Equipment owner review reference:
- Supervising operator review reference:
- Teacher/responsible adult review reference (if applicable):
- Software operator review reference:
- Follow-up issue/reference:
- Physical Readiness after review: `BLOCKED` until all required evidence is independently approved.

## Safety Boundary

Program STOP, Execution Cancellation, Administrative Stop, and Physical Emergency Stop
are distinct concepts. This record does not define a physical emergency-stop procedure.
The actual device procedure must be confirmed by the equipment owner/supervising operator
from authoritative guidance before any validation.
