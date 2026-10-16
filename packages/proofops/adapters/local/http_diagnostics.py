"""Safe E05 error metadata. No raw body, URL, socket, key or cookie storage."""

import re

from proofops.application.provider_resilience import HTTP_DIAGNOSTIC_POLICY
from proofops.domain.provenance import canonical_hash

RESPONSE_HEADERS = (
    "server",
    "cf-ray",
    "x-request-id",
    "retry-after",
    "content-type",
    "content-length",
)


def safe_header(value, secret):
    return (
        value
        if isinstance(value, str)
        and len(value) <= 160
        and re.fullmatch(r"[a-zA-Z0-9 .,;:=/+_-]+", value)
        and secret not in value
        and "sk-" not in value
        else None
    )


def safe_id(value, secret):
    return (
        value
        if isinstance(value, str)
        and re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", value)
        and secret not in value
        and not value.startswith("sk-")
        else None
    )


def error_context(probe, trace, response, client_request_id):
    secret = probe._key
    context = probe._response_context.get() or (probe.response_role, None)
    job = getattr(probe, "job", {})
    dispatch = probe._dispatch_context.get() or {}
    return trace | dict(
        diagnostic_policy_sha256=canonical_hash(HTTP_DIAGNOSTIC_POLICY),
        role=context[0],
        replica=context[1],
        reservation_id=safe_id(client_request_id, secret),
        run_id=safe_id(job.get("run_id"), secret),
        job_id=safe_id(job.get("job_id"), secret),
        tenant_id=safe_id((probe.response_policy or {}).get("tenant_id"), secret),
        source_sha256=(probe.response_policy or {}).get("source_sha256"),
        analysis_policy_sha256=(probe.response_policy or {}).get("analysis_policy_sha256"),
        physical_attempt=len(dispatch.get("physical_attempts", [])) or None,
        http_version={10: "HTTP/1.0", 11: "HTTP/1.1"}.get(getattr(response, "version", None)),
        response_received=response is not None,
        headers={
            name: value
            for name in RESPONSE_HEADERS
            if response is not None
            and (value := safe_header(response.getheader(name), secret)) is not None
        },
        **(
            probe.http_recent_request_counts()
            if hasattr(probe, "http_recent_request_counts")
            else dict(recent_requests_1s=None, recent_requests_60s=None)
        ),
    )
