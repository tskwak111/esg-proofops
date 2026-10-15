"""Request-local SC1 failure attribution, shared only inside one hosted run."""

import re
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock

from proofops.application.i27_inventory import POLICY

current = ContextVar("i27_sc1_request", default=None)


def transient_code(error):
    if getattr(error, "provider_error_code", None) == "billing_not_active":
        return None
    if re.fullmatch(r"OPENAI_HTTP_5\d\d", str(error)):
        return str(error)
    return "SC1_PROVIDER_TIMEOUT" if isinstance(error, TimeoutError) else None


class Failures:
    def __init__(self):
        self.lock = Lock()
        self.requests = {}

    def record(self, request):
        if request["attempts"]:
            with self.lock:
                self.requests[request["request_id"]] = request.copy()

    def summary(self):
        with self.lock:
            requests = sorted(self.requests.values(), key=lambda r: r["request_id"])
            return dict(
                profile=POLICY["profile"],
                optional_failed_calls=sum(len(r["attempts"]) for r in requests),
                requests=requests,
            )


@contextmanager
def request_scope(policy, original, failures):
    if policy != POLICY or not isinstance(failures, Failures):
        raise ValueError("I27_SC1_FAILURE_POLICY_MISMATCH")
    request = dict(
        request_id=original["request_id"],
        chunk_sha256=original["packet_sha256"],
        replicate_id=original["replicate_id"],
        attempts=[],
        retries=0,
        degraded=False,
        terminal_code=None,
    )
    token = current.set(request)
    try:
        yield request
    finally:
        failures.record(request)
        current.reset(token)
