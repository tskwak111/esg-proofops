"""Offline V2 delta on frozen R17/E14, canonical DL4=131 and held-out atoms.

Saved responses are diagnostic replays, never new independent model votes or
published revisions. No invented SC1 inventory, absence, or source verification.
"""

import argparse
import importlib.util
import json
import socket
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from proofops.adapters.aws.usage import LocalSQLiteUsageStore
from proofops.adapters.cache.aws import ImmutableResponseCache, InMemoryImmutableCacheClient
from proofops.adapters.parsing.parser_artifacts import iter_parser_artifacts
from proofops.application.analysis_profile import FINALS_I24_POLICY, QT1_V25_POLICY
from proofops.application.budget import BudgetLimits, RoleLimit, TokenUsage
from proofops.application.evidence.binding import local_relation_tags
from proofops.application.evidence.retrieval import freeze_packet
from proofops.application.ingest.qt1_goal_split import refine_selected
from proofops.application.ports.models import ModelBinding
from proofops.application.tagging.consensus import form_consensus
from proofops.application.tagging.qt1_tuples import augment_packet, tuples_for
from proofops.application.tagging.service import RawTagResponse, TaggingSettings, tag_replicates
from proofops.application.tagging.tracks import TrackCandidate
from proofops.application.tagging.unattended import provisional_result
from proofops.domain.provenance import canonical_hash
from proofops.domain.rules.engine import RuleContext

from evaluation.pa9_source_gate import fixture
from evaluation.qt2_replay import cases, packet_for, read


def refine_predictions(predictions):
    """Replay literal extraction only; parent verification/votes do not transfer."""
    result, changes = [], []
    for p in predictions:
        text = p["quote"]
        span = dict(kind="claim", quote=text, char_start=0, char_end=len(text))
        children, receipts = refine_selected([span], text, kind="paragraph")
        if not receipts:
            result.append(p)
            continue
        changes.append(dict(parent_id=p["id"], parent_quote=text, children=children))
        for child in children:
            result.append(
                dict(
                    id=canonical_hash(dict(parent=p["id"], child=child)),
                    company=p["company"],
                    page=p["page"],
                    quote=child["quote"],
                    source_verified=False,
                    verification="pending-child-reverification; no-parent-proof-inheritance",
                )
            )
    return result, changes


