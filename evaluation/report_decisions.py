"""Report evidence packets and adapter to the existing deterministic rules engine.

No model grade, automatic policy approval, historical claim replay or fabricated absence.
The operator installs an approved project pack; every result retains its input receipt.
"""

import json
import re
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from proofops.domain.rulepacks import RulePackSnapshot, canonical_json
from proofops.domain.rules.engine import (
    MAPPINGS,
    ConfirmedFact,
    ConfirmedTags,
    RuleContext,
    evaluate,
)
from proofops.domain.values import SourceRef

ROOT = Path(__file__).resolve().parents[1]
GLOBAL_FACTS = {
    "scope",
    "org_boundary",
    "calculation_boundary",
    "method",
    "assurance_covered",
    "external_verification",
}
CONFLICTS = {"parse_conflict", "table_grid_overlap", "numeric_not_in_native_region"}
KEYWORDS = re.compile(
    r"산정|방법론|검증|보증|보고.?범위|조직.?경계|assurance|methodolog|boundary", re.I
)


def digest(value):
    return sha256(canonical_json(value).encode("ascii")).hexdigest()


def load_pack(tenant_id):
    """Only an explicitly installed, hash-pinned operator approval is usable."""
    registry = ROOT / ".local/analysis-policy/registry.json"
    if not registry.is_file():
        return None
    entry = json.loads(registry.read_text(encoding="utf-8")).get(tenant_id)
    if not entry:
        return None
    path = registry.parent / entry["file"]
    if path.resolve().parent != registry.parent.resolve():
        raise ValueError("RULEPACK_PATH_INVALID")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != entry["sha256"]:
        raise ValueError("RULEPACK_INTEGRITY_MISMATCH")
    pack = RulePackSnapshot(**json.loads(raw))
    if (
        pack.tenant_id != tenant_id
        or pack.status != "active"
        or not pack.approved_by
        or not pack.approved_at
    ):
        raise ValueError("RULEPACK_APPROVAL_REQUIRED")
    return pack


def extraction_chunks(blocks, *, max_chars=18000, max_blocks=120):
    """Bounded windows instead of silently discarding the tail of selected pages."""
    chunks, current, length = [], [], 0
    for block in blocks:
        if current and (length + len(block["text"]) > max_chars or len(current) >= max_blocks):
            chunks.append(current)
            current, length = [], 0
        current.append(block)
        length += len(block["text"])
    if current:
        chunks.append(current)
    return chunks


def evidence_packet(claims, blocks, *, max_chars=40000):
    """Search the parsed document, keeping direct origins before contextual candidates."""
    origins = {c["block"] for c in claims}
    pages = {c["page"] for c in claims}
    words = set(re.findall(r"[가-힣A-Za-z]{2,}|20\d{2}", " ".join(c["quote"] for c in claims)))
    scored = []
    for b in blocks:
        terms = words & set(re.findall(r"[가-힣A-Za-z]{2,}|20\d{2}", b["text"]))
        score = 10000 if b["index"] in origins else 100 if b["page"] in pages else 0
        score += len(terms) * 3 + (10 if KEYWORDS.search(b["text"]) else 0)
        if score:
            scored.append((score, b))
    selected, chars = [], 0
    for _, b in sorted(scored, key=lambda x: (-x[0], x[1]["index"])):
        if chars + len(b["text"]) <= max_chars:
            selected.append(b)
            chars += len(b["text"])
    return sorted(selected, key=lambda b: b["index"]), {
        "searched_blocks": len(blocks),
        "candidate_blocks": len(scored),
        "included_blocks": len(selected),
        "truncated": len(selected) < len(scored),
        "absence_certified": False,
    }


def literal_citation(candidate, blocks):
    if not isinstance(candidate, dict) or type(candidate.get("block")) is not int:
        return None
    index, quote = candidate["block"], candidate.get("quote")
    if not 0 <= index < len(blocks) or not isinstance(quote, str) or not quote or len(quote) > 600:
        return None
    b = blocks[index]
    # Preserve raw offsets: normalization must not silently change provenance.
    if b["raw_text"].count(quote) != 1:
        return None
    return dict(
        quote=quote,
        page=b["page"],
        block=index,
        bbox=b["bbox"],
        source_key=b["key"],
        raw_text_sha256=sha256(b["raw_text"].encode()).hexdigest(),
    )


