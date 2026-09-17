import json
import logging

from poppy_agent.observability import (
    AGENT_REGISTERED,
    SERVER_REQUEST_RETRY,
    UNSTRUCTURED_LOG_SUPPRESSED,
    JsonFormatter,
    log_event,
)


def test_structured_event_allowlists_context_and_never_records_secrets(caplog) -> None:
    logger = logging.getLogger("poppy_agent.test.observability")

    with caplog.at_level(logging.INFO, logger=logger.name):
        log_event(
            logger,
            logging.INFO,
            AGENT_REGISTERED,
            agent_id="agent-1",
            robot_id="robot-1",
            agent_token="bootstrap-secret",
            command_payload='{"secret":"payload"}',
            headers="X-Agent-Token: runtime-secret",
        )

    record = caplog.records[0]
    assert record.poppy_event == AGENT_REGISTERED
    assert record.poppy_context == {"agent_id": "agent-1", "robot_id": "robot-1"}
    assert "bootstrap-secret" not in caplog.text
    assert "runtime-secret" not in caplog.text
    assert "payload" not in caplog.text


def test_json_formatter_emits_event_and_safe_context() -> None:
    logger = logging.getLogger("poppy_agent.test.formatter")
    record = logger.makeRecord(
        logger.name,
        logging.WARNING,
        __file__,
        1,
        SERVER_REQUEST_RETRY,
        (),
        None,
        extra={
            "poppy_event": SERVER_REQUEST_RETRY,
            "poppy_context": {"attempt": 2, "max_attempts": 3, "path": "/health?token=hidden"},
        },
    )

    formatted = json.loads(JsonFormatter().format(record))

    assert formatted["event"] == SERVER_REQUEST_RETRY
    assert formatted["context"] == {"attempt": 2, "max_attempts": 3, "path": "/health"}
    assert "hidden" not in formatted["context"]["path"]


def test_json_formatter_suppresses_unstructured_message_content() -> None:
    logger = logging.getLogger("poppy_agent.test.third_party")
    record = logger.makeRecord(
        logger.name,
        logging.ERROR,
        __file__,
        1,
        "request header contains X-Agent-Token=secret and payload=private",
        (),
        None,
    )

    formatted = json.loads(JsonFormatter().format(record))

    assert formatted["event"] == UNSTRUCTURED_LOG_SUPPRESSED
    assert "secret" not in json.dumps(formatted)
    assert "private" not in json.dumps(formatted)
