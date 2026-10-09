"""Explicit operator opt-in and brokered R108 provider adapters."""

import fcntl
import io
import json
import os
import subprocess
import sys
import time
from datetime import date
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from proofops.adapters.local.openai import (
    MODEL as OPENAI_MODEL,
)
from proofops.adapters.local.openai import (
    WIRE_POLICY as OPENAI_WIRE_POLICY,
)
from proofops.adapters.local.openai import (
    OpenAIProbe,
    token_cost,
)
from proofops.adapters.local.openrouter import MODEL, WIRE_POLICY, OpenRouterProbe
from proofops.adapters.local.upstage_parse import (
    ALLOWED_MODELS,
    COST_PER_PAGE,
    UpstageParseProbe,
)
from proofops.domain.provenance import canonical_hash
from pypdf import PdfReader, PdfWriter

# Release-owned approval, never populated from operator JSON or environment.
RENDERED_READER_POLICY = json.loads(
    (Path(__file__).resolve().parents[4] / "config/hosted_rendered_readers.json").read_text()
)
GATE_PASSED_RENDERED_READERS = frozenset(RENDERED_READER_POLICY["gate_passed"])
KNOWN_RENDERED_READERS = frozenset(
    {"upstage-ocr-page-v1", "upstage-ocr-page-v2", "upstage-ocr-page-v3"}
)