def bind(claim, element, blocks, allowed_scopes):
    """Location is not meaning. Consensus, source checks and attribution are separate."""
    c = element.get("citation")
    if not c:
        return "unknown", "not_found_in_packet", None
    check = element.get("crosscheck") or {}
    origin_check = claim.get("crosscheck") or {}
    if check.get("original_audit") in CONFLICTS or origin_check.get("original_audit") in CONFLICTS:
        return "conflict", "parser_conflict", None
    if not check.get("native_verified") or not claim.get("source_verified"):
        return "unknown", "source_unverified", None
    if not claim.get("tagging_complete"):
        return "unknown", "tagging_incomplete", None
    origin, target = blocks[claim["block"]], blocks[c["block"]]
    # Table layout must be independently checked, not inferred from digit presence.
    if (origin.get("table") or target.get("table")) and check.get("status") != "consensus":
        return "unknown", "table_structure_unverified", None
    name = element["name"]
    if name == "quantitative_or_qualified_ordinal" and not re.search(r"\d", c["quote"]):
        return "unknown", "ordinal_scale_review_required", None
    if name == "method" and not re.search(
        r"산정|계산|측정|계측|계량|배출계수|활동자료|활동데이터|방법론|GHG.?Protocol|"
        r"ISO.?14064|calculat|measur|meter|emission.factor|methodolog",
        c["quote"],
        re.I,
    ):
        return "unknown", "calculation_method_review_required", None
    if name in {"assurance_covered", "external_verification"}:
        # Provider names, self-reported certifications and GRI indexes are not coverage.
        return "unknown", "assurance_scope_review_required", None
    if origin["index"] == target["index"] and claim["quote"].count(c["quote"]) == 1:
        if "local_claim" in allowed_scopes:
            return "present", "accepted_local", "local_claim"
    if (
        "same_table" in allowed_scopes
        and origin.get("table")
        and origin.get("table") == target.get("table")
        and origin["page"] == target["page"]
        and origin["key"].split("/")[0] == target["key"].split("/")[0]
        and all(type(b.get(k)) is int for b in (origin, target) for k in ("row", "column"))
        and check.get("status") == "consensus"
    ):
        same_cell = origin["row"] == target["row"] and origin["column"] == target["column"]
        column_header = (
            target["row"] == 0
            and target["column"] == origin["column"]
            and target.get("column_span", 1) == 1
            and origin.get("column_span", 1) == 1
        )
        if same_cell or (column_header and name in {"target_year", "unit_or_qualified_ordinal"}):
            return "present", "accepted_table", "same_table"
    if name not in GLOBAL_FACTS or "global_bound" not in allowed_scopes:
        return "unknown", "direct_claim_or_table_binding_required", None
    # Cross-location evidence needs explicit sourced entity, metric and year on both sides.
    normalized = claim.get("normalized", {})
    for axis in ("entity", "metric", "year"):
        field = normalized.get(axis, {})
        value = field.get("value")
        if not value or value not in claim["quote"] or value not in c["quote"]:
            return "unknown", "cross_location_identity_unresolved", None
    for axis in ("unit", "denominator", "qualifier"):
        value = normalized.get(axis, {}).get("value")
        if value and value not in c["quote"]:
            return "unknown", "cross_location_scope_unresolved", None
    if re.search(r"제외|미포함|제한|except|exclud|not cover", c["quote"], re.I):
        return "unknown", "scope_exclusion_review_required", None
    claim_years = set(re.findall(r"20\d{2}", claim["quote"]))
    evidence_years = set(re.findall(r"20\d{2}", c["quote"]))
    if evidence_years != claim_years:
        return "conflict", "reporting_period_mismatch", None
    return "present", "accepted_global", "global_bound"


def source_ref(source, block, quote):
    begin = block["raw_text"].index(quote)
    run = block["key"].split("/", 1)[0]
    return SourceRef(
        str(uuid5(NAMESPACE_URL, source.sha256 + block["key"])),
        source.document_version_id,
        run,
        block["page"],
        None,
        tuple(block["bbox"]),
        sha256(block["raw_text"].encode()).hexdigest(),
        quote,
        begin,
        begin + len(quote),
        "located",
        "verified",
    )


