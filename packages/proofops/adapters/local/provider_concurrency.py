"""One run's bounded HTTP admission; reservations remain owned by the providers."""

import time
from threading import Condition


class ProviderConcurrency:
    def __init__(
        self, workers, *, clock=time.monotonic, cooldown_seconds=1, max_cooldown_seconds=30
    ):
        if type(workers) is not int or not 1 <= workers <= 16:
            raise ValueError("PROVIDER_CONCURRENCY_INVALID")
        self.limit = workers
        self.clock = clock
        self.cooldown_seconds = cooldown_seconds
        self.max_cooldown_seconds = max_cooldown_seconds
        self.condition = Condition()
        self.active = self.peak = self.rate_limits = 0
        self.not_before = 0.0
        self.deferred = False

    def call(self, operation, *args, **kwargs):
        with self.condition:
            while self.active >= self.limit or self.clock() < self.not_before:
                if self.deferred:
                    raise ValueError("OPENAI_HTTP_429")
                self.condition.wait(timeout=0.1)
            if self.deferred:
                raise ValueError("OPENAI_HTTP_429")
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
        probe._post = lambda *a, **k: self.call(original, *a, **k)
        return probe

    def snapshot(self):
        with self.condition:
            return dict(
                limit=self.limit,
                active=self.active,
                peak=self.peak,
                rate_limits=self.rate_limits,
                deferred=self.deferred,
            )