def operator_profiles(config: dict) -> dict:
    workers = config.get("llm_max_workers", 8)
    if type(workers) is not int or not 1 <= workers <= 16:
        raise ValueError("HOSTED_LLM_CONCURRENCY_INVALID")
    analysis = config.get("analysis_profile", "r108-default")
    if analysis not in ("r108-default", "r108-finals-candidate", "r108-finals-candidate-v2"):
        raise ValueError("HOSTED_ANALYSIS_PROFILE_INVALID")
    llm_provider = config.get("llm_provider", "openai")
    if llm_provider not in ("openai", "openrouter"):
        raise ValueError("HOSTED_LLM_PROVIDER_INVALID")
    requested = config.get("rendered_reader_profile")
    if requested is not None and requested not in KNOWN_RENDERED_READERS:
        raise ValueError("HOSTED_RENDERED_READER_PROFILE_INVALID")
    reader = (
        "apple-vision"
        if sys.platform == "darwin"
        else RENDERED_READER_POLICY["default_linux_reader"]
    )
    if requested is not None or reader != "apple-vision":
        reader = requested or reader
        reader = reader if reader in GATE_PASSED_RENDERED_READERS else "unresolved"
    approval = RENDERED_READER_POLICY["gate_passed"].get(reader, {})
    return PROFILES | dict(
        llm_max_workers=workers,
        llm_provider=llm_provider,
        llm_provider_options=["openai", "openrouter"],
        analysis_profile=analysis,
        analysis_profile_options=["r108-default", "r108-finals-candidate-v2"],
        analysis_profile_warning=(
            "E2E5 회귀 확인 — r108-finals-candidate-v2 또는 r108-default 사용 권장"
            if analysis == "r108-finals-candidate"
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
    for name in (key_name, "upstage_key_file"):
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


def rounded_cost(value) -> str:
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("PROVIDER_COST_INVALID")
    return str(amount.quantize(Decimal("0.000001"), rounding=ROUND_CEILING))


def broker_dispatch(store, *args, **kwargs):
    from proofops.application.budget import BudgetExceeded

    from proofops_api.hosted_store import HostedError

    try:
        return store.dispatch(*args, **kwargs)
    except HostedError as error:
        if error.code == "BUDGET_EXCEEDED":
            raise BudgetExceeded("BUDGET_EXHAUSTED") from None
        raise


class HostedLunaProbe(OpenRouterProbe):
    def __init__(self, *args, store, job, post=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.job, self.post = store, job, post

    def _post(self, body):
        # Includes every schema retry: each attempt gets a separate reservation.
        if body.get("model") != MODEL or body.get("provider") != WIRE_POLICY["provider"]:
            raise ValueError("HOSTED_WIRE_POLICY_REQUIRED")

        def transport(request):
            data = self.post(body) if self.post else super(HostedLunaProbe, self)._post(body)
            if data.get("model") != MODEL:
                raise ValueError("HOSTED_MODEL_MISMATCH")
            return request | dict(actual_usd=rounded_cost(data["usage"]["cost"]), payload=data)

        response = broker_dispatch(
            self.store,
            self.job,
            "openrouter",
            str(uuid4()),
            canonical_hash(body),
            Decimal("0.011"),
            transport,
            now=time.time(),
        )
        return response["payload"]


class HostedOpenAILunaProbe(OpenAIProbe):
    def __init__(self, *args, store, job, post=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.job, self.post = store, job, post

    def _post(self, body):
        if body.get("model") != OPENAI_MODEL or OPENAI_WIRE_POLICY["endpoint"] != (
            "https://api.openai.com/v1/chat/completions"
        ):
            raise ValueError("HOSTED_WIRE_POLICY_REQUIRED")

        def transport(request):
            data = self.post(body) if self.post else super(HostedOpenAILunaProbe, self)._post(body)
            if data.get("model") != OPENAI_MODEL:
                raise ValueError("HOSTED_MODEL_MISMATCH")
            return request | dict(actual_usd=rounded_cost(token_cost(data["usage"])), payload=data)

        response = broker_dispatch(
            self.store,
            self.job,
            "openai",
            str(uuid4()),
            canonical_hash(body),
            Decimal("0.011"),
            transport,
            now=time.time(),
        )
        return response["payload"]


class HostedParseProbe(UpstageParseProbe):
    def __init__(self, *args, store, job, post=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.store, self.job, self.post = store, job, post

    def _post_parse(self, pdf_bytes, mode, path="/v1/document-digitization"):
        pages = len(PdfReader(io.BytesIO(pdf_bytes)).pages)
        if path != "/v1/document-digitization" or not 1 <= pages <= 2:
            raise ValueError("HOSTED_PARSE_SCOPE_INVALID")
        cost = COST_PER_PAGE[mode] * pages

        def transport(request):
            data = (
                self.post(pdf_bytes, mode)
                if self.post
                else super(HostedParseProbe, self)._post_parse(pdf_bytes, mode)
            )
            usage = data.get("usage", {})
            if (
                data.get("model") not in ALLOWED_MODELS
                or usage.get("pages") != pages
                or usage.get(mode) != list(range(1, pages + 1))
                or usage.get("enhanced" if mode == "standard" else "standard", [])
            ):
                raise ValueError("HOSTED_PARSE_RECEIPT_INVALID")
            return request | dict(actual_usd=str(cost), payload=data)

        return broker_dispatch(
            self.store,
            self.job,
            "upstage-parse",
            str(uuid4()),
            canonical_hash(dict(sha256=canonical_hash(pdf_bytes.hex()), mode=mode, pages=pages)),
            cost,
            transport,
            now=time.time(),
        )["payload"]

    def parse_async(self, pdf_bytes, *, request_id, mode="standard"):
        # Keep synchronous, brokered <=2-page calls; map each receipt to the
        # prepared subset before canonical graph conversion. MP1 can replace this
        # factory later using the same pinned claim/evidence selection.
        reader = PdfReader(io.BytesIO(pdf_bytes))
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 30:
            raise ValueError("HOSTED_PARSE_SCOPE_INVALID")
        batches, receipts = [], []
        for start in range(0, len(reader.pages), 2):
            writer, buffer = PdfWriter(), io.BytesIO()
            for page in reader.pages[start : start + 2]:
                writer.add_page(page)
            writer.write(buffer)
            result = self.parse(buffer.getvalue(), request_id=f"{request_id}-{start}", mode=mode)
            batch = json.loads(json.dumps(result["raw_response"]))
            batch["usage"][mode] = [p + start for p in batch["usage"][mode]]
            for element in batch["elements"]:
                if type(element.get("page")) is not int or not 1 <= element["page"] <= len(
                    writer.pages
                ):
                    raise ValueError("HOSTED_PARSE_PAGE_INVALID")
                element["page"] += start
            batches.append(batch)
            receipts.append({k: v for k, v in result.items() if k != "raw_response"})
        return dict(
            raw_batches=batches,
            response_sha256=canonical_hash(batches),
            receipts=receipts,
            model=receipts[0]["model"],
            pages=len(reader.pages),
            mode=mode,
            cost_with_vat_reserve_usd=str(COST_PER_PAGE[mode] * len(reader.pages)),
        )


def execute_analysis(store, job, prepared):
    config = read_operator_config(store.settings.live_config)
    profiles = operator_profiles(config)
    with store.transaction() as db:
        store._fenced(db, job, time.time())
        directory = store.document_dir(job["tenant_id"], job["document_id"])
        lock = (directory / "analysis.lock").open("a+b")
        os.fchmod(lock.fileno(), 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with TemporaryDirectory(prefix="analysis-work-", dir=directory) as scratch:
            workspace = Path(scratch)
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
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "evaluation.hosted_r108",
                    job["run_id"],
                    str(job["fence"]),
                    str(workspace),
                ],
                check=True,
                timeout=840,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=(lock.fileno(),),
            )
            outcome = json.loads((workspace / "state" / "outcome.json").read_text())
            store.publish_analysis(
                job, workspace / "state", outcome["status"], outcome.get("reason")
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
