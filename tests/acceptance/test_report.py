"""AT-021: report projection over explicit local-synthetic immutable inputs."""

from __future__ import annotations

import json
import subprocess
from copy import deepcopy
from csv import reader
from io import StringIO
from pathlib import Path

import pytest
from proofops.application.reporting import build_report_model, render_report

TENANT = "11111111-1111-4111-8111-111111111111"
RUN = "22222222-2222-4222-8222-222222222222"
DOCUMENT = "55555555-5555-4555-8555-555555555555"
CLAIMS = (
    "33333333-3333-4333-8333-333333333331",
    "33333333-3333-4333-8333-333333333332",
    "33333333-3333-4333-8333-333333333333",
)
HASH = "a" * 64
MODEL = "b" * 64
PROMPT = "c" * 64
REPLICAS = ["1" * 64, "2" * 64, "3" * 64]


def source_ref(*, page=34, quote="2030년까지 탄소 배출량을 40% 감축하겠습니다."):
    return {
        "source_id": "66666666-6666-4666-8666-666666666666",
        "document_version_id": DOCUMENT,
        "parse_manifest_id": DOCUMENT,
        "page_num": page,
        "printed_page_label": None,
        "bbox": [120, 340, 480, 372],
        "raw_text_sha256": HASH,
        "quote": quote,
        "char_start": 0,
        "char_end": len(quote),
        "location_quality": "located",
        "verification_state": "verified",
    }


def manifest():
    return {
        "tenant_id": TENANT,
        "run_id": RUN,
        "document_version_id": DOCUMENT,
        "parse_manifest_id": DOCUMENT,
        "source_sha256": HASH,
        "mutation_epoch": 7,
        "claim_revision_refs": [
            {"claim_id": CLAIMS[0], "tag_revision": 1, "decision_revision": 1},
            {"claim_id": CLAIMS[1], "tag_revision": 2, "decision_revision": 2},
            {"claim_id": CLAIMS[2], "tag_revision": 0, "decision_revision": 0},
        ],
        "rule_pack_hashes": [HASH],
        "coverage": {
            "pages_total": 3,
            "pages_processed": 1,
            "pages_unreadable": 1,
            "pages_unprocessed": 1,
            "chunks_discovered": 3,
            "chunks_processed": 2,
            "claims_discovered": 3,
            "claims_decided": 1,
            "claims_needs_review": 1,
            "full_scope": True,
            "complete": False,
        },
        "unverified_basis": 2,
        "generated_at": "2026-09-09T00:00:00Z",
        "execution_profile": "local-synthetic-only",
    }


