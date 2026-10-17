"""One run's bounded HTTP admission; reservations remain owned by the providers."""

import json
import os
import time
from pathlib import Path
from threading import Condition


class ProviderCircuitOpen(ValueError):
    """Admission rejected before the provider transport/broker reservation."""

    def __init__(self):
        super().__init__("PROVIDER_CIRCUIT_OPEN")


class ProviderConcurrency:
    def __init__(
        self,
        workers,
        *,
        clock=time.monotonic,
        cooldown_seconds=1,
        max_cooldown_seconds=30,
        resilience_directory=None,
    ):
        if type(workers) is not int or not 1 <= workers <= 24:
            raise ValueError("PROVIDER_CONCURRENCY_INVALID")
        self.limit = workers
        self.clock = clock
        self.cooldown_seconds = cooldown_seconds
        self.max_cooldown_seconds = max_cooldown_seconds
        self.condition = Condition()
        self.active = self.peak = self.rate_limits = 0
        self.not_before = 0.0
        self.deferred = False
        self.resilience_directory = Path(resilience_directory) if resilience_directory else None
        self.consecutive_denials = self.failed_calls = self.circuit_deferred = 0
        self.uncertain_calls = 0
        self.circuit_open = False
        self.events = 0
        self.http_not_before = 0.0
        if self.resilience_directory is not None:
            self.resilience_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            for path in sorted(self.resilience_directory.glob("*.json")):
                event = json.loads(path.read_text())
                self._observe(event["code"], uncertain=event.get("uncertain") is True)
                self.events += 1

    def _observe(self, code, *, uncertain=False):
        from proofops.application.provider_resilience import POLICY

        if code is not None:
            self.failed_calls += 1
            self.uncertain_calls += int(uncertain)
        self.consecutive_denials = self.consecutive_denials + 1 if code == "OPENAI_HTTP_403" else 0
        self.circuit_open |= self.consecutive_denials >= POLICY["consecutive_denials"]

    def observe(self, code, *, uncertain=False):
        with self.condition:
            event = dict(code=code, observed_at_ns=time.time_ns())
            if uncertain:
                event["uncertain"] = True
            path = self.resilience_directory / f"{self.events + 1:08}.json"
            with path.open("x") as stream:
                json.dump(event, stream)
                stream.flush()
                os.fsync(stream.fileno())
            path.chmod(0o400)
            self.events += 1
            self._observe(code, uncertain=uncertain)
            self.condition.notify_all()

    def pace_http(self):
        from proofops.application.provider_resilience import POLICY

        with self.condition:
            while self.clock() < self.http_not_before:
                if self.circuit_open:
                    self.circuit_deferred += 1
                    raise ProviderCircuitOpen()
                self.condition.wait(timeout=0.05)
            if self.circuit_open:
                self.circuit_deferred += 1
                raise ProviderCircuitOpen()
            self.http_not_before = self.clock() + 1 / POLICY["requests_per_second"]

    def call(self, operation, *args, **kwargs):
        with self.condition:
            while self.active >= self.limit or self.clock() < self.not_before:
                if self.circuit_open:
                    self.circuit_deferred += 1
                    raise ValueError("PROVIDER_CIRCUIT_OPEN")
                if self.deferred:
                    raise ValueError("OPENAI_HTTP_429")
                self.condition.wait(timeout=0.1)
            if self.deferred:
                raise ValueError("OPENAI_HTTP_429")
            if self.circuit_open:
                self.circuit_deferred += 1
                raise ValueError("PROVIDER_CIRCUIT_OPEN")
            if self.resilience_directory is not None:
                from proofops.application.provider_resilience import POLICY

                self.not_before = self.clock() + 1 / POLICY["requests_per_second"]
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            return operation(*args, **kwargs)
        except ValueError as error:
            if str(error) == "OPENAI_HTTP_429":
                with self.condition:
                    self.rate_limits += 1
                    self.limit = max(1, self.limit // 2)
                    delay = getattr(error, "retry_after_seconds", None)
                    delay = self.cooldown_seconds if delay is None else delay
                    if delay > self.max_cooldown_seconds:
                        self.deferred = True
                    else:
                        self.not_before = max(self.not_before, self.clock() + delay)
            # Never retry a paid/uncertain dispatch here. The provider's immutable
            # failed receipt and original reservation remain authoritative.
            raise
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()

    def bind(self, probe):
        original = probe._post
        probe.http_admission_snapshot = self.snapshot
        if self.resilience_directory is None:
            probe._post = lambda *a, **k: self.call(original, *a, **k)
        else:
            # Admit before the local reservation, including queued circuit checks.
            # T1's single retry stays inside this admission and remains brokered.
            complete = probe._complete_uncached
            probe._complete_uncached = lambda *a, **k: self.call(complete, *a, **k)
            probe.http_dispatch_admission = self.pace_http

            def observed_post(*a, **k):
                from proofops.adapters.local.openai import OpenAITransient403
                from proofops.adapters.local.openai_connections import OpenAIConnectNotSent
                from proofops.application.provider_resilience import POLICY

                if not getattr(probe, "http_dispatch_guard", False):
                    with self.condition:
                        while self.clock() < self.http_not_before:
                            self.condition.wait(timeout=0.05)
                        self.http_not_before = self.clock() + 1 / POLICY["requests_per_second"]

                try:
                    result = original(*a, **k)
                except (ValueError, OSError) as error:
                    if isinstance(error, ProviderCircuitOpen):
                        raise
                    raw = str(error)
                    code = raw if raw.startswith("OPENAI_HTTP_") else "PROCESSING_UNCERTAIN"
                    if isinstance(error, OpenAITransient403):
                        code = "TRANSIENT_OVERLOAD"
                    self.observe(
                        code,
                        uncertain=raw == "PROCESSING_UNCERTAIN"
                        or isinstance(error, OSError)
                        and not isinstance(error, OpenAIConnectNotSent),
                    )
                    raise
                self.observe(None)
                return result

            probe._post = observed_post
        return probe

    def snapshot(self):
        with self.condition:
            result = dict(
                limit=self.limit,
                active=self.active,
                peak=self.peak,
                rate_limits=self.rate_limits,
                deferred=self.deferred,
            )
            if self.resilience_directory is not None:
                result.update(
                    circuit_open=self.circuit_open,
                    failed_calls=self.failed_calls,
                    circuit_deferred=self.circuit_deferred,
                    consecutive_denials=self.consecutive_denials,
                    requests_per_second=4,
                )
            return result
