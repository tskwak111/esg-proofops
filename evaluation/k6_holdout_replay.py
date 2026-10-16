"""H1 selection-preserving K6 coverage delta on four companies/seven pages."""

import importlib.util
import json
import socket
from argparse import Namespace
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

from proofops.adapters.local import upstage_ocr_profile_v11 as native
from proofops.application.analysis_profile import FINALS_K6_POLICY, apply_pilot_profile
from proofops.application.ingest.k6_coverage import observations_for, target_spans
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor
from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope

from evaluation.pa9_source_gate import fixture
from evaluation.w7_sentence_replay import NoTransport

ROOT = Path("/path/to/ESG_ProofOps")
LAB = ROOT / "outputs/agent-results/R108-redesign/lab"
OUT = LAB / "fix/K6"
CASES = {
    "SK하이닉스": ["SK하이닉스"],
    "현대자동차": ["현대자동차-p22", "현대자동차-p41"],
    "POSCO홀딩스": ["POSCO홀딩스"],
    "삼성전자": ["삼성전자"],
}


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main(*, policy=FINALS_K6_POLICY, output=None, baseline_root=None):
    global OUT
    OUT = output or OUT

    def deny(*args, **kwargs):
        raise AssertionError("K6_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    scorer_path = ROOT / ".local/g1-gold/evaluation/dl4_gold.py"
    scorer = module(scorer_path, "k6_g1")
    gold_path = LAB / "fix/A/paid-dec26/v1-gold-atoms.json"
    gold = read(gold_path)
    hashes = {str(p): sha256(p.read_bytes()).hexdigest() for p in (scorer_path, gold_path)}
    before, after, changes, audits = [], [], [], []
    args = Namespace(
        analysis_profile="finals-unattended-v2",
        analysis_policy_sha256=canonical_hash(policy),
    )
    apply_pilot_profile(args)
    flags = {k: v for k, v in vars(args).items() if k.startswith("extraction_") and type(v) is bool}
    # Retained v3 responses use their original source-ID namespace. This is an
    # explicit literal-selection projection, never a fresh I4 provider response.
    flags["extraction_i4_identity"] = False
    extractor = UpstageClaimExtractor(NoTransport(), OUT / "holdout-receipts", **flags)
    for company, cases in CASES.items():
        path = (baseline_root or LAB / "fix/H1/h1-final") / company / "predictions.json"
        previous = read(path)
        hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
        before.extend(previous)
        added = []
        for case in cases:
            state = LAB / "fix/A/paid-dec26/states" / case
            graph, source, discovery, snapshot, _ = fixture(state)
            refs, candidates = [], []
            for block in graph.blocks:
                if block.page_num not in discovery.scope.selected_pages:
                    continue
                if block.kind == "paragraph":
                    spans = target_spans(block.normalized_text, kind=block.kind)
                    if not spans:
                        continue
                    packet = dict(
                        tenant_id=graph.tenant_id,
                        document_version_id=graph.document_version_id,
                        parse_manifest_id=graph.parse_manifest_id,
                        source_sha256=graph.source_sha256,
                        untrusted_document_data=dict(
                            source_id=block.source_id,
                            page_num=block.page_num,
                            kind=block.kind,
                            text=block.normalized_text,
                        ),
                    )
                    resolved, diagnostics = extractor._resolve_payload(
                        {"sentence_ids": []},
                        block.normalized_text,
                        block.source_id,
                        packet=packet,
                        context_graph=graph,
                    )
                    spans = [asdict(s) for s in resolved]
                elif block.kind == "table":
                    spans = [
                        dict(char_start=r["start"], char_end=r["end"], quote=r["quote"])
                        for r in observations_for(block, graph)
                    ]
                    diagnostics = {"kind": "same-grid-latest-observation"}
                else:
                    continue
                for span in spans:
                    if any(
                        r.get("source_id") == block.source_id
                        and r["char_start"] < span["char_end"]
                        and span["char_start"] < r["char_end"]
                        for p in previous
                        for r in p["raw"]["source_refs"]
                    ):
                        continue
                    ref = block.source_ref(
                        normalized_char_start=span["char_start"],
                        normalized_char_end=span["char_end"],
                    )
                    refs.append(ref)
                    candidates.append((ref, diagnostics))
            if refs:
                with reader_scope(ReplayOCRStore(state / "ocr-attestation.sqlite3")):
                    try:
                        proof = native.for_run(snapshot["run_id"]).attest_claim_spans(
                            graph, source, refs, tenant_id=graph.tenant_id
                        )
                    except ValueError as error:
                        if str(error) != "OCR_COLLECTION_UNTRUSTED":
                            raise
                        # A new crop may have no immutable OCR collection. Never
                        # call a provider or turn that gap into verified/absent.
                        proof = dict(
                            records=[
                                dict(
                                    ref=asdict(r),
                                    status="unverified",
                                    reason="OCR_COLLECTION_UNTRUSTED",
                                )
                                for r in refs
                            ],
                            source_sha256=graph.source_sha256,
                            provider_calls=0,
                        )
                write(OUT / "holdout" / company / f"{case}-new-source-proof.json", proof)
                records = {
                    (r["ref"]["source_id"], r["ref"]["char_start"], r["ref"]["char_end"]): r
                    for r in proof["records"]
                }
                for ref, diagnostics in candidates:
                    record = records[(ref.source_id, ref.char_start, ref.char_end)]
                    pred = dict(
                        id=canonical_hash(asdict(ref)),
                        company=company,
                        page=ref.page_num,
                        quote=ref.quote,
                        source_verified=record["status"] == "verified",
                        raw=dict(source_refs=[asdict(ref)]),
                        selection_origin="k6-deterministic-literal-rescue; fresh-tags-required",
                    )
                    added.append(pred)
                    changes.append(
                        dict(
                            company=company,
                            page=ref.page_num,
                            before=None,
                            after=ref.quote,
                            source_status=record["status"],
                            diagnostics=diagnostics,
                        )
                    )
            # Source audit checks retained/new spans against the original PDF.
            import io

            import pdfplumber

            with pdfplumber.open(io.BytesIO(source)) as pdf:
                for p in [*previous, *added]:
                    for r in p["raw"]["source_refs"]:
                        if r["page_num"] not in discovery.scope.selected_pages:
                            continue
                        box = r.get("bbox")
                        if not box:
                            audits.append(
                                dict(id=p["id"], verified=p["source_verified"], uncheckable=True)
                            )
                            continue
                        crop = pdf.pages[r["page_num"] - 1].crop(tuple(box))
                        chars = "".join(c["text"] for c in crop.chars)
                        layout = crop.extract_text(x_tolerance=2, y_tolerance=5) or ""
                        literal = scorer.clean(r.get("quote", p["quote"])) in scorer.clean(
                            chars
                        ) or scorer.clean(r.get("quote", p["quote"])) in scorer.clean(layout)
                        audits.append(
                            dict(
                                id=p["id"],
                                verified=p["source_verified"],
                                native_literal=literal,
                                false_verified=p["source_verified"] and not literal,
                            )
                        )
            for filename in ("state.sqlite3", "settings.json"):
                p = state / filename
                hashes[str(p)] = sha256(p.read_bytes()).hexdigest()
        current = [*previous, *added]
        after.extend(current)
        write(OUT / "holdout" / company / "predictions.json", current)
    scores = {
        phase: scorer.evaluate(gold, pred) for phase, pred in (("before", before), ("after", after))
    }
    company_scores = {
        c: {
            phase: scorer.evaluate(
                [g for g in gold if g["company"] == c], [p for p in pred if p["company"] == c]
            )
            for phase, pred in (("before", before), ("after", after))
        }
        for c in CASES
    }
    assert scores["after"]["precision"] >= scores["before"]["precision"]
    assert scores["after"]["recall"] >= scores["before"]["recall"]
    assert all(s["after"]["precision"] >= s["before"]["precision"] for s in company_scores.values())
    assert not any(a.get("false_verified") for a in audits)
    unchanged = all(sha256(Path(p).read_bytes()).hexdigest() == h for p, h in hashes.items())
    assert unchanged

    def projection(ps):
        return Counter((p["company"], p["page"], p["quote"]) for p in ps)

    assert not projection(before) - projection(after)
    write(
        OUT / "holdout-scores.json",
        dict(
            scores=scores,
            company_scores=company_scores,
            changes=changes,
            source_audit=audits,
            input_sha256=hashes,
            inputs_unchanged=unchanged,
            normal_losses=0,
            false_verified=0,
            provider_calls=0,
            paid_usd="0",
            policy_sha256=canonical_hash(policy),
            limitation=(
                "H1 existing selections preserved; K6 coverage delta is deterministic; "
                "newly recovered claims need fresh tagging."
            ),
        ),
    )
    print(
        {
            phase: {
                k: v[k]
                for k in ("matches", "predictions", "precision", "recall", "verified_predictions")
            }
            for phase, v in scores.items()
        },
        flush=True,
    )


if __name__ == "__main__":
    main()