def decisions():
    return {
        CLAIMS[0]: {
            "tenant_id": TENANT,
            "document_version_id": DOCUMENT,
            "parse_manifest_id": DOCUMENT,
            "source_sha256": HASH,
            "claim_id": CLAIMS[0],
            "tag_revision": 1,
            "decision_revision": 1,
            "decision_status": "decided",
            "evidence_grade": "E1",
            "label": "INCOMPLETE",
            "review_status": "auto_confirmed",
            "missing_elements": ["G3", "G4"],
            "unresolved_elements": [],
            "gap_ids": ["GAP-005"],
            "rule_pack_sha256": HASH,
            "model_sha256": MODEL,
            "prompt_sha256": PROMPT,
            "replicate_hashes": REPLICAS,
            "source_refs": [source_ref()],
            "basis_refs": [
                json.dumps(
                    {
                        "source_section": "4.4",
                        "clause": None,
                        "verification_status": "unverified",
                        "rule_ids": ["goal-e1"],
                    }
                )
            ],
            "assurance": {
                "status": "not_covered",
                "level": None,
                "provider": None,
                "statement_id": None,
                "metric_match": "no",
                "period_match": "unknown",
                "boundary_match": "unknown",
                "evidence_refs": [],
            },
            "safe_harbor": {
                "claim_id": CLAIMS[0],
                "applicable": False,
                "category": None,
                "checklist": [],
                "reasonable_basis_documented": None,
                "legal_effect": "not_determined",
                "mapping_status": "unresolved",
                "gap_ids": [],
            },
        },
        CLAIMS[1]: {
            "tenant_id": TENANT,
            "document_version_id": DOCUMENT,
            "parse_manifest_id": DOCUMENT,
            "source_sha256": HASH,
            "claim_id": CLAIMS[1],
            "tag_revision": 2,
            "decision_revision": 2,
            "decision_status": "blocked_rule_gap",
            "evidence_grade": None,
            "label": None,
            "review_status": "needs_review",
            "missing_elements": [],
            "unresolved_elements": ["P6"],
            "gap_ids": ["GAP-003"],
            "rule_pack_sha256": HASH,
            "model_sha256": MODEL,
            "prompt_sha256": PROMPT,
            "replicate_hashes": REPLICAS,
            "source_refs": [],
            "basis_refs": [
                {
                    "source_section": "4.5",
                    "clause": None,
                    "verification_status": "unlicensed",
                    "rule_ids": [],
                }
            ],
            "assurance": {
                "status": "undetermined",
                "level": None,
                "provider": None,
                "statement_id": None,
                "metric_match": "unknown",
                "period_match": "unknown",
                "boundary_match": "unknown",
                "evidence_refs": [],
            },
            "safe_harbor": {
                "claim_id": CLAIMS[1],
                "applicable": True,
                "category": "emissions_estimate",
                "checklist": [
                    {
                        "element_id": "uncertainty",
                        "state": "unknown",
                        "evidence_refs": [],
                        "normalized_value": None,
                        "credited_from": None,
                        "reason_code": None,
                    }
                ],
                "reasonable_basis_documented": None,
                "legal_effect": "not_determined",
                "mapping_status": "unresolved",
                "gap_ids": ["GAP-001"],
            },
        },
        CLAIMS[2]: {
            "tenant_id": TENANT,
            "document_version_id": DOCUMENT,
            "parse_manifest_id": DOCUMENT,
            "source_sha256": HASH,
            "claim_id": CLAIMS[2],
            "tag_revision": 0,
            "decision_revision": 0,
            "decision_status": "not_run",
            "evidence_grade": None,
            "label": None,
            "source_refs": [source_ref(page=2, quote="합성 미태깅 주장")],
            "model_sha256": None,
            "prompt_sha256": None,
            "replicate_hashes": [],
        },
    }


def test_report_keeps_partial_work_unverified_clauses_and_source_locations_visible():
    model = build_report_model(manifest(), decisions())

    assert model["schema"] == "report_model_v1"
    assert model["partial"] is True
    assert model["unfinished_count"] == 2
    assert model["coverage"]["pages_unreadable"] == 1
    assert model["coverage"]["pages_unprocessed"] == 1
    assert model["unverified_clause_count"] == 2
    assert len(model["claims"]) == 3

    decided, blocked, not_run = model["claims"]
    assert decided["source_refs"][0] == decisions()[CLAIMS[0]]["source_refs"][0]
    assert decided["basis_refs"][0]["clause"] is None
    assert decided["basis_refs"][0]["verification_status"] == "unverified"
    assert blocked["decision_status"] == "blocked_rule_gap"
    assert blocked["evidence_grade"] is blocked["label"] is None
    assert blocked["unresolved_elements"] == ["P6"]
    assert blocked["safe_harbor"]["mapping_status"] == "unresolved"
    assert blocked["safe_harbor"]["legal_effect"] == "not_determined"
    assert not_run["decision_status"] == "not_run"
    assert not_run["assurance"] == not_run["safe_harbor"] == {"status": "not_run"}
    assert not_run["source_status"] == "available"
    assert not_run["source_refs"][0]["quote"] == "합성 미태깅 주장"
    assert not_run["tag_revision"] == 0
    assert not_run["model_sha256"] is None and not_run["replicate_hashes"] == []


def test_suggestion_names_only_missing_elements_and_never_fills_values():
    model = build_report_model(manifest(), decisions())
    suggestion = model["claims"][0]["suggestion"]

    assert suggestion == "원문 근거로 다음 결손 요소를 보완하세요: G3, G4."
    assert all(value not in suggestion for value in ("2020", "2030", "40%"))
    assert model["claims"][1]["suggestion"] is None
    assert model["claims"][2]["suggestion"] is None


