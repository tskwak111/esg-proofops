"""One run's physical HTTP queue; no grading, source admission or money grants."""

from collections import deque
from contextlib import contextmanager

from proofops.adapters.local.provider_concurrency import ProviderCircuitOpen, ProviderConcurrency
from proofops.application.provider_resilience import SCHEDULER_C24_POLICY, SCHEDULER_POLICY


class ProviderAdmissionDeferred(ValueError):
    """A physical attempt rejected before broker reservation or transport."""

    def __init__(self):
        super().__init__("OPENAI_HTTP_429")


class RoleProviderConcurrency(ProviderConcurrency):
    def __init__(self, workers, *, requests_per_second=4, scheduler_policy=None, **kwargs):
        self.policy = SCHEDULER_C24_POLICY if scheduler_policy is None else scheduler_policy
        if self.policy not in (SCHEDULER_POLICY, SCHEDULER_C24_POLICY):
            raise ValueError("PROVIDER_SCHEDULER_POLICY_MISMATCH")
        super().__init__(workers, **kwargs)
        if workers > self.policy["max_workers"]:
            raise ValueError("PROVIDER_CONCURRENCY_INVALID")
        if type(requests_per_second) is not int or not (
            1 <= requests_per_second <= self.policy["max_rps"]
        ):
            raise ValueError("HOSTED_LLM_RPS_INVALID")
        self.requests_per_second = requests_per_second
        self.queues = {role: deque() for role in self.policy["roles"]}
        self.physical_attempts = 0
        self.attempt_admissions = 0
        self.transport_not_before = 0.0
        self.sequence = 0
        self.queue_seconds = 0.0
        self.completed_by_role = dict.fromkeys(self.queues, 0)
        self.transport_starts = deque()

    def enqueue(self, role):
        if role not in self.queues:
            raise ValueError("PROVIDER_ROLE_INVALID")
        self.sequence += 1
        item = dict(role=role, queued=self.clock(), bypass=0, sequence=self.sequence)
        self.queues[role].append(item)
        self.condition.notify_all()
        return item

    def next_ticket(self):
        heads = [q[0] for q in self.queues.values() if q]
        if not heads:
            return None
        oldest = min(heads, key=lambda item: (item["queued"], item["sequence"]))
        return oldest if oldest["bypass"] >= self.policy["max_priority_bypass"] else heads[0]

    def dequeue(self, ticket):
        self.queues[ticket["role"]].remove(ticket)
        for queue in self.queues.values():
            for waiting in queue:
                waiting["bypass"] += 1

    @contextmanager
    def attempt(self, role, *, diagnostics=None):
        """Acquire immediately before each broker/HTTP attempt, release after it.

        Retry sleeps, JSON validation and persistence do not hold physical slots.
        A rejected admission proves no broker reservation or transport occurred.
        """
        with self.condition:
            ticket = self.enqueue(role)
            try:
                while True:
                    if self.circuit_open:
                        self.circuit_deferred += 1
                        raise ProviderCircuitOpen()
                    if self.deferred:
                        raise ProviderAdmissionDeferred()
                    current = self.clock()
                    if (
                        self.next_ticket() is ticket
                        and self.active < self.limit
                        and current >= max(self.not_before, self.http_not_before)
                    ):
                        self.dequeue(ticket)
                        self.active += 1
                        self.peak = max(self.peak, self.active)
                        self.attempt_admissions += 1
                        self.http_not_before = current + 1 / self.requests_per_second
                        wait = current - ticket["queued"]
                        self.queue_seconds += wait
                        record = dict(
                            role=role,
                            queued_monotonic=ticket["queued"],
                            admitted_monotonic=current,
                            queue_seconds=wait,
                        )
                        break
                    self.condition.wait(timeout=0.05)
            except BaseException:
                self.queues[role].remove(ticket)
                self.condition.notify_all()
                raise
        code = None
        uncertain = False
        if diagnostics is not None:
            diagnostics.setdefault("physical_attempts", []).append(record)
        try:
            yield
        except BaseException as error:
            from proofops.adapters.local.openai import OpenAITransient403
            from proofops.adapters.local.openai_connections import OpenAIConnectNotSent

            raw = str(error)
            uncertain = raw == "PROCESSING_UNCERTAIN" or (
                isinstance(error, OSError) and not isinstance(error, OpenAIConnectNotSent)
            )
            code = raw if raw.startswith("OPENAI_HTTP_") else "PROCESSING_UNCERTAIN"
            if isinstance(error, OpenAITransient403):
                code = "TRANSIENT_OVERLOAD"
            if raw == "OPENAI_HTTP_429":
                with self.condition:
                    self.rate_limits += 1
                    self.limit = max(1, self.limit // 2)
                    delay = getattr(error, "retry_after_seconds", None)
                    delay = self.cooldown_seconds if delay is None else delay
                    if delay > self.max_cooldown_seconds:
                        self.deferred = True
                    else:
                        self.not_before = max(self.not_before, self.clock() + delay)
            raise
        finally:
            try:
                # Persist K=3 outcomes before releasing the slot to queued work.
                if self.resilience_directory is not None:
                    self.observe(code, uncertain=uncertain)
                else:
                    with self.condition:
                        self._observe(code, uncertain=uncertain)
                record.update(finished_monotonic=self.clock(), error_code=code)
            finally:
                with self.condition:
                    self.active -= 1
                    self.completed_by_role[role] += 1
                    self.condition.notify_all()

    def pace_transport(self, diagnostics=None):
        # Broker/local reservation latency can reorder admissions. A second
        # timestamp at the transport boundary prevents HTTP starts bunching up.
        # Already admitted attempts keep their broker reservation and original
        # error semantics; circuit rejection happens before broker admission.
        with self.condition:
            while self.clock() < max(self.transport_not_before, self.not_before):
                if self.deferred:
                    raise ValueError("OPENAI_HTTP_429")
                self.condition.wait(timeout=0.05)
            if self.deferred:
                raise ValueError("OPENAI_HTTP_429")
            current = self.clock()
            self.transport_not_before = current + 1 / self.requests_per_second
            self.physical_attempts += 1
            self.transport_starts.append(current)
            while self.transport_starts and self.transport_starts[0] < current - 60:
                self.transport_starts.popleft()
            if diagnostics is not None:
                diagnostics["physical_attempts"][-1]["transport_started_monotonic"] = current
            return current

    def recent_requests(self):
        """Diagnostic counts only; do not add fields to historical snapshots."""
        with self.condition:
            current = self.clock()
            return dict(
                recent_requests_1s=sum(t > current - 1 for t in self.transport_starts),
                recent_requests_60s=sum(t > current - 60 for t in self.transport_starts),
            )

    def bind(self, probe):
        # This binding is explicitly selected by the S5 execution policy. The
        # normal F1 bind/call/pace path remains unchanged for old runs.
        if not hasattr(self, "connection_pool"):
            from proofops.adapters.local.openai_connections import OpenAIConnections

            self.connection_pool = OpenAIConnections()
        probe.connection_pool = self.connection_pool
        probe.http_admission_snapshot = self.snapshot
        probe.http_recent_request_counts = self.recent_requests
        probe.http_transport_pacing = lambda: self.pace_transport(probe._dispatch_context.get())
        probe.http_attempt_scope = lambda: self.attempt(
            (probe._response_context.get() or (probe.response_role, 0))[0],
            diagnostics=probe._dispatch_context.get(),
        )
        return probe

    def snapshot(self):
        with self.condition:
            return super().snapshot() | dict(
                scheduler=self.policy["profile"],
                requests_per_second=self.requests_per_second,
                physical_attempts=self.physical_attempts,
                attempt_admissions=self.attempt_admissions,
                queued_by_role={role: len(q) for role, q in self.queues.items()},
                completed_by_role=dict(self.completed_by_role),
                queue_seconds=self.queue_seconds,
                circuit_open=self.circuit_open,
                consecutive_denials=self.consecutive_denials,
            )
