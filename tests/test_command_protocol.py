import json
from pathlib import Path

import pytest

from poppy_agent.command import (
    CommandProtocolParseError,
    CommandType,
    HighLevelCommandProtocolParser,
    MoveDirection,
    Posture,
    TurnDirection,
    serialize_command_program,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "high_level_command_v1.json"


def test_server_contract_fixture_parses_with_typed_parameters() -> None:
    program = HighLevelCommandProtocolParser().parse(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert program.protocol_version == 1
    assert [command.type for command in program.commands] == list(CommandType)
    assert program.commands[1].parameters.direction is MoveDirection.FORWARD
    assert program.commands[2].parameters.direction is TurnDirection.LEFT
    assert program.commands[4].parameters.posture is Posture.SIT


def test_empty_command_program_is_valid() -> None:
    program = HighLevelCommandProtocolParser().parse('{"protocolVersion":1,"commands":[]}')

    assert program.commands == ()


def test_round_trip_preserves_typed_program() -> None:
    parser = HighLevelCommandProtocolParser()
    program = parser.parse(FIXTURE_PATH.read_text(encoding="utf-8"))

    serialized = serialize_command_program(program)
    reparsed = parser.parse(serialized)

    assert reparsed == program
    assert json.loads(serialized) == json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "document",
    [
        "not-json",
        '{"protocolVersion":2,"commands":[]}',
        '{"protocolVersion":true,"commands":[]}',
        '{"protocolVersion":1,"commands":{}}',
        '{"protocolVersion":1,"commands":[],"extra":true}',
        '{"protocolVersion":1,"commands":[{"sequence":1,"sourceBlockId":"x","type":"STOP","parameters":{}}]}',
        (
            '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":" ",'
            '"type":"STOP","parameters":{}}]}'
        ),
        '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x","type":"UNKNOWN","parameters":{}}]}',
        '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x","type":"STOP"}]}',
        '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x","type":"STOP","parameters":{"unexpected":1}}]}',
        '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x","type":"WAIT","parameters":{"durationSeconds":"1.0"}}]}',
        '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x","type":"WAIT","parameters":{"durationSeconds":true}}]}',
        '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x","type":"MOVE","parameters":{"direction":"FORWARD","distanceMeters":NaN}}]}',
        '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x","type":"MOVE","parameters":{"direction":"FORWARD","distanceMeters":1,"speed":2}}]}',
        '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x","type":"MOVE","parameters":{"direction":"SIDEWAYS","distanceMeters":1}}]}',
        '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x","type":"STOP","parameters":{"reason":"x"}}]}',
        (
            '{"protocolVersion":1,"commands":[{"sequence":0,"sourceBlockId":"x",'
            '"type":"PRESET","parameters":{"presetCode":" "}}]}'
        ),
    ],
)
def test_parser_rejects_invalid_contract(document: str) -> None:
    with pytest.raises(CommandProtocolParseError):
        HighLevelCommandProtocolParser().parse(document)