@pytest.mark.parametrize(
    "change",
    [
        "tenant",
        "document",
        "source_document",
        "safe_harbor_claim",
        "untagged_model",
        "decided_no_source",
        "revision",
        "rule_pack",
        "decided_without_grade",
        "missing_claim",
    ],
)
def test_report_rejects_mixed_or_unpinned_revision_inputs(change):
    snapshot, revisions = manifest(), decisions()
    if change == "tenant":
        snapshot["tenant_id"] = "44444444-4444-4444-8444-444444444444"
    elif change == "document":
        revisions[CLAIMS[0]]["document_version_id"] = RUN
    elif change == "source_document":
        revisions[CLAIMS[0]]["source_refs"][0]["document_version_id"] = RUN
    elif change == "safe_harbor_claim":
        revisions[CLAIMS[1]]["safe_harbor"]["claim_id"] = CLAIMS[0]
    elif change == "untagged_model":
        revisions[CLAIMS[2]]["model_sha256"] = MODEL
    elif change == "decided_no_source":
        revisions[CLAIMS[0]]["source_refs"] = []
    elif change == "revision":
        revisions[CLAIMS[0]]["decision_revision"] = 9
    elif change == "rule_pack":
        revisions[CLAIMS[0]]["rule_pack_sha256"] = "b" * 64
    elif change == "decided_without_grade":
        revisions[CLAIMS[0]]["evidence_grade"] = None
    else:
        revisions.pop(CLAIMS[1])

    with pytest.raises(ValueError):
        build_report_model(snapshot, revisions)


def test_report_projection_is_deterministic_and_does_not_mutate_snapshot():
    snapshot, revisions = manifest(), decisions()
    before = deepcopy((snapshot, revisions))

    assert build_report_model(snapshot, revisions) == build_report_model(snapshot, revisions)
    assert (snapshot, revisions) == before


def test_wholly_unavailable_unfinished_claim_remains_explicit_not_run():
    snapshot, revisions = manifest(), decisions()
    revisions[CLAIMS[2]] = None

    claim = build_report_model(snapshot, revisions)["claims"][2]

    assert claim["decision_status"] == claim["source_status"] == "not_run"
    assert claim["source_refs"] == []
    assert claim["model_sha256"] is claim["prompt_sha256"] is None
    assert claim["replicate_hashes"] == []


def test_tagged_unfinished_claim_cannot_drop_its_provenance_record():
    snapshot, revisions = manifest(), decisions()
    snapshot["claim_revision_refs"][2]["tag_revision"] = 1
    revisions[CLAIMS[2]] = None

    with pytest.raises(ValueError):
        build_report_model(snapshot, revisions)


def test_pre_parse_partial_report_keeps_null_manifest_without_inventing_identity():
    snapshot = manifest()
    snapshot["parse_manifest_id"] = None
    snapshot["claim_revision_refs"] = []
    snapshot["coverage"] |= {
        "pages_processed": 0,
        "pages_unreadable": 0,
        "pages_unprocessed": 3,
        "chunks_discovered": 0,
        "chunks_processed": 0,
        "claims_discovered": 0,
        "claims_decided": 0,
        "claims_needs_review": 0,
    }
    snapshot["unverified_basis"] = 0

    model = build_report_model(snapshot, {})

    assert model["parse_manifest_id"] is None
    assert model["partial"] is True
    assert model["claims"] == []


def test_actual_rule_decision_and_safe_harbor_record_flow_into_report():
    from dataclasses import asdict

    from proofops.domain.rules.engine import evaluate
    from proofops.domain.rules.safe_harbor import record_safe_harbor

    from tests.acceptance.test_rules import inputs, pack

    tags, context = inputs()
    rulepack = pack()
    decision = evaluate(tags, context, rulepack)
    source = next(fact.evidence_refs[0] for fact in tags.facts if fact.evidence_refs)
    safe_harbor = record_safe_harbor(tags, context, rulepack)
    pinned = {
        "tenant_id": tags.tenant_id,
        "run_id": RUN,
        "document_version_id": tags.document_version_id,
        "parse_manifest_id": source.parse_manifest_id,
        "source_sha256": source.raw_text_sha256,
        "mutation_epoch": 1,
        "claim_revision_refs": [
            {
                "claim_id": tags.claim_id,
                "tag_revision": tags.tag_revision,
                "decision_revision": decision.decision_revision,
            }
        ],
        "rule_pack_hashes": [rulepack.sha256],
        "coverage": {
            "pages_total": 1,
            "pages_processed": 1,
            "pages_unreadable": 0,
            "pages_unprocessed": 0,
            "chunks_discovered": 1,
            "chunks_processed": 1,
            "claims_discovered": 1,
            "claims_decided": 1,
            "claims_needs_review": 0,
            "full_scope": True,
            "complete": True,
        },
        "unverified_basis": len(decision.basis_refs),
        "generated_at": "2026-09-09T00:00:00Z",
        "execution_profile": "local-synthetic-only",
    }
    revision = asdict(decision) | {
        "tenant_id": tags.tenant_id,
        "document_version_id": tags.document_version_id,
        "parse_manifest_id": source.parse_manifest_id,
        "source_sha256": source.raw_text_sha256,
        "claim_id": tags.claim_id,
        "model_sha256": tags.model_sha256,
        "prompt_sha256": tags.prompt_sha256,
        "replicate_hashes": list(tags.replicate_hashes),
        "source_refs": [asdict(source)],
        "assurance": {
            "status": "covered",
            "level": "limited",
            "provider": "Synthetic provider",
            "statement_id": source.source_id,
            "metric_match": "yes",
            "period_match": "yes",
            "boundary_match": "yes",
            "evidence_refs": [asdict(source)],
        },
        "safe_harbor": safe_harbor.to_api_dict(),
    }

    model = build_report_model(pinned, {tags.claim_id: revision})

    assert model["claims"][0]["evidence_grade"] == decision.evidence_grade == "E3"
    assert model["claims"][0]["safe_harbor"] == safe_harbor.to_api_dict()
    assert model["claims"][0]["source_refs"][0]["quote"] == source.quote


