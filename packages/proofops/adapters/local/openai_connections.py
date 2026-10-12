"""Run-owned exclusive HTTP/1 connections. Failed or unread responses are discarded."""

import http.client
import ssl
import time
from threading import Lock
from uuid import uuid4

from proofops.application.openai_transport import POLICY


class OpenAIConnectNotSent(OSError):
    """Created only around explicit connect(), before request() can write any HTTP bytes."""

    def __init__(self, diagnostic):
        super().__init__("OPENAI_CONNECT_NEVER_SENT")
        self.diagnostic = diagnostic


class OpenAIConnections:
    def __init__(self):
        self.context = ssl.create_default_context()
        self.lock = Lock()
        self.idle = []

    def take(self):
        with self.lock:
            while self.idle:
                connection, identifier, released = self.idle.pop()
                if time.monotonic() - released <= POLICY["idle_seconds"] and connection.sock:
                    return connection, identifier, True
                connection.close()
        return (
            http.client.HTTPSConnection("api.openai.com", timeout=90, context=self.context),
            str(uuid4()),
            False,
        )

    def release(self, connection, identifier):
        with self.lock:
            if connection.sock and len(self.idle) < POLICY["max_idle"]:
                self.idle.append((connection, identifier, time.monotonic()))
            else:
                connection.close()

    def close(self):
        with self.lock:
            for connection, _, _ in self.idle:
                connection.close()
            self.idle.clear()
