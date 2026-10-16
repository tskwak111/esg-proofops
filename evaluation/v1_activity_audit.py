"""Offline V1 audit of fixed R17, actual DL4-131 and four-company holdout.

Retained runs lacking independent same-run inventory are not retagged by fiat.
The separate synthetic contract measurement exercises the production SC1 path;
it is not a real-model improvement claim. All source artifacts stay read-only.
"""

import argparse
import importlib.util
import json
import socket
from collections import Counter
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory

from proofops.application.analysis_profile import FINALS_I24_POLICY, V1_ACTIVITY_POLICY
from proofops.application.tagging.analysis_scope import InventoryIndex, analyze_scope
from proofops.application.tagging.element_inventory import (
    assemble_inventory,
    plan_inventory,
    selection_from_snapshot,
)
from proofops.application.tagging.v1_activity_links import POLICY, link_inventory
from proofops.domain.errors import DomainValidationError
from proofops.domain.provenance import canonical_hash

from evaluation.qt2_replay import cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    lab = args.root / "outputs/agent-results/R108-redesign/lab"
    args.output.mkdir(parents=True, exist_ok=True)
    hashes = {}

    def read(path):
        hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
        return json.loads(path.read_text())

    def deny(*a, **kw):
        raise AssertionError("V1_AUDIT_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    audit = read(lab / "review/R17/audit.json")
    reports, rows, indices, checked, source_rejected = {}, [], {}, Counter(), {}
    for report in audit["reports"]:
        path = args.root / report["result_path"]
        read(path)
        assert hashes[str(path)] == report["result_sha256"]
        source = Path(report["source_pdf"])
        hashes[str(source)] = sha256(source.read_bytes()).hexdigest()
        assert hashes[str(source)] == report["source_sha256"]
        artifacts = read(lab / "quality/QT2/stored" / report["run_id"] / "job-artifacts.json")
        assert not any("sc1_inventory" in x["value"] for x in artifacts)
        counts = Counter(
            claims=0,
            provisional=0,
            hold=0,
            confirmed=0,
            scoped_confirmed=0,
            present_recalled=0,
            gold_present=0,
            false_present=0,
            false_confirmed=0,
            scored_elements=0,
            source_verified=0,
        )
        for row in report["rows"]:
            if row["record_type"] != "claim":
                continue
            counts["claims"] += 1
            counts["confirmed"] += bool(row.get("confirmed_grade"))
            counts["provisional"] += bool(row.get("provisional_grade"))
            counts["hold"] += not row.get("confirmed_grade") and not row.get("provisional_grade")
            counts["source_verified"] += row["source_quality"] == "verified"
            for element in row["elements"]:
                if not element["scored"]:
                    continue
                counts["scored_elements"] += 1
                counts["gold_present"] += element["gold_state"] == "present"
                counts["present_recalled"] += (
                    element["server_state"] == element["gold_state"] == "present"
                )
                counts["false_present"] += (
                    element["server_state"] == "present" and element["gold_state"] != "present"
                )
            assert not row.get(
                "confirmed_grade"
            ), "New baseline confirmations need individual audit"
            rows.append(
                dict(
                    case=report["case"],
                    claim_id=row["claim_id"],
                    status="retag_required",
                    reason="NO_SAME_RUN_INDEPENDENT_SC1_INVENTORY",
                    new_links=0,
                )
            )
        reports[report["case"]] = dict(
            before=dict(counts),
            after=dict(counts),
            new_false_present=0,
            new_false_confirmed=0,
            recovered_present=0,
        )

    # Exercise the actual new reader on the archived source catalogs. Empty raw
    # response maps model the observed missing inventory; no fabricated votes.
    from tests.acceptance.test_rules import pack

    for report, row, item, graph, context in cases(lab / "quality/QT2/stored", audit):
        run_id = report["run_id"]
        if run_id not in indices:
            selected = sorted({b.page_num for b in graph.blocks})
            selection = selection_from_snapshot(
                dict(
                    document=dict(
                        version_id=graph.document_version_id,
                        sha256=graph.source_sha256,
                        page_count=max(selected),
                    ),
                    selected_pages=selected,
                ),
                graph,
                run_id,
            )
            try:
                inv = assemble_inventory(
                    plan_inventory(graph, selection), {}, graph=graph, model_sha256="a" * 64
                )
                indices[run_id] = InventoryIndex(inv, graph)
            except DomainValidationError as error:
                indices[run_id] = None
                source_rejected[report["case"]] = str(error)
        if indices[run_id] is None:
            continue
        result = link_inventory(
            context,
            indices[run_id],
            graph,
            run_id=run_id,
            tenant_id=graph.tenant_id,
            rulepack=replace(pack(), tenant_id=graph.tenant_id),
            policy=POLICY,
        )
        assert result["links"] == []
        checked[report["case"]] += 1

    scorer = args.root / ".local/g1-gold/evaluation/dl4_gold.py"
    hashes[str(scorer)] = sha256(scorer.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("v1_frozen_dl4", scorer)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dl4 = read(lab / "perf/I3/dl4-reference/DL4-gold.json")
    assert len(dl4["golds"]) == 131
    qt1 = read(lab / "quality/QT1/cohort-results.json")
    predictions = []
    for company in ("naver", "kia"):
        before = read(lab / "perf/I23/dl4" / f"{company}-after.json")
        predictions.extend(p | dict(company=company) for p in before + qt1["dl4"][company]["added"])
    dl4_score = module.evaluate(dl4["golds"], predictions)
    pending = read(lab / "perf/I3/dl4-reference/denominator-audit.json")["pending_scope"]
    holdout_gold = read(lab / "fix/A/paid-dec26/v1-gold-atoms.json")
    holdout_predictions = []
    for company in ("SK하이닉스", "현대자동차", "POSCO홀딩스", "삼성전자"):
        holdout_predictions.extend(
            read(lab / "perf/I23/holdout/holdout" / company / "predictions.json")
        )
    holdout_score = module.evaluate(holdout_gold, holdout_predictions)

    from tests.integration.test_r19_activity_links import diagram_case, links, scope_inputs

    with TemporaryDirectory(prefix="v1-audit-") as tmp:
        inputs = scope_inputs(Path(tmp))
        old = analyze_scope(**inputs)
        new = analyze_scope(**inputs, v1_activity_policy=POLICY)
        assert old["sc1_confirmation"] is None and new["sc1_confirmation"]["evidence_grade"] == "E2"
        synthetic = dict(
            before=old,
            after=new,
            raw_replicas_sha256=canonical_hash([asdict(r) for r in inputs["runs"]]),
            label="synthetic_contract_only_not_model_accuracy",
        )
        (args.output / "synthetic-scope-comparison.json").write_text(
            json.dumps(synthetic, ensure_ascii=False, indent=2) + "\n"
        )
    context, graph, inv = diagram_case()
    d11 = links(context, graph, inv)
    assert len(d11["links"]) == 1
    (args.output / "D11-synthetic-links.json").write_text(
        json.dumps(d11, ensure_ascii=False, indent=2) + "\n"
    )
    result = dict(
        schema="v1-r19-offline-measurement-v1",
        baseline_code="6c6241f",
        model_calls=0,
        actual_openai_api_calls=0,
        network="denied",
        v24_default_sha256=canonical_hash(FINALS_I24_POLICY),
        opt_in_sha256=canonical_hash(V1_ACTIVITY_POLICY),
        r17=reports,
        r17_rows=rows,
        production_missing_inventory_checks=dict(checked),
        archived_source_rejected=source_rejected,
        semantic_candidates_deduplicated=[
            dict(
                case="lg-p36",
                claim_id="0a7c7e05-e5fc-59d1-a9dd-bccae44e9af4",
                status="retag_required",
                reason=(
                    "new ISO14001 activity role and verified boundary inventory required; "
                    "original C3 hold preserved"
                ),
            ),
            dict(
                case="kakao-p55",
                claim_id="3071ea9e-765a-5db4-9d90-cf8db7480bc7",
                status="retag_required",
                reason=(
                    "metric/period unresolved; retain main-direct-sites >=95% qualifier; "
                    "M3 dedicated DEC43 unchanged"
                ),
            ),
            dict(
                case="lge-p31",
                claim_id="ca12a731-a076-5f8a-88fd-6fd0014aa572",
                status="held",
                reason="source unverified; expanding to all sites is not current certification",
            ),
        ],
        dl4=dict(
            before=dl4_score,
            after=dl4_score,
            pending_scope=pending,
            grade_element_metrics=(
                "not_measured: extraction gold/receipts lack same-run inventory "
                "and element gold; no new grade is issued"
            ),
        ),
        holdout=dict(
            before=holdout_score,
            after=holdout_score,
            grade_element_metrics=(
                "not_measured: extraction-only held-out predictions; "
                "no invented element/grade votes"
            ),
        ),
        limitation=(
            "Saved E14/v23 receipts and I24 adopted extraction outputs, "
            "not new v25 production inference. Synthetic source/role fixtures "
            "are separate. No demonstrated real-run grade gain."
        ),
        inputs_sha256=hashes,
    )
    for path, digest in hashes.items():
        assert sha256(Path(path).read_bytes()).hexdigest() == digest
    (args.output / "measurements.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            dict(
                r17=reports,
                checked=checked,
                dl4={k: dl4_score[k] for k in ("gold_denominator", "predictions", "matches")},
                holdout={
                    k: holdout_score[k] for k in ("gold_denominator", "predictions", "matches")
                },
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
