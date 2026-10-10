"""Explicit reviewer confirmations create immutable, source-bound report revisions.

No label edits or model-based approvals. A confirmation is an operator attestation,
not independent expert gold. Unreadable sources and parser conflicts stay blocked.
"""

import json
import re
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from proofops.domain.rulepacks import RulePackSnapshot
from proofops.domain.rules.engine import (
    ConfirmedFact,
    ConfirmedTags,
    EvidenceReview,
    RuleContext,
    evaluate,
)
from proofops.domain.values import SourceRef

from evaluation.report_decisions import CONFLICTS, digest

ROOT = Path(__file__).resolve().parents[1] / ".local/web-analysis"


def public_result(result):
    view = json.loads(json.dumps(result))
    for i, claim in enumerate(view["claims"]):
        claim["review_handle"] = dict(
            run_id=result["run_id"],
            claim_index=i,
            result_sha256=digest(result),
            document_pages=result.get("coverage", {}).get("document_pages", 0),
        )
    return view


def review(payload):
    allowed = {
        "run_id",
        "claim_index",
        "result_sha256",
        "document_pages",
        "reviewer",
        "note",
        "confirmed_names",
        "absent_names",
        "coverage_confirmed",
        "absence_confirmed",
        "searched_pages",
    }
    if not isinstance(payload, dict) or set(payload) - allowed:
        raise ValueError("INVALID_REVIEW_FIELDS")
    run_id = payload.get("run_id", "")
    if not isinstance(run_id, str) or not re.fullmatch(r"[0-9a-f]{32}", run_id):
        raise ValueError("INVALID_REVIEW_RUN")
    directory = ROOT / run_id
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    inputs = json.loads((directory / "decision-inputs.json").read_text(encoding="utf-8"))
    if result.get("decision_inputs_sha256") != digest(inputs):
        raise ValueError("REVIEW_SOURCE_CHANGED")
    if payload.get("result_sha256") != digest(result):
        raise ValueError("REVIEW_REVISION_CONFLICT")
    successor = directory / "review-child.json"
    if successor.exists():
        saved = json.loads(successor.read_text(encoding="utf-8"))
        if saved["request_sha256"] != digest(payload):
            raise ValueError("REVIEW_REVISION_CONFLICT")
        child = json.loads((ROOT / saved["run_id"] / "result.json").read_text(encoding="utf-8"))
        return dict(result=public_result(child), result_sha256=digest(child), parent_run=run_id)
    index = payload.get("claim_index")
    if type(index) is not int or not 0 <= index < len(result["claims"]):
        raise ValueError("INVALID_REVIEW_CLAIM")
    reviewer, note = payload.get("reviewer", ""), payload.get("note", "")
    if (
        not isinstance(reviewer, str)
        or not reviewer.strip()
        or not isinstance(note, str)
        or not note.strip()
    ):
        raise ValueError("REVIEW_IDENTITY_AND_REASON_REQUIRED")
    original = result["claims"][index]
    if not original.get("decision_input") or not original.get("source_verified"):
        raise ValueError("REVIEW_VERIFIED_INPUT_REQUIRED")
    if "special_route_review_required" in original["decision"].get("gate_reasons", []):
        raise ValueError("REVIEW_SPECIAL_ROUTE_REQUIRES_DOMAIN_REVIEW")
    if (original.get("crosscheck") or {}).get("original_audit") in CONFLICTS:
        raise ValueError("REVIEW_PARSER_CONFLICT_UNRESOLVED")
    names = payload.get("confirmed_names", [])
    absent = payload.get("absent_names", [])
    if not isinstance(names, list) or not isinstance(absent, list) or not (names or absent):
        raise ValueError("INVALID_REVIEW_ELEMENTS")
    if any(not isinstance(n, str) for n in names + absent) or len(set(names + absent)) != len(
        names + absent
    ):
        raise ValueError("INVALID_REVIEW_ELEMENTS")
    claim = deepcopy(original)
    by_name = {e["name"]: e for e in claim["elements"]}
    if set(names + absent) - by_name.keys():
        raise ValueError("INVALID_REVIEW_ELEMENTS")
    pack = RulePackSnapshot(**inputs["rulepack"])
    prior = claim["decision_input"]
    facts = {
        f["name"]: ConfirmedFact(
            **{**f, "evidence_refs": tuple(SourceRef(**r) for r in f["evidence_refs"])}
        )
        for f in prior["tags"]["facts"]
    }
    for name in names:
        e = by_name[name]
        citation = e.get("citation")
        check = e.get("crosscheck") or {}
        if not citation or not e.get("source_verified") or check.get("original_audit") in CONFLICTS:
            raise ValueError("REVIEW_VERIFIED_CITATION_REQUIRED")
        block = inputs["blocks"][citation["block"]]
        if block["raw_text"].count(citation["quote"]) != 1:
            raise ValueError("REVIEW_SOURCE_CHANGED")
        if block.get("table") and check.get("status") != "consensus":
            raise ValueError("REVIEW_TABLE_STRUCTURE_UNVERIFIED")
        allowed = next(
            d["source_scopes"]
            for d in pack.file_content("rubric/elements.yaml")["elements"]
            if d["id"] == e["element_id"]
        )
        scope = e.get("source_scope")
        if not scope:
            direct = citation["block"] == claim["block"] and citation["quote"] in claim["quote"]
            scope = "local_claim" if direct and "local_claim" in allowed else "global_bound"
        if scope not in allowed or scope == "explicit_link":
            raise ValueError("REVIEW_SOURCE_SCOPE_NOT_ALLOWED")
        if (
            name in {"assurance_covered", "external_verification"}
            and payload.get("coverage_confirmed") is not True
        ):
            raise ValueError("REVIEW_ASSURANCE_COVERAGE_REQUIRED")
        # The operator explicitly confirms meaning and entity/period/metric/scope here.
        from types import SimpleNamespace

        from evaluation.report_decisions import source_ref

        source = SimpleNamespace(
            sha256=inputs["source_sha256"], document_version_id=prior["tags"]["document_version_id"]
        )
        ref = source_ref(source, block, citation["quote"])
        facts[name] = ConfirmedFact(
            name,
            "present",
            (ref,),
            pack.tenant_id,
            True,
            True,
            source_scope=scope,
            normalized_value="covered" if name == "assurance_covered" else citation["quote"],
        )
        e.update(
            state="present",
            binding_status="reviewed",
            source_scope=scope,
            confirmed_ref=asdict(ref),
        )
    if absent:
        coverage = result.get("coverage", {})
        expected_pages = list(range(1, coverage.get("document_pages", 0) + 1))
        if (
            not expected_pages
            or coverage.get("parsed_pages") != expected_pages
            or payload.get("searched_pages") != expected_pages
            or payload.get("absence_confirmed") is not True
        ):
            raise ValueError("REVIEW_FULL_SEARCH_COVERAGE_REQUIRED")
        for name in absent:
            e = by_name[name]
            if e.get("candidate_state") == "present" or e.get("state") in {"present", "conflict"}:
                raise ValueError("REVIEW_ABSENCE_CONTRADICTS_EVIDENCE")
            facts[name] = ConfirmedFact(name, "absent", search_coverage_verified=True)
            e.update(state="absent", binding_status="reviewed_absent")
    stamp = datetime.now(UTC).isoformat()
    packet = digest(
        {"prior": prior["tags"]["packet_sha256"], "facts": [asdict(f) for f in facts.values()]}
    )
    record = dict(
        parent_run=run_id,
        parent_result_sha256=payload["result_sha256"],
        claim_index=index,
        reviewer=reviewer,
        reviewed_at=stamp,
        note=note,
        confirmed_names=names,
        absent_names=absent,
        searched_pages=payload.get("searched_pages", []),
        absence_confirmed=payload.get("absence_confirmed") is True,
        coverage_confirmed=payload.get("coverage_confirmed") is True,
        authority="authenticated local operator confirmation",
        expert_gold=False,
        source_sha256=inputs["source_sha256"],
        packet_sha256=packet,
    )
    tags = ConfirmedTags(
        **{
            **prior["tags"],
            "facts": tuple(facts.values()),
            "tag_revision": prior["tags"]["tag_revision"] + 1,
            "packet_sha256": packet,
            "replicate_hashes": (),
            "evidence_review": EvidenceReview(
                reviewer, stamp, record["authority"], packet, digest(record)
            ),
        }
    )
    context = RuleContext(
        **{
            **prior["context"],
            "packet_sha256": packet,
            "decision_revision": prior["context"]["decision_revision"] + 1,
        }
    )
    decision = evaluate(tags, context, pack)
    claim["decision"] = decision.to_api_dict() | {
        "unresolved_elements": list(decision.unresolved_elements),
        "approval_scope": "project_rubric_only",
        "expert_gold": False,
        "gate_reasons": list(decision.unresolved_elements),
    }
    claim["decision_input"] = dict(
        tags=asdict(tags), context=asdict(context), rulepack_sha256=pack.sha256
    )
    claim["review"] = dict(
        status="reviewed",
        origin="local_operator",
        expert_gold=False,
        scope="선택한 요소의 의미·기업·기간·범위 확인",
        notes=[note],
        record_sha256=digest(record),
    )
    claim["blocked_reason"] = (
        ""
        if decision.evidence_grade
        else "추가 확인 요소: "
        + ", ".join(decision.grade_open_elements or decision.unresolved_elements)
    )
    result["claims"][index] = claim
    new_id = uuid4().hex
    result["run_id"] = new_id
    for i, c in enumerate(result["claims"]):
        c["review_handle"] = dict(run_id=new_id, claim_index=i)
    inputs["inputs"][index] = claim["decision_input"]
    result["decision_inputs_sha256"] = digest(inputs)
    new_dir = ROOT / new_id
    new_dir.mkdir()
    for name, data in (
        ("result.json", result),
        ("decision-inputs.json", inputs),
        ("review.json", record),
    ):
        (new_dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    successor.write_text(
        json.dumps(dict(request_sha256=digest(payload), run_id=new_id)), encoding="utf-8"
    )
    return dict(result=public_result(result), result_sha256=digest(result), parent_run=run_id)
