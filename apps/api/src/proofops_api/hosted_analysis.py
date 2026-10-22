"""Explicit operator opt-in and brokered R108 provider adapters."""

import fcntl
import json
import os
import signal
import subprocess
import sys
import time
from datetime import date
from pathlib import Path
from tempfile import TemporaryFile

from proofops.adapters.local.openrouter import MODEL
from proofops.application.openai_retry import POLICY as T1_RETRY_POLICY
from proofops.domain.provenance import canonical_hash

from proofops_api.hosted_probes import WIRE_POLICY as WIRE_POLICY
from proofops_api.hosted_probes import (
    HostedLunaProbe as HostedLunaProbe,
)
from proofops_api.hosted_probes import (
    HostedOpenAILunaProbe as HostedOpenAILunaProbe,
)
from proofops_api.hosted_probes import (
    HostedParseProbe as HostedParseProbe,
)
from proofops_api.hosted_probes import (
    broker_dispatch as broker_dispatch,
)
from proofops_api.hosted_probes import (
    rounded_cost as rounded_cost,
)

# Release-owned approval, never populated from operator JSON or environment.
RENDERED_READER_POLICY = json.loads(
    (Path(__file__).resolve().parents[4] / "config/hosted_rendered_readers.json").read_text()
)
GATE_PASSED_RENDERED_READERS = frozenset(RENDERED_READER_POLICY["gate_passed"])
KNOWN_RENDERED_READERS = frozenset(
    {
        "upstage-ocr-page-v1",
        "upstage-ocr-page-v2",
        "upstage-ocr-page-v3",
        "upstage-ocr-page-v4",
        "upstage-ocr-page-v5",
        "upstage-ocr-page-v6",
        "upstage-ocr-page-v9",
        "upstage-ocr-page-v10",
    }
)
PUBLIC_FINALS_PROFILES = ("finals-unattended-v1", "finals-unattended-v2")
FINALS_PROFILES = (
    *PUBLIC_FINALS_PROFILES,
    "finals-unattended-j3-v1",
    "finals-unattended-j7-v1",
    "finals-unattended-j8-v1",
)


def default_analysis_profile():
    # HS3 temporary choice. Coordinator finalizes it after QI2.
    return os.environ.get("HOSTED_ANALYSIS_PROFILE", "finals-unattended-v2")


def operator_profiles(config: dict) -> dict:
    from proofops.application.analysis_profile import publication_policy_for
    from proofops.application.claim_scope import MAX_EXTRACTION_BATCH_CALLS

    analysis = config.get("analysis_profile", default_analysis_profile())
    policy = (
        publication_policy_for(analysis, pinned_hash=config.get("analysis_policy_sha256"))
        if analysis in FINALS_PROFILES
        else {}
    )
    workers = config.get(
        "llm_max_workers",
        policy.get("provider_scheduler", {}).get(
            "default_workers", policy["max_http_workers"] if policy.get("tagging_budget") else 8
        ),
    )
    # Pre-scheduler F1/T1 pins retain their original accept-then-clamp behavior.
    max_workers = policy["max_http_workers"] if policy.get("provider_scheduler") else 16
    if type(workers) is not int or not 1 <= workers <= max_workers:
        raise ValueError("HOSTED_LLM_CONCURRENCY_INVALID")
    if policy.get("openai_retry_policy") == T1_RETRY_POLICY:
        workers = min(workers, policy["max_http_workers"])
    rps = config.get("llm_requests_per_second", 4)
    if type(rps) is not int or not 1 <= rps <= policy.get("provider_scheduler", {}).get(
        "max_rps", 8
    ):
        raise ValueError("HOSTED_LLM_RPS_INVALID")
    if "llm_requests_per_second" in config and not policy.get("provider_scheduler"):
        raise ValueError("PROVIDER_SCHEDULER_POLICY_REQUIRED")
    batch_calls = config.get("extract_batch_calls", policy.get("extract_batch_calls", 20))
    if type(batch_calls) is not int or not 1 <= batch_calls <= MAX_EXTRACTION_BATCH_CALLS:
        raise ValueError("HOSTED_EXTRACT_BATCH_INVALID")
    analysis = config.get("analysis_profile", default_analysis_profile())
    if analysis not in (
        "r108-default",
        "r108-finals-candidate",
        "r108-finals-candidate-v2",
        *FINALS_PROFILES,
    ):
        raise ValueError("HOSTED_ANALYSIS_PROFILE_INVALID")
    llm_provider = config.get("llm_provider", "openai")
    if llm_provider not in ("openai", "openrouter"):
        raise ValueError("HOSTED_LLM_PROVIDER_INVALID")
    if analysis in FINALS_PROFILES:
        llm_provider = "openai"
    if config.get("analysis_policy_sha256") is not None:
        from proofops.application.analysis_profile import publication_policy_for

        publication_policy_for(analysis, pinned_hash=config["analysis_policy_sha256"])
    requested = config.get("rendered_reader_profile")
    if requested is not None and requested not in KNOWN_RENDERED_READERS:
        raise ValueError("HOSTED_RENDERED_READER_PROFILE_INVALID")
    reader = (
        "apple-vision"
        if sys.platform == "darwin"
        else RENDERED_READER_POLICY.get(
            "default_linux_reader_v2", RENDERED_READER_POLICY["default_linux_reader"]
        )
        if analysis
        in (
            "finals-unattended-v2",
            "finals-unattended-j3-v1",
            "finals-unattended-j7-v1",
            "finals-unattended-j8-v1",
        )
        else RENDERED_READER_POLICY["default_linux_reader"]
    )
    if requested is not None or reader != "apple-vision":
        reader = requested or reader
        reader = reader if reader in GATE_PASSED_RENDERED_READERS else "unresolved"
    approval = RENDERED_READER_POLICY["gate_passed"].get(reader, {})
    return PROFILES | dict(
        llm_max_workers=workers,
        llm_requests_per_second=rps,
        extract_batch_calls=batch_calls,
        llm_provider=llm_provider,
        llm_provider_options=["openai", "openrouter"],
        analysis_profile=analysis,
        analysis_profile_options=[
            "r108-default",
            "r108-finals-candidate-v2",
            *PUBLIC_FINALS_PROFILES,
        ],
        analysis_profile_warning=(
            "E2E5 회귀 확인 — r108-finals-candidate-v2 또는 r108-default 사용 권장"
            if analysis == "r108-finals-candidate"
            else "v2 기본값은 잠정 설정이며 QI2 이후 확정합니다."
            if analysis in FINALS_PROFILES
            else None
        ),
        rendered_reader_requested=requested,
        source_reader=reader,
        claim_source=reader if reader in GATE_PASSED_RENDERED_READERS else "glyph-alignment-v1",
        rendered_reader_policy_sha256=canonical_hash(RENDERED_READER_POLICY),
        rendered_reader_gate_report_sha256=approval.get("report_sha256"),
    )


