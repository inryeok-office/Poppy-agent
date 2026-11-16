"""Deterministic Robot pose double for closed-loop tests; nothing reaches DDS."""

from __future__ import annotations

import math
from collections.abc import Callable

from poppy_agent.robot.adapter import SportStateSample


class SimulatedRobot:
    """Integrate the last ``Move`` on a fake clock.

    ``gain`` scales what the Robot really does, ``start_delay`` models the gait
    starting late and ``drift`` adds sideways speed in meters per second.
    """

    def __init__(
        self,
        clock: Callable[[], float],
        *,
        gain: float = 1.0,
        start_delay: float = 0.0,
        drift: float = 0.0,
        yaw_degrees: float = 0.0,
    ) -> None:
        self._clock = clock
        self.gain = gain
        self.start_delay = start_delay
        self.drift = drift
        self.x = 0.0
        self.y = 0.0
        self.yaw = math.radians(yaw_degrees)
        self.stale_after_reads: int | None = None
        self.reads = 0
        self._vx = 0.0
        self._vyaw = 0.0
        self._moving_since: float | None = None
        self._last = clock()

    def command(self, vx: float, vyaw: float) -> None:
        self._integrate()
        if self._moving_since is None:
            self._moving_since = self._clock()
        self._vx, self._vyaw = vx, vyaw

    def stop(self) -> None:
        self._integrate()
        self._vx = self._vyaw = 0.0
        self._moving_since = None

    def state(self) -> SportStateSample | None:
        self._integrate()
        self.reads += 1
        if self.stale_after_reads is not None and self.reads > self.stale_after_reads:
            return None
        wrapped = (self.yaw + math.pi) % math.tau - math.pi
        return SportStateSample(self.x, self.y, wrapped, 1, 1)

    def _integrate(self) -> None:
        now = self._clock()
        seconds = now - self._last
        self._last = now
        if self._moving_since is None or now - self._moving_since < self.start_delay:
            return
        forward = self._vx * self.gain * seconds
        self.x += forward * math.cos(self.yaw) - self.drift * seconds * math.sin(self.yaw)
        self.y += forward * math.sin(self.yaw) + self.drift * seconds * math.cos(self.yaw)
        self.yaw += self._vyaw * self.gain * seconds