def decide(claim, source, blocks, pack):
    if not pack or claim["track"] not in MAPPINGS:
        reason = "project_rulepack_unapproved" if not pack else "track_unclassified"
        claim["decision"] = dict(
            evidence_grade=None,
            label=None,
            grade_range=None,
            decision_status="blocked_rule_gap",
            gate_reasons=[reason],
            missing_elements=[],
        )
        claim["blocked_reason"] = "프로젝트 규칙 승인 필요" if not pack else "주장 트랙 분류 필요"
        return
    definitions = {e["id"]: e for e in pack.file_content("rubric/elements.yaml")["elements"]}
    facts = []
    for element in claim["elements"]:
        state, reason, scope = bind(
            claim, element, blocks, definitions[element["element_id"]]["source_scopes"]
        )
        element.update(state=state, binding_status=reason, source_scope=scope)
        if state == "present":
            c = element["citation"]
            ref = source_ref(source, blocks[c["block"]], c["quote"])
            element["confirmed_ref"] = asdict(ref)
            facts.append(
                ConfirmedFact(
                    element["name"],
                    state,
                    (ref,),
                    source.tenant_id,
                    True,
                    True,
                    source_scope=scope,
                    normalized_value=c["quote"],
                )
            )
        else:
            facts.append(ConfirmedFact(element["name"], state))
    packet = digest(
        {
            "source": source.sha256,
            "claim": claim["quote"],
            "page": claim["page"],
            "track": claim["track"],
            "facts": [asdict(f) for f in facts],
            "evidence_packet": claim.get("evidence_packet_sha256"),
            "pack": pack.sha256,
        }
    )
    claim_id = str(uuid5(NAMESPACE_URL, source.sha256 + str(claim["page"]) + claim["quote"]))
    replicas = tuple(claim.get("replicate_hashes", []))
    if len(replicas) != 3:
        claim["decision"] = dict(
            evidence_grade=None,
            label=None,
            grade_range=None,
            decision_status="blocked_evidence",
            missing_elements=[],
            gate_reasons=["tagging_incomplete"],
        )
        claim["blocked_reason"] = "태깅 3회 미완료 · 재실행 필요"
        return
    tags = ConfirmedTags(
        source.tenant_id,
        source.document_version_id,
        claim_id,
        claim["track"],
        tuple(facts),
        1,
        packet,
        digest(claim.get("model")),
        digest("report-bound-facts-v1"),
        replicas,
        pack.ontology_version,
    )
    decision = evaluate(
        tags, RuleContext(source.tenant_id, source.document_version_id, claim_id, packet), pack
    )
    claim["decision"] = decision.to_api_dict() | {
        "unresolved_elements": list(decision.unresolved_elements),
        "gate_reasons": sorted(
            {e["binding_status"] for e in claim["elements"] if e["state"] != "present"}
        ),
        "approval_scope": "project_rubric_only",
        "expert_gold": False,
    }
    # Unclassified special routes must never silently become ordinary decided claims.
    if re.search(r"최초|최고|유일|세계.?1위|예상|전망|first|best|forecast", claim["quote"], re.I):
        claim["decision"].update(
            evidence_grade=None, label=None, grade_range=None, decision_status="blocked_rule_gap"
        )
        claim["decision"]["gate_reasons"].append("special_route_review_required")
    claim["decision_input"] = {
        "tags": asdict(tags),
        "context": asdict(
            RuleContext(source.tenant_id, source.document_version_id, claim_id, packet)
        ),
        "rulepack_sha256": pack.sha256,
    }
    claim["blocked_reason"] = (
        ""
        if claim["decision"]["evidence_grade"]
        else "판정에 영향을 주는 미해결 요소: "
        + ", ".join(decision.grade_open_elements or decision.unresolved_elements)
    )
    if "special_route_review_required" in claim["decision"]["gate_reasons"]:
        claim["blocked_reason"] = "최상급·예측 특칙 분류 검토 필요"
