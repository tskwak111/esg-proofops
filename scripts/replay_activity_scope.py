"""Free DEC-23 replay of saved gold-v2 report-wide candidates (no model/network)."""

import argparse
import copy
import json
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from proofops.application.evidence.report_level import (
    ACTIVITY_SCOPE_V2,
    REPORT_SCOPE_V1,
    REPORT_WIDE_SCOPE_NOT_ACTIVITY_SCOPE,
    check_report_level,
)
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import pack_content_hash, snapshot_from_validated
from proofops.domain.rules.engine import ConfirmedFact, ConfirmedTags, RuleContext, evaluate
from proofops.domain.values import SourceRef


def read(path):
    return json.loads(path.read_text())


def source(raw):
    if "physical_page" not in raw:
        return SourceRef(**raw)
    return SourceRef(
        raw["source_id"],
        raw["document_version_id"],
        str(uuid5(NAMESPACE_URL, "native/" + raw["pdf_sha256"])),
        raw["page_num"],
        str(raw["page_num"]),
        tuple(raw["bbox"]),
        raw["raw_text_sha256"],
        raw["quote"],
        raw["char_start"],
        raw["char_end"],
        "located",
        "verified",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = args.lab_root
    paths = {
        "returned": lab / "gold-v2/v1-reingested.json",
        "draft": lab / "gold-v1/evidence-search-draft.json",
        "inputs": lab / "gold-v1/engine-inputs-v2.json",
        "pack": lab / "gold-v1/engine-rulepack-snapshot.json",
        "pages": lab / "gold-v2/source-pages.json",
        "findings": lab / "gold-v2/findings.json",
        "original_draft": lab / "gold-v1/draft.json",
    }
    paths.update(
        {f"native_{c}": lab / f"gold-v1/native/{c}.json" for c in ("sk", "hyundai", "posco")}
    )
    before_hashes = {k: sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}
    returned = read(paths["returned"])["sheets"]["4_문서전체근거"]
    draft = {c["claim_id"]: c for c in read(paths["draft"])["claims"]}
    inputs = {c["claim_id"]: c for c in read(paths["inputs"])}
    pages = {
        c: {i + 1: [r["text"]] for i, r in enumerate(read(paths[f"native_{c}"]))}
        for c in ("sk", "hyundai", "posco")
    }
    original_claims = {c["claim_id"]: c for c in read(paths["original_draft"])["claims"]}
    saved = read(paths["pack"])
    old = snapshot_from_validated(saved["manifest"], saved["files"])
    new_saved = copy.deepcopy(saved)
    manifest, files = new_saved["manifest"], new_saved["files"]
    manifest.update(
        version=old.version + "-dec23-scope-v2",
        effective_date="2026-10-10",
        rule_pack_id=str(uuid5(NAMESPACE_URL, old.sha256 + ACTIVITY_SCOPE_V2)),
        status="draft",
        approved_by=None,
        approved_at=None,
    )
    for value in files.values():
        if "version" in value:
            value["version"] = manifest["version"]
    next(e for e in files["rubric/elements.yaml"]["elements"] if e["id"] == "M2")[
        "binding_policy"
    ] = ACTIVITY_SCOPE_V2
    manifest["sha256"] = pack_content_hash(manifest, files)
    new = snapshot_from_validated(manifest, files)
    rows, changes, decisions = [], [], []
    for row in returned:
        cid = row["주장ID"]
        claim = draft[cid]
        m2 = next((e for e in claim["elements"] if e["element_id"] == "M2"), None)
        after_state = m2["applied_state"] if m2 else None
        candidates = []
        if m2:
            for candidate in m2["candidates"]:
                if candidate["policy"] != REPORT_SCOPE_V1:
                    continue
                refs = tuple(source(r) for r in candidate["evidence_refs"])
                claim_refs = tuple(source(r) for r in claim["source_refs"])
                page_texts = pages[claim["company_id"]]
                common = dict(
                    claim_refs=claim_refs,
                    claim_quote=original_claims[cid]["quote"],
                    page_texts=page_texts,
                    credited_from=refs[0].source_id,
                )
                prior_literal = check_report_level("M2", REPORT_SCOPE_V1, refs, **common)
                assert prior_literal == candidate["policy_check"]["literal_check"], cid
                admitted = check_report_level("M2", ACTIVITY_SCOPE_V2, refs, **common)
                assert admitted is False
                candidates.append(
                    dict(
                        before_admitted=candidate["admitted"],
                        after_admitted=admitted,
                        before_literal=prior_literal,
                        refs=candidate["evidence_refs"],
                        reason_code=REPORT_WIDE_SCOPE_NOT_ACTIVITY_SCOPE,
                    )
                )
                if candidate["admitted"]:
                    after_state = "unknown"
                    changes.append(cid)
        before_agreed = row["확인 판정"] == "맞음"
        # The returned ES-18 memo names an additional M1 defect outside DEC-23.
        remaining = ["M1 requires separate correction"] if row["ID"] == "ES-18" else []
        after_agreed = before_agreed or (cid in changes and not remaining)
        rows.append(
            dict(
                review_id=row["ID"],
                claim_id=cid,
                returned_verdict=row["확인 판정"],
                before_row_agreement=before_agreed,
                after_row_agreement=after_agreed,
                before_m2=m2["applied_state"] if m2 else None,
                after_m2=after_state,
                scope_error_resolved=cid in changes,
                candidates=candidates,
                remaining_out_of_scope=remaining,
                returned_memo=row["메모"],
            )
        )
        raw = inputs[cid]
        t = copy.deepcopy(raw["tags"])
        facts = tuple(
            ConfirmedFact(**(f | {"evidence_refs": tuple(source(r) for r in f["evidence_refs"])}))
            for f in t.pop("facts")
        )
        before_tags = ConfirmedTags(**t, facts=facts)
        context = RuleContext(**raw["context"])
        before = evaluate(before_tags, context, old)
        assert asdict(before) == {
            k: v for k, v in claim["engine_expected_v2"].items() if k != "expected"
        } or canonical_hash(asdict(before)) == canonical_hash(
            {k: v for k, v in claim["engine_expected_v2"].items() if k != "expected"}
        ), cid
        after_facts = tuple(
            replace(
                f,
                state="unknown",
                citation_verified=False,
                binding_accepted=False,
                search_coverage_verified=False,
                normalized_value=None,
            )
            if cid in changes and f.name == "org_boundary"
            else f
            for f in facts
        )
        packet_hash = canonical_hash(
            {
                "previous_packet": before_tags.packet_sha256,
                "scope_policy": ACTIVITY_SCOPE_V2,
                "facts": asdict(before_tags) | {"facts": [asdict(f) for f in after_facts]},
            }
        )
        after_tags = replace(
            before_tags,
            facts=after_facts,
            tag_revision=before_tags.tag_revision + 1,
            packet_sha256=packet_hash,
        )
        after = evaluate(
            after_tags,
            replace(
                context, packet_sha256=packet_hash, decision_revision=context.decision_revision + 1
            ),
            new,
        )
        decisions.append(
            dict(
                claim_id=cid,
                before=asdict(before),
                after=asdict(after),
                after_tags=asdict(after_tags),
            )
        )
    assert len(returned) == 45 and len(set(changes)) == 8
    assert all(r["after_row_agreement"] for r in rows if r["before_row_agreement"])
    assert before_hashes == {k: sha256(p.read_bytes()).hexdigest() for k, p in paths.items()}
    summary = dict(
        rows=45,
        before_agreement=sum(r["before_row_agreement"] for r in rows),
        after_agreement=sum(r["after_row_agreement"] for r in rows),
        m2_errors_resolved=8,
        preserved_correct_rows=34,
        new_absent=0,
        changed_review_ids=[r["review_id"] for r in rows if r["scope_error_resolved"]],
        unresolved_review_ids=[r["review_id"] for r in rows if not r["after_row_agreement"]],
        grades_before=dict(Counter(d["before"]["evidence_grade"] or "null" for d in decisions)),
        grades_after=dict(Counter(d["after"]["evidence_grade"] or "null" for d in decisions)),
    )
    args.output.mkdir(parents=True, exist_ok=True)
    result = dict(
        policy=ACTIVITY_SCOPE_V2,
        inputs_sha256=before_hashes,
        originals_unchanged=True,
        old_pack_sha256=old.sha256,
        new_pack_sha256=new.sha256,
        summary=summary,
        rows=rows,
        decisions=decisions,
        limits="Saved AI draft / partial adjudication, not human full gold "
        "or production PDF-to-grade evaluation; full-row agreement is memo-based replay, "
        "not a new independent review. ES-18 M1 and other non-M2 defects remain.",
        model_calls=0,
        aws="not_run",
        paid_cost_usd=0,
    )
    (args.output / "replay.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    (args.output / "rulepack-v2.json").write_text(
        json.dumps(new_saved, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
