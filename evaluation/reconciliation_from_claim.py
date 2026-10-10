"""Build and register a pending case from a verified run and operator selections.

This is a local operator command, never a public upload API. The financial
half comes from reconciliation_prepare's selected draft, the SR half from
the current accepted claim/tag head. No approval is imported or manufactured.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from copy import deepcopy
from datetime import date
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

from proofops.adapters.local.reconciliation_store import ReconciliationRejected
from proofops.adapters.reconciliation.files import FileSourceReader
from proofops.application.linkage_exchange import (
    BlockedPacket,
    C2PeriodContext,
    C3Context,
    C4Context,
    FinancialContext,
    FinancialFact,
    FinancialSource,
    build_packet,
)
from proofops.application.reconciliation.schema import validate_schema

from evaluation.reconciliation_bindings import documents_for_packet
from evaluation.reconciliation_cli import load_json
from scripts.linkage_exchange_cli import reviewed_head_tags


def financial_context_from_draft(draft):
    """Consume the existing candidate-selection output, not a second fact mapper."""
    packet = draft["packet"]
    validate_schema("input", packet)
    identity = packet["identity"]
    fields = {
        key: identity[key]
        for key in (
            "company_id",
            "package_id",
            "dart_corp_code",
            "financial_document_version",
            "financial_fiscal_year",
            "consolidation",
            "financial_period_start",
            "financial_period_end",
            "financial_published_at",
            "rcept_no",
            "as_of_date",
        )
    }
    return FinancialContext(
        **fields,
        synthetic=packet["synthetic"],
        financial=FinancialFact(**packet["financial"]),
        financial_sources=tuple(
            FinancialSource(**ref)
            for ref in packet["sources"]
            if ref["document_id"] != identity["sustainability_document_version"]
        ),
        c3_context=C3Context(**packet["c3_context"]) if packet["c3_context"] else None,
        c4_context=C4Context(**packet["c4_context"]) if packet["c4_context"] else None,
    )


def pdf_page_units(payload):
    """Every physical page of the staged bytes; cited pages are never the whole document."""
    from io import BytesIO

    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise ValueError("encrypted")
        count = len(reader.pages)
    except (PyPdfError, ValueError, OSError, KeyError, TypeError) as error:
        raise ReconciliationRejected("PAGE_CATALOG_UNREADABLE", 422) from error
    if count < 1:
        raise ReconciliationRejected("PAGE_CATALOG_UNREADABLE", 422)
    return [
        dict(kind="page", unit_id=f"page-{number}", locator=f"page:{number}")
        for number in range(1, count + 1)
    ]


def consistent_units(units):
    """A supplied unit catalog is kept only when every unit is well formed and unique."""
    if not isinstance(units, list) or not units:
        return None
    seen = set()
    for unit in units:
        if (
            not isinstance(unit, dict)
            or unit.get("kind") not in ("page", "note")
            or any(not isinstance(unit.get(k), str) or not unit[k] for k in ("unit_id", "locator"))
            or unit["unit_id"] in seen
        ):
            return None
        seen.add(unit["unit_id"])
    return deepcopy(units)


def bind_coverage(document, template, units, *, pdf):
    """Map each binding to one catalog unit, or mark the document's coverage incomplete."""
    ids = {unit["unit_id"] for unit in units or []}
    mapped = units is not None
    for sid, binding in document["source_bindings"].items():
        binding.pop("coverage_unit_id", None)
        page = re.fullmatch(r"page:([1-9][0-9]*)", binding["locator"]) if pdf else None
        prior = template.get("source_bindings", {}).get(sid, {}).get("coverage_unit_id")
        unit_id = f"page-{page.group(1)}" if page else prior
        if unit_id in ids:
            binding["coverage_unit_id"] = unit_id
        else:
            mapped = False
    if mapped:
        document["coverage_units"] = units
        document["coverage_catalog"] = dict(
            state="complete", source="pdf_pages" if pdf else "supplied"
        )
    else:
        # Fail closed: without a full unit catalog no search over this document can be
        # recorded as complete (coverage_reason then reports coverage_unverified).
        document.pop("coverage_units", None)
        for binding in document["source_bindings"].values():
            binding.pop("coverage_unit_id", None)
        document["coverage_catalog"] = dict(state="incomplete", reason="unit_catalog_missing")


