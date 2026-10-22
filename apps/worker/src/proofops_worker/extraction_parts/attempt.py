"""Shared per-attempt authority and usage; selection and lease order stay caller-owned."""

from datetime import UTC, datetime
from threading import Lock

from proofops.application.authorization import AuthContext


def authorize_attempt(runner, snapshot, graph, profile, *, tenant_id, run_id, check_binding):
    authorization = check_binding(
        binding=snapshot["runtime"],
        consent=snapshot["consent"],
        auth=AuthContext("local-worker", tenant_id, "viewer", frozenset(), run_id),
        checked_at=datetime.fromtimestamp(runner.clock(), UTC).isoformat(),
        source_sha256=graph.source_sha256,
        model_sha256=profile.model_sha256,
    )
    if not authorization.ready:
        raise ValueError("LOCAL_TEST_AUTHORIZATION_INVALID")


class ExtractionAttemptContext:
    def __init__(self, runner, snapshot, usage, *, is_real=False, since=0, manifest_id=None):
        self.runner = runner
        self.snapshot = snapshot
        self.usage = usage
        self.is_real = is_real
        self.since = since
        self.manifest_id = manifest_id
        self.lock = Lock()

    def sync_usage(self):
        if self.is_real:
            with self.lock:
                self.usage.update(
                    self.runner.extractor.cumulative_usage(
                        since=self.since, parse_manifest_id=self.manifest_id
                    )
                )

    def admit(self, graph, profile, *, tenant_id, run_id, admit, check_binding):
        if not admit(self.runner, self.snapshot, "extract"):
            return False
        if self.is_real:
            authorize_attempt(
                self.runner,
                self.snapshot,
                graph,
                profile,
                tenant_id=tenant_id,
                run_id=run_id,
                check_binding=check_binding,
            )
        return True
