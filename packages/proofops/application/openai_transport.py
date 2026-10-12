"""Explicit K10 transport selection; no exception-name inference of delivery."""

POLICY = dict(
    profile="openai-connection-reuse-k10-v1",
    pool="run-owned-exclusive-http1-idle16-ttl30; shared-verified-TLS-context",
    retry="one-explicit-connect-failure-before-request-start; fresh-attempt-reservation",
    unknown="request-started-or-response-failed; retain-full-cost-and-claim-hold",
    attempts="immutable-attempt-identity; logical-envelope-remains-reserved",
    max_idle=16,
    idle_seconds=30,
)
