"""Shared hosted errors, identifiers, amounts, file checks and settings."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol
from uuid import UUID
from zoneinfo import ZoneInfo

from proofops.application.authorization import AuthContext, MembershipPort, SessionPort
from proofops.domain.documents import PageGeometry


class ScopeSelectionValidator(Protocol):
    def __call__(
        self,
        plan: dict[str, Any],
        source_sha256: str,
        page_count: int,
        *,
        manual_override: bool = False,
        manual_selection: bool = False,
    ) -> dict[str, Any]: ...


class DiscoveryReaderFactory(Protocol):
    def __call__(
        self,
        pdf: Path,
        *,
        tenant_id: str,
        cache_dir: Path,
        source_sha256: str | None = None,
    ) -> Callable[[int], dict[str, Any]]: ...


MICRO = Decimal(1_000_000)
RUN_LEASE_SECONDS = 1900


TERMINAL = ("partial_blocked", "completed", "cancelled", "failed")
OPENROUTER_LIMIT_CODES = frozenset({"OPENROUTER_HTTP_402", "OPENROUTER_HTTP_403"})
OPENAI_LIMIT_CODES = frozenset({"OPENAI_HTTP_401", "OPENAI_HTTP_429", "OPENAI_INSUFFICIENT_QUOTA"})
PROVIDER_LIMIT_CODES = {
    "openrouter": OPENROUTER_LIMIT_CODES,
    "openai": OPENAI_LIMIT_CODES,
}
ALL_PROVIDER_LIMIT_CODES = OPENROUTER_LIMIT_CODES | OPENAI_LIMIT_CODES
PROVIDER_LIMIT_MESSAGE = "분석 서비스 한도 초과 — 운영자 확인 필요"
CONTROL_MESSAGES = {
    "MAINTENANCE": "서버 점검 중입니다. 진행 중 분석은 계속 처리하며 새 분석은 점검 후 접수합니다.",
    "LEASE_EXPIRED": (
        "서버 재시작 또는 작업 응답 중단으로 분석이 중단되었습니다. "
        "전송 기록이 있어 비용 정산 확인 전까지 보류하며 자동 재실행하지 않습니다."
    ),
    "LEASE_EXPIRED_NO_DISPATCH": (
        "서버 재시작 또는 작업 응답 중단으로 분석이 중단되었습니다. "
        "모델 전송이 없어 비용 예약이 해제되었습니다. 다시 접수할 수 있습니다."
    ),
}


class HostedError(ValueError):
    def __init__(self, code: str, status: int = 409, *, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code, self.status = code, status
        self.retry_after = retry_after


def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def file_sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_verified_file(source: Path, target: Path, expected_sha: str) -> None:
    """Create-only disk publication; hash the copied bytes before making them visible."""
    with NamedTemporaryFile(dir=target.parent) as staged, source.open("rb") as stream:
        shutil.copyfileobj(stream, staged, length=1024 * 1024)
        staged.flush()
        os.fsync(staged.fileno())
        if file_sha256(Path(staged.name)) != expected_sha:
            raise HostedError("SOURCE_HASH_MISMATCH")
        os.chmod(staged.name, 0o400)
        os.link(staged.name, target)


def micros(value: Decimal | str) -> int:
    amount = Decimal(value)
    if not amount.is_finite() or amount < 0 or amount * MICRO != (amount * MICRO).to_integral():
        raise ValueError("invalid micro-USD amount")
    return int(amount * MICRO)


def usd(value: int) -> str:
    return f"{Decimal(value) / MICRO:.6f}"


def identifier(value: str) -> str:
    try:
        if str(UUID(value)) != value:
            raise ValueError()
        return value
    except (ValueError, TypeError, AttributeError):
        raise HostedError("RESOURCE_NOT_FOUND", 404) from None


def day(now: float) -> str:
    return datetime.fromtimestamp(now, ZoneInfo("Asia/Seoul")).date().isoformat()


@dataclass(frozen=True)
class HostedSettings:
    root: Path
    origin: str
    secret: str
    event_id: str
    accept_uploads: bool = False
    consent_version: str = ""
    backend: str = "static"
    accept_runs: bool = False
    live_disabled: bool = True
    live_config: Path | None = None
    max_upload_bytes: int = 150 * 1024 * 1024
    active_days: int = 7
    backup_days: int = 14
    audit_days: int = 30
    run_usd: Decimal = Decimal("1.0")
    day_usd: Decimal = Decimal("7")
    event_usd: Decimal = Decimal("7")
    event_usd_ceiling: Decimal = Decimal("7")
    user_daily_runs: int = 6
    max_active_runs: int = 1
    user_active_runs: int = 1
    daily_runs: int = 10
    access_config: Path | None = None
    auth_trusted_proxies: tuple[str, ...] = ()
    guest_access_until: datetime | None = None
    guest_fresh_runs_per_day: int = 2
    guest_sessions_per_ip_hour: int = 30
    guest_uploads_per_day: int = 60
    showcase_tenant: str = ""
    rc1_reuse_enabled: bool = False
    retain_failed_analysis: bool = True
    failure_diagnostics_max_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        from urllib.parse import urlsplit

        parsed = urlsplit(self.origin)
        if self.guest_access_until is not None and (
            not isinstance(self.guest_access_until, datetime)
            or self.guest_access_until.utcoffset() is None
        ):
            raise ValueError("HOSTED_GUEST_ACCESS_UNTIL must include a timezone")
        if (
            type(self.guest_fresh_runs_per_day) is not int
            or not 1 <= self.guest_fresh_runs_per_day <= 5
            or type(self.guest_sessions_per_ip_hour) is not int
            or self.guest_sessions_per_ip_hour < 1
            or type(self.guest_uploads_per_day) is not int
            or self.guest_uploads_per_day < 1
        ):
            raise ValueError("HOSTED_GUEST_LIMIT_INVALID")
        if not isinstance(self.showcase_tenant, str):
            raise ValueError("HOSTED_SHOWCASE_TENANT must be a UUID or empty")
        if self.showcase_tenant:
            identifier(self.showcase_tenant)
        if type(self.retain_failed_analysis) is not bool or (
            type(self.failure_diagnostics_max_bytes) is not int
            or not 16384 <= self.failure_diagnostics_max_bytes <= 512 * 1024 * 1024
        ):
            raise ValueError("HOSTED_FAILURE_DIAGNOSTICS_INVALID")
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path
            or parsed.query
            or parsed.fragment
            or "*" in self.origin
        ):
            raise ValueError("APP_ORIGIN must be one exact HTTPS origin")
        if not self.root.is_absolute() or len(self.secret.encode()) < 32 or not self.event_id:
            raise ValueError(
                "absolute private data directory, session secret and event ID required"
            )
        if self.backend not in {"r108", "legacy", "static"}:
            raise ValueError("invalid analysis backend")
        if self.access_config is not None and not self.access_config.is_absolute():
            raise ValueError("absolute private access config required")
        from ipaddress import ip_address

        for proxy in self.auth_trusted_proxies:
            ip_address(proxy)
        if type(self.max_active_runs) is not int or self.max_active_runs not in (1, 2):
            raise ValueError("HOSTED_RUN_CONCURRENCY_INVALID")
        if not self.live_disabled:
            from proofops_api.hosted_analysis import read_operator_config

            read_operator_config(self.live_config)
        if self.accept_uploads and not self.consent_version:
            raise ValueError("upload consent version required")
        for value in (
            self.max_upload_bytes,
            self.active_days,
            self.backup_days,
            self.audit_days,
            self.user_daily_runs,
            self.user_active_runs,
            self.daily_runs,
        ):
            if type(value) is not int or value <= 0:
                raise ValueError("positive limits required")
        if (
            self.max_upload_bytes > 150 * 1024 * 1024
            or self.active_days > 7
            or self.backup_days > 14
            or self.audit_days > 30
        ):
            raise ValueError("limits exceed P1 ceilings")
        if not self.active_days <= self.backup_days <= self.audit_days:
            raise ValueError("retention order invalid")
        # DEC-191: the operator-approved daily ceiling is USD 15; run and event caps are unchanged.
        for amount, ceiling in ((self.run_usd, "1.0"), (self.day_usd, "15")):
            if not 0 < micros(amount) <= micros(ceiling):
                raise ValueError("budget exceeds DEC-22 ceilings")
        if not 0 < micros(self.event_usd) <= micros(self.event_usd_ceiling):
            raise ValueError("budget exceeds DEC-22 ceilings")

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> HostedSettings:
        def flag(name: str, default: str) -> bool:
            value = env.get(name, default)
            if value not in {"true", "false"}:
                raise ValueError(f"invalid {name}")
            return value == "true"

        if env.get("APP_ENV") != "hosted" or env.get("MODEL_ADAPTER", "disabled") != "disabled":
            raise ValueError("explicit hosted/disabled composition required")
        return cls(
            root=Path(env.get("HOSTED_DATA_DIR", "")),
            origin=env.get("APP_ORIGIN", ""),
            secret=env.get("HOSTED_SESSION_SECRET", ""),
            event_id=env.get("HOSTED_EVENT_ID", ""),
            accept_uploads=flag("HOSTED_ACCEPT_UPLOADS", "false"),
            consent_version=env.get("HOSTED_CONSENT_VERSION", ""),
            backend=env.get("ANALYSIS_BACKEND", "static"),
            accept_runs=flag("R108_ACCEPT_NEW_RUNS", "false"),
            rc1_reuse_enabled=flag("RC1_RESULT_REUSE_ENABLED", "false"),
            live_disabled=flag("LIVE_DISABLED", "true"),
            live_config=Path(env["HOSTED_LIVE_CONFIG"]) if env.get("HOSTED_LIVE_CONFIG") else None,
            max_upload_bytes=int(env.get("HOSTED_MAX_UPLOAD_BYTES", "157286400")),
            active_days=int(env.get("HOSTED_ACTIVE_DAYS", "7")),
            backup_days=int(env.get("HOSTED_BACKUP_DAYS", "14")),
            audit_days=int(env.get("HOSTED_AUDIT_DAYS", "30")),
            run_usd=Decimal(env.get("HOSTED_RUN_USD", "1.0")),
            day_usd=Decimal(env.get("HOSTED_DAY_USD", "7")),
            event_usd=Decimal(env.get("HOSTED_EVENT_USD", "7")),
            event_usd_ceiling=Decimal(env.get("HOSTED_EVENT_USD_CEILING", "7")),
            user_daily_runs=int(env.get("HOSTED_USER_DAILY_RUNS", "6")),
            max_active_runs=int(env.get("HOSTED_MAX_ACTIVE_RUNS", "1")),
            user_active_runs=int(env.get("HOSTED_USER_ACTIVE_RUNS", "1")),
            daily_runs=int(env.get("HOSTED_DAILY_RUNS", "10")),
            retain_failed_analysis=flag("HOSTED_RETAIN_FAILED_ANALYSIS", "true"),
            failure_diagnostics_max_bytes=int(
                env.get("HOSTED_FAILURE_DIAGNOSTICS_MAX_BYTES", "536870912")
            ),
            access_config=Path(env.get("HOSTED_ACCESS_CONFIG", "/run/private/access.json")),
            auth_trusted_proxies=tuple(
                value.strip()
                for value in env.get("HOSTED_AUTH_TRUSTED_PROXIES", "").split(",")
                if value.strip()
            ),
            guest_access_until=datetime.fromisoformat(env["HOSTED_GUEST_ACCESS_UNTIL"])
            if env.get("HOSTED_GUEST_ACCESS_UNTIL")
            else None,
            guest_fresh_runs_per_day=int(env.get("HOSTED_GUEST_FRESH_RUNS_PER_DAY", "2")),
            guest_sessions_per_ip_hour=int(env.get("HOSTED_GUEST_SESSIONS_PER_IP_HOUR", "30")),
            guest_uploads_per_day=int(env.get("HOSTED_GUEST_UPLOADS_PER_DAY", "60")),
            showcase_tenant=env.get("HOSTED_SHOWCASE_TENANT", ""),
        )


# Read-only SQLite rows and JSON copies carry the same persisted hosted records.
type HostedRow = sqlite3.Row | dict[str, Any]
type SourceAnchor = tuple[str, str, str, PageGeometry]
type CoordinateRequest = tuple[dict[str, Any], dict[str, Any], Path, SourceAnchor | None, bool]
type ProjectedGlyph = tuple[str, int, tuple[float, float, float, float]]


class SourceInventoryStore(Protocol):
    @property
    def root(self) -> Path: ...

    def document_dir(self, tenant: str, document: str) -> Path: ...


class HostedReadStore(SourceInventoryStore, Protocol):
    """Store operations used by API reads, including duck-typed offline readers."""

    @property
    def settings(self) -> HostedSettings: ...

    @property
    def sessions(self) -> SessionPort: ...

    @property
    def memberships(self) -> MembershipPort: ...

    def transaction(
        self, *, readonly: bool = False
    ) -> AbstractContextManager[sqlite3.Connection]: ...

    def _document(self, db: sqlite3.Connection, tenant: str, document: str) -> sqlite3.Row: ...

    def _require_document_owner(
        self, db: sqlite3.Connection, auth: AuthContext, document: str
    ) -> None: ...

    def user_hash(self, user: str) -> str: ...

    def ux1_document_metadata(self, tenant: str, document: str) -> dict[str, Any]: ...

    def _project_run(
        self, row: sqlite3.Row, db: sqlite3.Connection, *, inline_result: bool = True
    ) -> dict[str, Any]: ...

    def get_run(self, tenant: str, run: str) -> dict[str, Any]: ...

    def _run(self, db: sqlite3.Connection, tenant: str, run: str) -> sqlite3.Row: ...

    def _result(self, db: sqlite3.Connection | None, row: sqlite3.Row) -> dict[str, Any]: ...

    def analysis_source(self, directory: Path, document: dict[str, Any]) -> Path: ...

    def run_options(self, job: HostedRow) -> dict[str, Any]: ...
