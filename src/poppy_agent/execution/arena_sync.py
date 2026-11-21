"""Periodic arena refresh from Poppy-Server for the open motion guard.

Fail-safe rules:
* The environment baseline is the approved limit.  A remote arena can only narrow it.
* Without a valid remote value — before the first fetch, on any error, or for an invalid or
  wider payload — the guard uses the **baseline**, never the last received value.
* Updates are applied between Executions only (see ``OpenMotionGuard.apply_arena``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from threading import Event

from poppy_agent.config.arena_override import narrow_arena
from poppy_agent.config.open_motion import OpenMotionSettings
from poppy_agent.execution.open_motion import OpenMotionGuard

logger = logging.getLogger(__name__)

DEFAULT_SYNC_INTERVAL_SECONDS = 30.0
MIN_SYNC_INTERVAL_SECONDS = 5.0


class ArenaSettingsSync:
    """Fetch, narrow-check and apply the Server arena; fall back to the baseline."""

    def __init__(
        self,
        *,
        baseline: OpenMotionSettings,
        guard: OpenMotionGuard,
        fetch: Callable[[], Mapping[str, object]],
    ) -> None:
        self._baseline = baseline
        self._guard = guard
        self._fetch = fetch
        self.last_source = "baseline"
        self.last_reason: str | None = "not fetched yet"

    def refresh_once(self) -> bool:
        """One fetch; returns True when a Server arena (narrower or equal) is in effect."""
        try:
            payload = self._fetch()
        except Exception as exc:  # any transport/response error → baseline, never the last value
            self._use_baseline(f"fetch failed: {type(exc).__name__}")
            return False
        decision = narrow_arena(self._baseline, payload)
        if not decision.accepted:
            self._use_baseline(f"rejected: {decision.reason}")
            return False
        self._guard.apply_arena(decision.settings)
        if self.last_source != "server":
            logger.warning(
                "arena settings from Server in effect: %.2f x %.2f m, margin %.2f m, "
                "max move %.1f m",
                decision.settings.arena_width_meters,
                decision.settings.arena_depth_meters,
                decision.settings.arena_margin_meters,
                decision.settings.max_move_meters_per_command,
            )
        self.last_source = "server"
        self.last_reason = None
        return True

    def run(
        self, stop_event: Event, interval_seconds: float = DEFAULT_SYNC_INTERVAL_SECONDS
    ) -> None:
        interval = max(interval_seconds, MIN_SYNC_INTERVAL_SECONDS)
        while not stop_event.is_set():
            self.refresh_once()
            stop_event.wait(interval)

    def _use_baseline(self, reason: str) -> None:
        self._guard.apply_arena(self._baseline)
        if self.last_source != "baseline" or self.last_reason != reason:
            logger.warning("arena settings: using the approved baseline (%s)", reason)
        self.last_source = "baseline"
        self.last_reason = reason


__all__ = ["ArenaSettingsSync", "DEFAULT_SYNC_INTERVAL_SECONDS", "MIN_SYNC_INTERVAL_SECONDS"]