def runtime_profiles(settings):
    config = {} if settings.live_disabled else read_operator_config(settings.live_config)
    return operator_profiles(config)


def read_operator_config(path: Path | None) -> dict:
    if path is None or not path.is_absolute() or not path.is_file():
        raise ValueError("HOSTED_LIVE_CONFIG_REQUIRED")
    config = json.loads(path.read_text())
    if config.get("enabled") is not True:
        raise ValueError("HOSTED_OPERATOR_OPT_IN_REQUIRED")
    profiles = operator_profiles(config)
    provider = profiles["llm_provider"]
    config["llm_provider"] = provider
    key_name = "openai_key_file" if provider == "openai" else "openrouter_key_file"
    from proofops.application.analysis_profile import policy_for

    selected = (
        policy_for(profiles["analysis_profile"], pinned_hash=config.get("analysis_policy_sha256"))
        if profiles["analysis_profile"] in FINALS_PROFILES
        else {}
    )
    keys = [key_name, "upstage_key_file"]
    if selected.get("ops2_provider_fallback"):
        keys.append("openrouter_key_file")
    for name in keys:
        key_path = Path(config.get(name, ""))
        if not key_path.is_absolute() or not key_path.is_file():
            raise ValueError("HOSTED_KEY_FILE_REQUIRED")
    if type(config["report_year"]) is not int or not 1900 <= config["report_year"] <= 2100:
        raise ValueError("HOSTED_REPORTING_SCOPE_REQUIRED")
    if date.fromisoformat(config["period_start"]) > date.fromisoformat(config["period_end"]):
        raise ValueError("HOSTED_REPORTING_SCOPE_INVALID")
    return config


def read_key(path: str, name: str) -> str:
    for line in Path(path).read_text().splitlines():
        if line.startswith(name + "="):
            key = line.split("=", 1)[1].strip().strip('"').strip("'")
            if key and not any(c.isspace() for c in key):
                return key
    raise ValueError("HOSTED_KEY_FILE_INVALID")


# Wall-clock cap for one analysis subprocess; the per-run USD cap still bounds spend.
ANALYSIS_TIMEOUT_SECONDS = int(os.environ.get("HOSTED_ANALYSIS_TIMEOUT_SECONDS", "2700"))
HEARTBEAT_SECONDS = 30
TWO_SLOT_MEMORY_BYTES = 1100 * 1024 * 1024