def test_stdlib_renderers_escape_html_and_guard_csv_formulas():
    revisions = decisions()
    revisions[CLAIMS[0]]["source_refs"] = [source_ref(quote='=HYPERLINK("bad")<script>')]
    model = build_report_model(manifest(), revisions)

    assert json.loads(render_report(model, "json")) == model
    html = render_report(model, "html").decode()
    assert "<script>" not in html and "&lt;script&gt;" in html
    for text in (
        "E1",
        "INCOMPLETE",
        "auto_confirmed",
        "tag revision 1",
        "decision revision 1",
        "미완료 2건",
        "미확인 조항 2건",
        "120.0, 340.0, 480.0, 372.0",
        "감사 세부정보",
        "model_sha256",
    ):
        assert text in html
    rows = list(reader(StringIO(render_report(model, "csv").decode())))
    quote = rows[1][rows[0].index("source_quotes")]
    assert quote.startswith("'") and not quote.startswith("=")
    assert json.loads(rows[1][rows[0].index("source_refs")]) == model["claims"][0]["source_refs"]
    with pytest.raises(ValueError):
        render_report(model, "pdf")


def test_report_preview_renders_partial_and_unverified_states(tmp_path):
    root = Path(__file__).resolve().parents[2]
    esbuild = next((root / "node_modules/.pnpm").glob("esbuild@*/node_modules/esbuild/bin/esbuild"))
    entry = tmp_path / "report-render.tsx"
    entry.write_text(
        """
import React from REACT;
import { renderToStaticMarkup } from SERVER;
import { ReportPreview } from COMPONENT;
import assert from "node:assert/strict";
const report=REPORT;
const html=renderToStaticMarkup(React.createElement(ReportPreview,{report}));
for (const text of ["검토용 부분 리포트","미완료 2건","판독 불가 1쪽","미처리 1쪽",
"p.34","G3, G4","조항 미확인","보증 범위 밖","세이프하버 미실행",MODEL,PROMPT,
"규칙 공백으로 미판정"])
  assert.ok(html.includes(text), text);
console.log("ReportPreview audit-state checks passed");
""".replace("REACT", json.dumps(str(root / "apps/web/node_modules/react/index.js")))
        .replace("SERVER", json.dumps(str(root / "apps/web/node_modules/react-dom/server.node.js")))
        .replace(
            "COMPONENT", json.dumps(str(root / "apps/web/src/features/reports/ReportPreview.tsx"))
        )
        .replace("REPORT", json.dumps(build_report_model(manifest(), decisions())))
        .replace("MODEL", json.dumps(MODEL))
        .replace("PROMPT", json.dumps(PROMPT))
    )
    bundle = tmp_path / "report-render.cjs"
    subprocess.run(
        [
            str(esbuild),
            str(entry),
            "--bundle",
            "--platform=node",
            "--format=cjs",
            "--jsx=automatic",
            f"--outfile={bundle}",
        ],
        check=True,
        capture_output=True,
    )
    rendered = subprocess.run(["node", str(bundle)], check=True, capture_output=True, text=True)
    assert "checks passed" in rendered.stdout
