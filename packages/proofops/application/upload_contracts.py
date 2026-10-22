"""Upload verification errors, resource policies and immutable input/output records."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

HOSTED_NULL_NAVIGATION_PROFILE = "hosted-null-navigation-hx2-v1"
STRICT_PROFILES = frozenset({"strict-v1", HOSTED_NULL_NAVIGATION_PROFILE})


class UploadRejected(ValueError):
    """Code-only failure with optional structured inspection status; no source/parser text."""

    def __init__(self, code: str, *, security_metadata: dict | None = None):
        super().__init__(code)
        self.security_metadata = security_metadata or {}


@dataclass(frozen=True)
class PdfLimits:
    policy_profile: str = "strict-v1"
    max_expansion_ratio: int = 1000
    # Technical development limits, not corpus performance claims.
    max_bytes: int = 104_857_600
    max_pages: int = 300
    max_objects: int = 250_000
    max_decoded_bytes: int = 75_000_000
    timeout_seconds: float = 30
    memory_bytes: int = 512 * 1024 * 1024
    cpu_seconds: int = 20

    def __post_init__(self) -> None:
        if self.policy_profile not in {*STRICT_PROFILES, "display-v2"}:
            raise ValueError("Unsupported PDF security profile")
        for key, value in asdict(self).items():
            if key == "policy_profile":
                continue
            if (
                isinstance(value, bool)
                or not isinstance(value, float | int)
                or not math.isfinite(value)
                or value <= 0
                or (key != "timeout_seconds" and not isinstance(value, int))
            ):
                raise ValueError("Positive finite resource limits required")

    @classmethod
    def display(cls, **overrides) -> PdfLimits:
        """New-upload profile; legacy defaults remain byte-for-byte strict in behavior."""
        values: dict[str, Any] = dict(
            policy_profile="display-v2",
            max_objects=250_000,
            max_decoded_bytes=512 * 1024 * 1024,
            memory_bytes=1024 * 1024 * 1024,
            cpu_seconds=60,
            timeout_seconds=90,
        )
        values.update(overrides)
        return cls(**values)


@dataclass(frozen=True)
class QuarantinedPdf:
    tenant_id: str
    document_version_id: str
    object_version_id: str
    content: bytes = field(repr=False)
    expected_size: int
    expected_sha256: str


@dataclass(frozen=True)
class VerifiedPdf:
    source: QuarantinedPdf
    page_count: int
    display_content: bytes | None = field(default=None, repr=False)
    security_metadata: dict = field(default_factory=dict)
    analysis_content: bytes | None = field(default=None, repr=False)