def process_tree_bytes(pid):
    """RSS of the isolated analysis and its parser/OCR descendants."""
    output = subprocess.check_output(["ps", "-eo", "pid=,ppid=,rss="], text=True, timeout=5)
    rows = [tuple(map(int, line.split())) for line in output.splitlines()]
    descendants = {pid}
    while True:
        expanded = descendants | {child for child, parent, _ in rows if parent in descendants}
        if expanded == descendants:
            return sum(rss * 1024 for child, _, rss in rows if child in descendants)
        descendants = expanded


def acquire_analysis_lock(lock, *, timeout=2):
    from proofops_api.hosted_contracts import HostedError

    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise HostedError("ANALYSIS_LOCK_BUSY") from None
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def run_analysis_process(command, store, job, lock, *, publication_fd=None):
    from proofops_api.hosted_contracts import HostedError

    deadline = time.monotonic() + ANALYSIS_TIMEOUT_SECONDS
    next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    bounded = store.settings.max_active_runs == 2
    if publication_fd is not None:
        command = [*command, str(publication_fd)]
    process = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        pass_fds=(lock.fileno(),) + ((publication_fd,) if publication_fd is not None else ()),
        start_new_session=True,
        env=os.environ | {"PROOFOPS_RB3_HARD_DEADLINE": str(deadline)},
    )
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, ANALYSIS_TIMEOUT_SECONDS)
            try:
                code = process.wait(
                    timeout=min(
                        2 if bounded else HEARTBEAT_SECONDS,
                        remaining,
                        max(0.05, next_heartbeat - time.monotonic()),
                    )
                )
                if code:
                    raise subprocess.CalledProcessError(code, command)
                return
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise
                if bounded and process_tree_bytes(process.pid) > TWO_SLOT_MEMORY_BYTES:
                    raise HostedError("ANALYSIS_MEMORY_LIMIT") from None
                if time.monotonic() >= next_heartbeat:
                    from proofops_api.hosted_sqlite import is_busy

                    try:
                        store.renew_lease(job, now=time.time())
                    except Exception as exc:
                        if not is_busy(exc):
                            raise
                        if time.time() >= job["lease_until"]:
                            raise HostedError("LEASE_LOST") from None
                        # The existing fence is still valid: keep this child,
                        # never launch a replacement or repeat a provider call.
                        next_heartbeat = time.monotonic() + 1
                    else:
                        next_heartbeat = time.monotonic() + HEARTBEAT_SECONDS
    finally:
        # Reap the entire private session, including a parser/OCR child after an
        # interrupted parent. Its inherited document lock must not outlive the slot.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def execute_analysis(store, job, prepared):
    from proofops_api.hosted_diagnostics import analysis_workspace

    config = read_operator_config(store.settings.live_config)
    profiles = operator_profiles(config)
    with store.transaction() as db:
        store._fenced(db, job, time.time())
        directory = store.document_dir(job["tenant_id"], job["document_id"])
        lock = (directory / "analysis.lock").open("a+b")
        os.fchmod(lock.fileno(), 0o600)
    try:
        acquire_analysis_lock(lock)
        store.renew_lease(job, now=time.time())
        with analysis_workspace(store, job, directory) as workspace:
            os.chmod(workspace, 0o700)
            (workspace / "selected.pdf").write_bytes(prepared.read_bytes())
            if profiles["source_reader"] == "unresolved":
                state = workspace / "state"
                state.mkdir(mode=0o700)
                (state / "outcome.json").write_text(
                    json.dumps(
                        dict(
                            status="partial_blocked",
                            reason="LINUX_SOURCE_READER_UNRESOLVED",
                            profiles=profiles,
                            stages=[],
                            provider_calls=0,
                        )
                    )
                )
                store.publish_analysis(
                    job, state, "partial_blocked", "LINUX_SOURCE_READER_UNRESOLVED"
                )
                return
            # Anonymous, parent-owned FD: no workspace file can impersonate a
            # child attestation. Keep analysis.lock through byte-pin comparison.
            from proofops_api.hosted_publication import MAX_BYTES

            with TemporaryFile() as publication:
                run_analysis_process(
                    [
                        sys.executable,
                        "-m",
                        "evaluation.hosted_r108",
                        job["run_id"],
                        str(job["fence"]),
                        str(workspace),
                    ],
                    store,
                    job,
                    lock,
                    publication_fd=publication.fileno(),
                )
                publication.seek(0)
                packet = publication.read(MAX_BYTES + 1)
            outcome = json.loads((workspace / "state" / "outcome.json").read_text())
            store.publish_analysis(
                job,
                workspace / "state",
                outcome["status"],
                outcome.get("reason"),
                publication_handoff=packet,
            )
    finally:
        lock.close()


PROFILES = dict(
    parser="upstage",
    llm=MODEL,
    relation="occurrence-v3",
    display="glyph-joined-display-v1",
    claim_source="glyph-alignment-v1",
    source_reader="apple-vision" if sys.platform == "darwin" else "unresolved",
)