def pin_provenance(pin, selected):
    """Immutable audit copy of the operator's DART pin, stored with the financial document."""
    history = pin["pin_history"]
    return dict(
        corp_code=pin["corp_code"],
        as_of=pin["as_of"],
        rcept_no=selected["rcept_no"],
        rcept_dt=selected.get("rcept_dt"),
        report_nm=selected.get("report_nm"),
        report_period=selected["report_period"],
        pinned_at=history[-1]["pinned_at"],
        operator=history[-1]["operator"],
        pin_history_length=len(history),
        raw_response_sha256=deepcopy(pin.get("raw_response_sha256", [])),
        manifest_sha256=sha256(
            json.dumps(pin, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    )


def create_case_from_claim(
    *,
    store,
    uploads,
    auth,
    run_id,
    claim_id,
    draft,
    artifact_root,
    pin,
    c2_period_context=None,
    sr_published_at=None,
    coverage_proposal=None,
):
    """Require a trusted current head and explicit company/filing identity."""
    from proofops.adapters.dart.filings import validate_pinned_manifest

    store._require(auth, "admin")
    tenant = store._tenant(auth)
    if draft.get("packet", {}).get("item") == "C5":
        raise ReconciliationRejected("stage_disabled", 422)
    policy = deepcopy(draft["policy"])
    if (
        policy.get("approved") is not False
        or policy.get("approved_by") is not None
        or (policy.get("approved_on") is not None or draft.get("policies"))
    ):
        raise ReconciliationRejected("imported_policy_approval_forbidden", 422)
    claim = store.claims.get(tenant, run_id, claim_id)
    run = store.run_store.snapshot(tenant, run_id)
    company_id = run["document"]["company"]["company_id"]
    link = store.company_link(auth, company_id)
    financial = financial_context_from_draft(draft)
    selected = validate_pinned_manifest(pin)
    if financial.dart_corp_code != link["corp_code"] or (
        pin["corp_code"] != link["corp_code"]
        or selected["rcept_no"] != financial.rcept_no
        or pin["as_of"] != financial.as_of_date.replace("-", "")
    ):
        raise ReconciliationRejected("filing_identity_mismatch", 422)
    if int(selected["report_period"][:4]) != financial.financial_fiscal_year or (
        financial.financial_period_end is not None
        and selected["report_period"].replace(".", "-") != financial.financial_period_end[:7]
    ):
        raise ReconciliationRejected("filing_period_mismatch", 422)
    tags, revision = reviewed_head_tags(
        store.claims, claim, tenant_id=tenant, run_id=run_id, claim_id=claim_id
    )
    with store.jobs._transaction() as db:
        mutation_epoch = store.jobs._get(db, tenant, run_id, "run", "META")["mutation_epoch"]
    metadata = uploads.version_snapshot(tenant, claim.document_version_id).get("metadata") or {}
    stored_publication = metadata.get("sr_published_at") or metadata.get("publication_date")
    if sr_published_at is not None:
        if (
            not isinstance(sr_published_at, str)
            or date.fromisoformat(sr_published_at).isoformat() != sr_published_at
        ):
            raise ReconciliationRejected("INVALID_PUBLICATION_DATE", 422)
        if stored_publication is not None and sr_published_at != stored_publication:
            raise ReconciliationRejected("PUBLICATION_DATE_CONFLICT", 422)
    packet = build_packet(
        claim=claim,
        tags=tags,
        financial_context=financial,
        item=draft["packet"]["item"],
        tenant_id=tenant,
        trusted_company_id=company_id,
        period_start=metadata.get("period_start"),
        period_end=metadata.get("period_end"),
        sr_published_at=stored_publication or sr_published_at,
        c2_period_context=c2_period_context,
    )
    if isinstance(packet, BlockedPacket):
        raise ReconciliationRejected(packet.reason, 422) from ValueError(packet.detail)
    if packet["synthetic"] is not (run["document"].get("local_synthetic") is True):
        raise ReconciliationRejected("SYNTHETIC_SCOPE_MISMATCH", 422)
    # Only explicit operator comparability is retained, never a result or approval.
    packet["comparability"] = draft["packet"]["comparability"]
    coverage = {}
    if coverage_proposal is not None:
        # This is an explicit operator proposal, only consumed after authenticated review.
        # Never synthesize a complete receipt from page counts or selected citations.
        if not isinstance(coverage_proposal, dict) or set(coverage_proposal) != {
            "search",
            "coverage",
        }:
            raise ReconciliationRejected("INVALID_COVERAGE_PROPOSAL", 422)
        packet["search"] = deepcopy(coverage_proposal["search"])
        coverage = deepcopy(coverage_proposal["coverage"])
        if not isinstance(coverage, dict):
            raise ReconciliationRejected("INVALID_COVERAGE_PROPOSAL", 422)
    for ref in packet["sources"]:
        match = re.fullmatch(r"physical_page=([1-9][0-9]*);source_id=.+", ref["locator"])
        if ref["document_id"] == claim.document_version_id and match:
            ref["locator"] = "page:" + match.group(1)
    validate_schema("input", packet)
    validate_schema("policy", policy)
    reader = FileSourceReader(Path(artifact_root), draft["artifacts"])
    with TemporaryDirectory(prefix="reconciliation-from-claim-") as folder:
        stage = Path(folder)
        artifacts, units = {}, {}
        for ref in packet["sources"]:
            document_id = ref["document_id"]
            if document_id in artifacts:
                continue
            if document_id == claim.document_version_id:
                payload = uploads.read_original(tenant, document_id)
                format_name = "pdf"
            else:
                payload = reader(ref)
                format_name = draft["artifacts"][document_id]["format"]
            digest = sha256(payload).hexdigest()
            if digest != ref["artifact_sha256"]:
                raise ReconciliationRejected("ARTIFACT_UNVERIFIED", 422)
            name = f"{len(artifacts):04d}.bin"
            (stage / name).write_bytes(payload)
            artifacts[document_id] = dict(path=name, format=format_name, sha256=digest)
            if format_name == "pdf":
                units[document_id] = pdf_page_units(payload)
        documents = documents_for_packet(packet)
        # New cases require explicit fact periods. Missing bindings stay blocked;
        # a report-wide period is not automatically a fact's period.
        for document_id, document in documents.items():
            document["period_binding_required"] = True
            template = draft.get("documents", {}).get(document_id, {})
            if "candidate_limit" in template:
                document["candidate_limit"] = deepcopy(template["candidate_limit"])
            for field in ("source_bindings", "fact_bindings"):
                for sid, binding in document[field].items():
                    prior = template.get(field, {}).get(sid, {})
                    for sidecar in ("period_binding", "difference_binding"):
                        if sidecar in prior:
                            binding[sidecar] = deepcopy(prior[sidecar])
            # Real PDF bytes define their own page catalog; other formats keep a supplied
            # catalog only when it is well formed and maps every cited binding.
            pdf = artifacts[document_id]["format"] == "pdf"
            bind_coverage(
                document,
                template,
                units[document_id] if pdf else consistent_units(template.get("coverage_units")),
                pdf=pdf,
            )
            if document["document_role"] == "financial":
                document["filing_pin"] = pin_provenance(pin, selected)
            elif stored_publication is None and sr_published_at is not None:
                document["publication_date_origin"] = "operator_proposal"
        if c2_period_context is not None:
            # This literal was checked by build_packet against the exact trigger citation.
            start, end = c2_period_context.normalized.split("/")
            sid = packet["sustainability"]["source_id"]
            documents[claim.document_version_id]["fact_bindings"][sid]["period_binding"] = {
                "period_start": start,
                "period_end": end,
            }
        # A head changed during preparation must not silently replace its trigger.
        _, current_revision = reviewed_head_tags(
            store.claims, claim, tenant_id=tenant, run_id=run_id, claim_id=claim_id
        )
        if revision != current_revision:
            raise ReconciliationRejected("TAG_HEAD_CHANGED", 409)
        return store.register_case(
            auth,
            run_id,
            claim_id,
            dict(
                packet=packet,
                policy=policy,
                documents=documents,
                artifacts=artifacts,
                coverage=coverage,
                policies={},
            ),
            stage,
            expected_tag_revision=revision,
            expected_mutation_epoch=mutation_epoch,
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--pin", type=Path, required=True)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    parser.add_argument("--run-id", type=UUID, required=True)
    parser.add_argument("--claim-id", type=UUID, required=True)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--c2-period-context", type=Path)
    parser.add_argument(
        "--sr-published-at", help="Explicit ISO date proposal; never inferred from upload time"
    )
    parser.add_argument(
        "--coverage-proposal",
        type=Path,
        help="Pending JSON {search, coverage}; requires reviewer confirmation",
    )
    args = parser.parse_args(argv)
    if not args.database.is_file() or os.environ.get("APP_ENV", "local") != "local":
        parser.error("an existing local server database is required")
    if not args.actor.strip():
        parser.error("operator identity is required")
    from proofops.application.authorization import AuthContext
    from proofops_api.composition import build_composition

    os.environ["LOCAL_DATABASE_PATH"] = str(args.database.resolve())
    os.environ["ENABLE_RECONCILIATION"] = "true"
    composition = build_composition()
    try:
        draft = {
            name: load_json(args.bundle / f"{name}.json")
            for name in ("packet", "policy", "documents", "artifacts")
        }
        if (args.bundle / "policies.json").exists():
            draft["policies"] = load_json(args.bundle / "policies.json")
        auth = AuthContext(
            args.actor.strip(),
            str(args.tenant_id),
            "admin",
            frozenset({"viewer", "editor", "reviewer", "admin"}),
            "local-operator-from-claim",
        )
        detail = create_case_from_claim(
            store=composition.reconciliation,
            uploads=composition.uploads,
            auth=auth,
            run_id=str(args.run_id),
            claim_id=str(args.claim_id),
            draft=draft,
            artifact_root=args.artifacts,
            pin=load_json(args.pin),
            c2_period_context=C2PeriodContext(**load_json(args.c2_period_context))
            if args.c2_period_context
            else None,
            sr_published_at=args.sr_published_at,
            coverage_proposal=load_json(args.coverage_proposal) if args.coverage_proposal else None,
        )
        print(
            json.dumps(
                {
                    key: detail[key]
                    for key in ("case_id", "revision", "review_state", "policy_approved")
                }
            )
        )
        return 0
    except (ValueError, LookupError, OSError, TypeError) as error:
        print(
            json.dumps({"error": getattr(error, "code", "case_preparation_rejected")}),
            file=sys.stderr,
        )
        return 2
    finally:
        composition.uploads.close()
        composition.registry.close()


if __name__ == "__main__":
    raise SystemExit(main())
