"""Strict parser and serializer for High-level Command Protocol v1."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any, NoReturn, cast

from poppy_agent.command.models import (
    CommandParameters,
    CommandType,
    HighLevelCommand,
    HighLevelCommandProgram,
    MoveDirection,
    MoveParameters,
    Posture,
    PostureParameters,
    PresetParameters,
    StopParameters,
    TurnDirection,
    TurnParameters,
    WaitParameters,
)

SUPPORTED_PROTOCOL_VERSION = 1


class CommandProtocolParseError(ValueError):
    """Raised when a Command Protocol v1 document violates its contract."""


class HighLevelCommandProtocolParser:
    """Parse a Server Command Protocol v1 document without JSON coercion."""

    def parse(self, document: str) -> HighLevelCommandProgram:
        try:
            raw = json.loads(document, parse_constant=_reject_non_finite_constant)
        except (TypeError, ValueError) as exc:
            raise CommandProtocolParseError("command protocol JSON is malformed") from exc

        root = _object(raw, "program")
        _exact_keys(root, {"protocolVersion", "commands"}, "program")
        protocol_version = _integer(root.get("protocolVersion"), "protocolVersion")
        if protocol_version != SUPPORTED_PROTOCOL_VERSION:
            raise CommandProtocolParseError(f"unsupported protocolVersion: {protocol_version}")

        commands_value = root.get("commands")
        if not isinstance(commands_value, list):
            raise CommandProtocolParseError("commands must be an array")
        commands = tuple(
            self._parse_command(index, raw_command)
            for index, raw_command in enumerate(commands_value)
        )
        return HighLevelCommandProgram(protocol_version, commands)

    def _parse_command(self, index: int, raw: object) -> HighLevelCommand:
        command = _object(raw, "command")
        _exact_keys(command, {"sequence", "sourceBlockId", "type", "parameters"}, "command")
        sequence = _integer(command.get("sequence"), "sequence")
        if sequence != index:
            raise CommandProtocolParseError("sequence must be contiguous from zero")

        source_block_id = command.get("sourceBlockId")
        if not isinstance(source_block_id, str) or not source_block_id.strip():
            raise CommandProtocolParseError("sourceBlockId must be a non-blank string")

        raw_type = command.get("type")
        if not isinstance(raw_type, str):
            raise CommandProtocolParseError("type must be a string")
        try:
            command_type = CommandType(raw_type)
        except ValueError as exc:
            raise CommandProtocolParseError(f"unknown command type: {raw_type}") from exc

        parameters = self._parse_parameters(command_type, command.get("parameters"))
        return HighLevelCommand(sequence, source_block_id, command_type, parameters)

    def _parse_parameters(self, command_type: CommandType, raw: object) -> CommandParameters:
        parameters = _object(raw, "parameters")
        if command_type is CommandType.WAIT:
            _exact_keys(parameters, {"durationSeconds"}, "WAIT parameters")
            return WaitParameters(_number(parameters.get("durationSeconds"), "durationSeconds"))
        if command_type is CommandType.MOVE:
            _exact_keys(parameters, {"direction", "distanceMeters"}, "MOVE parameters")
            return MoveParameters(
                _enum(parameters.get("direction"), MoveDirection, "direction"),
                _number(parameters.get("distanceMeters"), "distanceMeters"),
            )
        if command_type is CommandType.TURN:
            _exact_keys(parameters, {"direction", "angleDegrees"}, "TURN parameters")
            return TurnParameters(
                _enum(parameters.get("direction"), TurnDirection, "direction"),
                _number(parameters.get("angleDegrees"), "angleDegrees"),
            )
        if command_type is CommandType.STOP:
            _exact_keys(parameters, set(), "STOP parameters")
            return StopParameters()
        if command_type is CommandType.POSTURE:
            _exact_keys(parameters, {"posture"}, "POSTURE parameters")
            return PostureParameters(_enum(parameters.get("posture"), Posture, "posture"))
        _exact_keys(parameters, {"presetCode"}, "PRESET parameters")
        preset_code = parameters.get("presetCode")
        if not isinstance(preset_code, str) or not preset_code.strip():
            raise CommandProtocolParseError("presetCode must be a non-blank string")
        return PresetParameters(preset_code)


def serialize_command_program(program: HighLevelCommandProgram) -> str:
    """Serialize a typed program using the v1 wire field names."""
    _validate_program_model(program)
    return json.dumps(program_to_dict(program), ensure_ascii=False, separators=(",", ":"))


def program_to_dict(program: HighLevelCommandProgram) -> dict[str, object]:
    """Convert a typed program to its protocol field names."""
    return {
        "protocolVersion": program.protocol_version,
        "commands": [command_to_dict(command) for command in program.commands],
    }


def command_to_dict(command: HighLevelCommand) -> dict[str, object]:
    return {
        "sequence": command.sequence,
        "sourceBlockId": command.source_block_id,
        "type": command.type.value,
        "parameters": parameters_to_dict(command.parameters),
    }


def parameters_to_dict(parameters: CommandParameters) -> dict[str, object]:
    if isinstance(parameters, WaitParameters):
        return {"durationSeconds": parameters.duration_seconds}
    if isinstance(parameters, MoveParameters):
        return {
            "direction": parameters.direction.value,
            "distanceMeters": parameters.distance_meters,
        }
    if isinstance(parameters, TurnParameters):
        return {"direction": parameters.direction.value, "angleDegrees": parameters.angle_degrees}
    if isinstance(parameters, StopParameters):
        return {}
    if isinstance(parameters, PostureParameters):
        return {"posture": parameters.posture.value}
    return {"presetCode": parameters.preset_code}


def _validate_program_model(program: HighLevelCommandProgram) -> None:
    if (
        type(program.protocol_version) is not int
        or program.protocol_version != SUPPORTED_PROTOCOL_VERSION
    ):
        raise CommandProtocolParseError("unsupported protocolVersion")
    for index, command in enumerate(program.commands):
        if type(command.sequence) is not int or command.sequence != index:
            raise CommandProtocolParseError("sequence must be contiguous from zero")
        if not isinstance(command.source_block_id, str) or not command.source_block_id.strip():
            raise CommandProtocolParseError("sourceBlockId must be a non-blank string")
        _validate_parameters(command)


def _validate_parameters(command: HighLevelCommand) -> None:
    parameters = command.parameters
    valid = (
        (
            command.type is CommandType.WAIT
            and isinstance(parameters, WaitParameters)
            and _finite_number(parameters.duration_seconds)
        )
        or (
            command.type is CommandType.MOVE
            and isinstance(parameters, MoveParameters)
            and isinstance(parameters.direction, MoveDirection)
            and _finite_number(parameters.distance_meters)
        )
        or (
            command.type is CommandType.TURN
            and isinstance(parameters, TurnParameters)
            and isinstance(parameters.direction, TurnDirection)
            and _finite_number(parameters.angle_degrees)
        )
        or (command.type is CommandType.STOP and isinstance(parameters, StopParameters))
        or (
            command.type is CommandType.POSTURE
            and isinstance(parameters, PostureParameters)
            and isinstance(parameters.posture, Posture)
        )
        or (
            command.type is CommandType.PRESET
            and isinstance(parameters, PresetParameters)
            and isinstance(parameters.preset_code, str)
            and bool(parameters.preset_code.strip())
        )
    )
    if not valid:
        raise CommandProtocolParseError("command parameters do not match command type")


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise CommandProtocolParseError(f"{name} must be an object")
    return value


def _exact_keys(value: Mapping[str, object], expected: set[str], name: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        detail = []
        if missing:
            detail.append(f"missing {missing}")
        if unknown:
            detail.append(f"unknown {unknown}")
        raise CommandProtocolParseError(f"{name} fields are invalid: {', '.join(detail)}")


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise CommandProtocolParseError(f"{name} must be an integer")
    return value


def _number(value: object, name: str) -> float:
    if type(value) not in (int, float):
        raise CommandProtocolParseError(f"{name} must be a finite JSON number")
    try:
        if type(value) is int:
            converted = float(value)
        else:
            converted = cast(float, value)
    except (OverflowError, ValueError) as exc:
        raise CommandProtocolParseError(f"{name} must be a finite JSON number") from exc
    if not math.isfinite(converted):
        raise CommandProtocolParseError(f"{name} must be a finite JSON number")
    return converted


def _enum(value: object, enum_type: type[Any], name: str) -> Any:
    if not isinstance(value, str):
        raise CommandProtocolParseError(f"{name} must be a string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise CommandProtocolParseError(f"{name} has an invalid value") from exc


def _finite_number(value: object) -> bool:
    if type(value) is int:
        try:
            return math.isfinite(float(value))
        except (OverflowError, ValueError):
            return False
    return type(value) is float and math.isfinite(value)


def _reject_non_finite_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")
