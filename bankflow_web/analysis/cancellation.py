"""Cooperative cancellation shared by analysis frontends."""

from __future__ import annotations

import threading


class CancellationToken:
    def __init__(self) -> None:
        self._requested = threading.Event()

    def request(self) -> None:
        self._requested.set()

    @property
    def requested(self) -> bool:
        return self._requested.is_set()