def replay(item, graph, context, out, enabled):
    from tests.acceptance.test_rules import pack

    packet = packet_for(item, graph, context, True)  # v24 already includes QT2
    data = packet.to_dict()
    data.pop("packet_sha256")
    data["run_id"] = str(uuid4())
    if enabled:
        augment_packet(data, context.claim, graph, tenant_id=graph.tenant_id)
    packet = freeze_packet(data)
    rules = replace(pack(), tenant_id=graph.tenant_id)
    assert rules.sha256 == data["rule_sha256"]
    raw = {
        r["guarded"]["replicate_id"]: json.loads(r["raw_response_json"])
        for r in item["tag_runs"]
        if r.get("guarded") and r.get("raw_response_json")
    }
    if set(raw) != {1, 2, 3}:
        return None
    settings = TaggingSettings(
        ModelBinding("qt1-v25-offline", "tagger", True),
        "stored-E14",
        "qt1-v25",
        "offline",
        "Diagnostic saved responses; no provider calls.",
        Path("contracts/jsonschema/llm_tags.schema.json").read_text(),
        max_tokens=100,
    )
    usage = LocalSQLiteUsageStore(out / "diagnostic-budget.sqlite3")
    usage.create_budget(
        graph.tenant_id,
        data["run_id"],
        graph.document_version_id,
        BudgetLimits(100000, 100000, (RoleLimit("tagger", 3, 10000, 10000, 100000),)),
    )

    def respond(request):
        payload = deepcopy(raw[request["replicate_id"]])
        payload.update({k: request[k] for k in ("claim_id", "packet_sha256", "replicate_id")})
        return RawTagResponse(
            json.dumps(payload, ensure_ascii=False),
            TokenUsage(1, 1, 0, 0, 1, "succeeded", f"stored-replay-{request['replicate_id']}"),
            True,
        )

    runs = tag_replicates(
        packet=packet,
        context=context,
        track=TrackCandidate(context.claim, data["track"], data.get("safe_harbor_category")),
        original=graph,
        relation_tags=local_relation_tags(context),
        rulepack=rules,
        settings=settings,
        cache=ImmutableResponseCache(InMemoryImmutableCacheClient()),
        usage_store=usage,
        invoke=respond,
        tenant_id=graph.tenant_id,
        ensemble_id=str(uuid4()),
        consent_profile="qt1-v25-offline",
        token_counter=lambda _: 1,
        now=lambda: 1,
        semantic_policy=FINALS_I24_POLICY["semantic_admission"],
        pipeline_profile="finals-unattended-v2",
        allow_edge_whitespace=True,
    )
    assert all(r.guarded for r in runs), [r.errors for r in runs]
    consensus = form_consensus(
        runs,
        packet=packet,
        rulepack=rules,
        tenant_id=graph.tenant_id,
        tag_revision=1,
        profile=FINALS_I24_POLICY["fact_assembly_profile"],
    )
    rc = RuleContext(
        graph.tenant_id,
        graph.document_version_id,
        context.claim.claim_id,
        packet.packet_sha256,
        local_synthetic=True,
    )
    projection = provisional_result(runs, packet, rules, rc, range_profile=True)
    return dict(
        states={e.element_id: e.state for e in consensus.candidate_elements},
        projection=projection,
        tuples=data.get("qt1_table_tuples", []),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    lab = args.root / "outputs/agent-results/R108-redesign/lab"
    out = args.output
    out.mkdir(parents=True, exist_ok=True)

    def deny(*args, **kwargs):
        raise AssertionError("QT1_V25_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    manifest = {}

    def load(path):
        manifest[str(path)] = sha256(path.read_bytes()).hexdigest()
        return read(path)

    audit = load(lab / "review/R17/audit.json")
    for report in audit["reports"]:
        directory = lab / "quality/QT2/stored" / report["run_id"]
        for path in [
            directory / "job-artifacts.json",
            *iter_parser_artifacts(directory, "candidates.json"),
            *directory.rglob("manifest.json"),
        ]:
            manifest[str(path)] = sha256(path.read_bytes()).hexdigest()
    outcomes, details, tables = {}, [], {}
    for report, row, item, graph, context in cases(lab / "quality/QT2/stored", audit):
        before = replay(item, graph, context, out, False)
        after = replay(item, graph, context, out, True)
        if before is None or after is None:
            continue
        outcomes[row["claim_id"]] = (before, after)
        details.append(
            dict(case=report["case"], claim_id=row["claim_id"], before=before, after=after)
        )
        if report["case"] not in tables:
            tables[report["case"]] = [
                t for b in graph.blocks if b.kind == "table" for t in tuples_for(b, graph)
            ]
    metrics = {}
    for report in audit["reports"]:
        stats = Counter()
        for row in report["rows"]:
            if row.get("record_type") != "claim":
                continue
            pair = outcomes.get(row["claim_id"])
            stats["sample_claims"] += 1
            changed = False
            for element in row["elements"]:
                if not element["scored"]:
                    continue
                stats["element_slots"] += 1
                gold, before = element["gold_state"], element["server_state"]
                after = before
                if pair and element["element_id"] in ("P1", "P2"):
                    old = pair[0]["states"].get(element["element_id"], "unknown")
                    new = pair[1]["states"].get(element["element_id"], "unknown")
                    if old != new:
                        after = new
                        changed = True
                for label, state in (("before", before), ("after", after)):
                    stats[label + "_true_present"] += state == gold == "present"
                    stats[label + "_false_present"] += state == "present" and gold != "present"
            if pair:
                for label, value in zip(("before", "after"), pair):
                    stats[label + "_replayed_claims"] += 1
                    stats[label + "_range_display"] += (
                        value["projection"]["display_type"] == "range"
                    )
                    stats[label + "_provisional_grade"] += (
                        value["projection"]["evidence_grade"] is not None
                    )
                    stats[label + "_no_grade"] += value["projection"]["evidence_grade"] is None
            else:
                stats["without_three_saved_responses"] += 1
            before_grade = row["provisional_grade"]
            after_grade = pair[1]["projection"]["evidence_grade"] if changed else before_grade
            for label, value in (("before", before_grade), ("after", after_grade)):
                stats[label + "_frozen_sample_provisional"] += value is not None
                stats[label + "_frozen_sample_held"] += value is None
        metrics[report["case"]] = dict(
            stats,
            stored_E14_population=report["population"],
            before_confirmed=0,
            after_confirmed=0,
            false_confirmed=0,
            scope_confirmation="not_run: E14 has no SC1 inventory; no fabricated search receipts",
            tuple_candidates=len(tables.get(report["case"], [])),
            source_verified_tuples=sum(t["admitted"] for t in tables.get(report["case"], [])),
        )
    scorer_path = args.root / ".local/g1-gold/evaluation/dl4_gold.py"
    manifest[str(scorer_path)] = sha256(scorer_path.read_bytes()).hexdigest()
    spec = importlib.util.spec_from_file_location("qt1_v25_frozen_scorer", scorer_path)
    scorer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(scorer)
    qt1 = load(lab / "perf/I24/qt1/cohort-results.json")
    dl4_gold = load(lab / "perf/I3/dl4-reference/DL4-gold.json")
    assert len(dl4_gold["golds"]) == 131
    predictions = []
    for company in ("naver", "kia"):
        before = load(lab / f"perf/I23/dl4/{company}-after.json")
        predictions += [p | dict(company=company) for p in before + qt1["dl4"][company]["added"]]
        graph, _, _, _, _ = fixture(lab / f"perf/PA9/{company}-server")
        tables[company] = [
            t for b in graph.blocks if b.kind == "table" for t in tuples_for(b, graph)
        ]
    refined_dl4, dl4_changes = refine_predictions(predictions)
    dl4_score = scorer.evaluate(dl4_gold["golds"], predictions)
    dl4_after = scorer.evaluate(dl4_gold["golds"], refined_dl4)
    holdout_gold = load(lab / "fix/A/paid-dec26/v1-gold-atoms.json")
    held = []
    for company in ("SK하이닉스", "현대자동차", "POSCO홀딩스", "삼성전자"):
        before = load(lab / f"perf/I23/holdout/holdout/{company}/predictions.json")
        held += before + qt1["holdout"]["companies"][company]["added"]
    holdout_score = scorer.evaluate(holdout_gold, held)
    refined_holdout, holdout_changes = refine_predictions(held)
    holdout_after = scorer.evaluate(holdout_gold, refined_holdout)
    recovery = load(lab / "quality/QT1/r17-recovery.json")
    equivalence = load(lab / "perf/I24/qt1/recovery-equivalence.json")
    result = dict(
        scope="saved-response diagnostic; no model accuracy, new votes or published decisions",
        baseline_commit="6c6241f",
        baseline_policy_sha256=canonical_hash(FINALS_I24_POLICY),
        new_policy_sha256=canonical_hash(QT1_V25_POLICY),
        r17=metrics,
        dl4=dict(
            denominator=131,
            before=dl4_score,
            after=dl4_after,
            refinements=dl4_changes,
            element_grades="not_run: DL4 fixtures have extraction but no element/grade gold",
        ),
        holdout=dict(
            denominator=len(holdout_gold),
            before=holdout_score,
            after=holdout_after,
            refinements=holdout_changes,
            element_grades="not_run: holdout fixtures have extraction but no element/grade gold",
        ),
        inherited_qt1_recovery={
            k: {f: v[f] for f in ("before_missing", "recovered_any", "recovered_complete")}
            for k, v in recovery["cases"].items()
        },
        i24_recovery_equivalence=equivalence,
        added_literal_candidates=len(refined_dl4)
        - len(predictions)
        + len(refined_holdout)
        - len(held),
        new_verified_claims=0,
        published_confirmations=0,
        false_confirmations_added=0,
        model_calls=0,
        network="denied",
        inputs=manifest,
    )
    for name, value in (
        ("cohort-results.json", result),
        ("r17-details.json", details),
        ("table-tuples.json", tables),
        ("holdout-after.json", refined_holdout),
    ):
        (out / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            dict(
                r17=metrics,
                dl4={
                    k: dl4_score[k]
                    for k in ("gold_denominator", "predictions", "matches", "precision", "recall")
                },
                holdout={
                    k: holdout_score[k]
                    for k in ("gold_denominator", "predictions", "matches", "precision", "recall")
                },
                holdout_after={
                    k: holdout_after[k]
                    for k in ("gold_denominator", "predictions", "matches", "precision", "recall")
                },
            ),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
