"""Typed models for High-level Command Protocol v1."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias


class CommandType(StrEnum):
    WAIT = "WAIT"
    MOVE = "MOVE"
    TURN = "TURN"
    STOP = "STOP"
    POSTURE = "POSTURE"
    PRESET = "PRESET"


class MoveDirection(StrEnum):
    FORWARD = "FORWARD"
    BACKWARD = "BACKWARD"


class TurnDirection(StrEnum):
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class Posture(StrEnum):
    SIT = "SIT"
    STAND = "STAND"


@dataclass(frozen=True, slots=True)
class WaitParameters:
    duration_seconds: float


@dataclass(frozen=True, slots=True)
class MoveParameters:
    direction: MoveDirection
    distance_meters: float


@dataclass(frozen=True, slots=True)
class TurnParameters:
    direction: TurnDirection
    angle_degrees: float


@dataclass(frozen=True, slots=True)
class StopParameters:
    pass


@dataclass(frozen=True, slots=True)
class PostureParameters:
    posture: Posture


@dataclass(frozen=True, slots=True)
class PresetParameters:
    preset_code: str


CommandParameters: TypeAlias = (
    WaitParameters
    | MoveParameters
    | TurnParameters
    | StopParameters
    | PostureParameters
    | PresetParameters
)


@dataclass(frozen=True, slots=True)
class HighLevelCommand:
    sequence: int
    source_block_id: str
    type: CommandType
    parameters: CommandParameters


@dataclass(frozen=True, slots=True)
class HighLevelCommandProgram:
    protocol_version: int
    commands: tuple[HighLevelCommand, ...]
