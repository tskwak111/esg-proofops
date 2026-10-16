"""H1 fresh extraction on A's immutable parsing, with the frozen A/G1 scorer.

No grade/tag revision writer or parser/OCR transport is used. Source proofs are
recomputed against the same PDF and trusted, read-only A OCR collections.
"""

import argparse
import json
import traceback
from argparse import Namespace
from dataclasses import asdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from time import monotonic

from proofops.adapters.local import upstage_ocr_profile_v11 as native
from proofops.adapters.local.claim_source_verification import discovery_refs
from proofops.adapters.local.openai import OpenAIProbe
from proofops.adapters.parsing.parser_artifacts import iter_parser_artifacts, read_parser_json
from proofops.application.analysis_profile import FINALS_I3_POLICY, apply_pilot_profile
from proofops.application.claims import discover_atomic_claims
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import GraphBoundExtractor, UpstageClaimExtractor
from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope
from proofops_worker.extract_runner import _ContinuingExtractor, select_batch_paragraph_sources

import evaluation
from evaluation.pa9_source_gate import fixture
from scripts.finals_demo import FinalsBudget

ROOT = Path("/path/to/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"
A = LAB / "fix/A/paid-dec26"
OUT = LAB / "fix/H1"
CASES = {
    "SK하이닉스": ["SK하이닉스"],
    "현대자동차": ["현대자동차-p22", "현대자동차-p41"],
    "POSCO홀딩스": ["POSCO홀딩스"],
    "삼성전자": ["삼성전자"],
}


def read(path):
    return read_parser_json(path)


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def load_a_scorer():
    # Execute the exact accepted A evaluator, without running its CLI/writers.
    evaluation.__path__ = [*evaluation.__path__, str(ROOT / ".local/a-holdout/evaluation")]
    from evaluation.a_score import audit_sources, scorer

    return scorer(), audit_sources


def funded_probe():
    ledgers = {p: ROOT / f".local/{p}/budget.sqlite3" for p in ("openai", "upstage", "openrouter")}
    fence = FinalsBudget(
        LAB / "sprint3/E2E/r108-spend.json", ledgers, OUT / "paid-calls.jsonl", task="H1-openai"
    )
    fence.limit_usd = Decimal("1.2")
    with fence.transaction() as (_, entry):
        if Decimal(entry["delta_usd"]) == Decimal(entry["reserved_usd"]) == 0:
            entry["limit_usd"] = "1.2"
        assert Decimal(entry["limit_usd"]) == Decimal("1.2")
        entry["authorization"] = "holdout-H1.md: OpenAI USD1.2; Upstage USD0.5"
    original = OpenAIProbe._total

    def task_total(probe, db):
        original(probe, db)  # Validate every historical reservation and receipt.
        data = read(fence.spend_path)
        entry = next(e for e in data["executions"] if e.get("task") == "H1-openai")
        if Decimal(entry["limit_usd"]) != Decimal("1.2"):
            raise ValueError("H1_FUNDING_AUTHORITY_INVALID")
        return Decimal(entry["delta_usd"])

    OpenAIProbe._total = task_total
    transport = OpenAIProbe.complete

    def diagnosed(probe, *args, **kwargs):
        try:
            return transport(probe, *args, **kwargs)
        except Exception as error:
            print(
                json.dumps(
                    dict(
                        error_type=type(error).__name__,
                        frames=[
                            dict(file=f.filename, line=f.lineno)
                            for f in traceback.extract_tb(error.__traceback__)
                        ],
                    )
                ),
                flush=True,
            )
            raise

    OpenAIProbe.complete = fence.guarded(diagnosed, "openai", lambda *args: Decimal(".02"))
    keys = dict(
        line.split("=", 1)
        for line in (ROOT / ".env.openai.local").read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    return OpenAIProbe(keys["OPENAI_API_KEY"].strip(), ledgers["openai"]), fence


def measure(label, company, *, policy=FINALS_I3_POLICY, grid_bypass=False):
    out = OUT / label / company
    out.mkdir(parents=True, exist_ok=True)
    scorer, audit_sources = load_a_scorer()
    golds = read(A / "v1-gold-atoms.json")
    golds = [g for g in golds if g["company"] == company]
    probe, fence = funded_probe()
    restore = None
    if grid_bypass:
        from evaluation.a_grid_context import install

        restore = install()
    predictions, audits, stages, hashes, source_details = [], [], [], {}, {}
    options = Namespace(
        analysis_profile="finals-unattended-v2", analysis_policy_sha256=canonical_hash(policy)
    )
    apply_pilot_profile(options)
    names = (
        "source_ids",
        "assertion_prompt",
        "context",
        "table_context",
        "table_rows",
        "pb1",
        "pb1_context_guard",
        "linewrap_join",
        "fragment_guard",
        "w9",
        "j3",
        "j7",
        "j8",
        "i3_wire",
        "k1",
        "k3",
        "sentence_prefix",
        "table_footnotes",
    )
    flags = {"extraction_" + n: getattr(options, "extraction_" + n, False) for n in names}
    flags.update(position_order=False, display_text_profile="glyph-joined-display-v1")
    try:
        for case in CASES[company]:
            started = monotonic()
            state = A / "states" / case
            graph, source, retained, snapshot, parse = fixture(state)
            for p in [
                state / "state.sqlite3",
                state / "pilot.json",
                *iter_parser_artifacts(state, "candidates.json"),
            ]:
                hashes[str(p)] = sha256(p.read_bytes()).hexdigest()
            with reader_scope(ReplayOCRStore(state / "ocr-attestation.sqlite3")):
                reader = native.for_run(snapshot["run_id"])
                table = reader.attest_tables(graph, source, tenant_id=graph.tenant_id)
                graph = reader.replay_tables(table, graph, source, tenant_id=graph.tenant_id)
                native_proof = reader.attest_native_sources(
                    graph,
                    source,
                    tenant_id=graph.tenant_id,
                    geometry_mode=parse["native_paragraph_attestation"]["geometry_mode"],
                )
                graph = reader.replay_native_sources(
                    native_proof, graph, source, tenant_id=graph.tenant_id
                )
                extractor = UpstageClaimExtractor(
                    probe, out / case / "extraction-receipts", **flags
                )
                window = select_batch_paragraph_sources(
                    graph, retained.scope, 256, extraction_table_rows=True, extraction_k3=True
                )
                bound = _ContinuingExtractor(
                    GraphBoundExtractor(extractor, graph, source),
                    extractor.profile,
                    {},
                    window,
                    256,
                    extraction_table_rows=True,
                    extraction_k3=True,
                    graph=graph,
                )
                discovery = discover_atomic_claims(graph, retained.scope, extractor=bound)
                receipt = reader.attest_claim_spans(
                    graph, source, discovery_refs(discovery), tenant_id=graph.tenant_id
                )
                discovery, _ = native.replay_claim_spans(
                    receipt, graph, source, discovery, tenant_id=graph.tenant_id
                )
                write(out / case / "discovery.json", asdict(discovery))
                write(out / case / "attestation.json", receipt)
                write(out / case / "native-attestation.json", native_proof)
                write(out / case / "table-attestation.json", table)
                pp = [
                    dict(
                        id=c.claim_id,
                        company=company,
                        page=c.source_refs[0].page_num,
                        quote=c.quote,
                        source_verified=c.source_quality == "verified",
                        raw=asdict(c),
                    )
                    for c in discovery.claims
                ]
                predictions.extend(pp)
                audits.extend(
                    audit_sources(pp, graph, snapshot["document"]["source_path"])
                    if "source_path" in snapshot["document"]
                    else audit_sources(pp, graph, read(state / "pilot.json")["source_path"])
                )
                source_details[case] = dict(
                    graph_sha256=canonical_hash(asdict(graph)),
                    source_sha256=sha256(source).hexdigest(),
                )
                stages.append(
                    dict(
                        case=case,
                        claims=len(pp),
                        eligible_sources=len(window),
                        failed_sources=sum(r.status == "failed" for r in discovery.receipts),
                        stop_code=bound.stop_code,
                        seconds=round(monotonic() - started, 3),
                    )
                )
                print(json.dumps(stages[-1], ensure_ascii=False), flush=True)
        assert all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
        result = dict(
            company=company,
            policy=policy,
            policy_sha256=canonical_hash(policy),
            extraction_profile=asdict(extractor.profile),
            source_policy=native.claim_source_policy(),
            strict=scorer.evaluate(golds, predictions),
            stages=stages,
            native_mismatches=sum(a["native_audit_mismatch"] for a in audits),
            uncheckable=sum(a["uncheckable"] for a in audits),
            input_hashes=hashes,
            source_details=source_details,
            upstage_calls=0,
            parsing="retained A candidates",
            grid_bypass=grid_bypass,
            tagging="not_run; extraction/source task only",
        )
        write(out / "predictions.json", predictions)
        write(out / "source-audit.json", audits)
        write(out / "measurement.json", result)
        print(
            json.dumps(
                {
                    k: result["strict"][k]
                    for k in (
                        "matches",
                        "predictions",
                        "recall",
                        "precision",
                        "verified_predictions",
                    )
                }
            ),
            flush=True,
        )
    finally:
        if restore:
            restore()
        with fence.transaction() as (_, entry):
            write(
                OUT / "cost.json",
                dict(
                    openai_usd=entry["delta_usd"],
                    openai_limit="1.2",
                    reserved_usd=entry["reserved_usd"],
                    upstage_usd="0",
                    upstage_limit="0.5",
                ),
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", required=True)
    parser.add_argument("--company", required=True, choices=CASES)
    parser.add_argument("--grid-bypass", action="store_true")
    args = parser.parse_args()
    measure(args.label, args.company, grid_bypass=args.grid_bypass)
