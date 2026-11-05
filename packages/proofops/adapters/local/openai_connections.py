"""Run-owned exclusive HTTP/1 connections. Failed or unread responses are discarded."""

from __future__ import annotations

import http.client
import ssl
import time
from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock
from typing import Any, cast
from uuid import uuid4

from proofops.application.openai_transport import POLICY
from proofops.application.ports.jobs import JobControlSignal, LeaseLost


class OpenAIControlNotSent(BaseException):
    """Typed proof of a control stop before request(); never a retry authorization."""

    def __init__(self, signal: JobControlSignal | LeaseLost) -> None:
        self.signal = signal
        super().__init__("OPENAI_CONTROL_NEVER_SENT")


@contextmanager
def control_before_send() -> Iterator[None]:
    """Use only around work that cannot write HTTP request bytes."""
    try:
        yield
    except (JobControlSignal, LeaseLost) as error:
        raise OpenAIControlNotSent(error) from None


class OpenAIConnectNotSent(OSError):
    """Created only around explicit connect(), before request() can write any HTTP bytes."""

    def __init__(self, diagnostic: dict[str, Any] | None) -> None:
        super().__init__("OPENAI_CONNECT_NEVER_SENT")
        self.diagnostic = diagnostic


class OpenAIConnections:
    def __init__(self) -> None:
        self.context = ssl.create_default_context()
        self.lock = Lock()
        self.idle: list[tuple[http.client.HTTPSConnection, str, float]] = []

    def take(self) -> tuple[http.client.HTTPSConnection, str, bool]:
        with self.lock:
            while self.idle:
                connection, identifier, released = self.idle.pop()
                if (
                    time.monotonic() - released <= cast(float, POLICY["idle_seconds"])
                    and connection.sock
                ):
                    return connection, identifier, True
                connection.close()
        return (
            http.client.HTTPSConnection("api.openai.com", timeout=90, context=self.context),
            str(uuid4()),
            False,
        )

    def release(self, connection: http.client.HTTPSConnection, identifier: str) -> None:
        with self.lock:
            if connection.sock and len(self.idle) < cast(int, POLICY["max_idle"]):
                self.idle.append((connection, identifier, time.monotonic()))
            else:
                connection.close()

    def close(self) -> None:
        with self.lock:
            for connection, _, _ in self.idle:
                connection.close()
            self.idle.clear()
