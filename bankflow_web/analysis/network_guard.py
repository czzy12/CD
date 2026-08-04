"""Default-deny Python network boundary for formal offline analysis."""

from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import socket
import threading
from typing import Callable, Iterator


_NETWORK_GUARD_LOCK = threading.RLock()


@contextmanager
def external_network_disabled() -> Iterator[None]:
    with _NETWORK_GUARD_LOCK:
        original_connect = socket.socket.connect
        original_create_connection = socket.create_connection

        def blocked(*_args, **_kwargs):
            raise RuntimeError("分析任务已禁用外部网络连接")

        socket.socket.connect = blocked
        socket.create_connection = blocked
        try:
            yield
        finally:
            socket.socket.connect = original_connect
            socket.create_connection = original_create_connection


def offline_analysis(function: Callable):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if kwargs.pop("allow_external_network", False):
            return function(*args, **kwargs)
        with external_network_disabled():
            return function(*args, **kwargs)

    return wrapped
