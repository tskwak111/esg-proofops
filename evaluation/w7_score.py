"""Finalize W7: exact DL3 functions, final-policy equivalence and native bbox audit."""

import argparse
import ast
import json
import re
import tempfile
import unicodedata
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pdfplumber
from proofops.application.ingest.sentence_prefix import POLICY, expand_sentence_prefixes
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.pa9_source_gate import fixture
from evaluation.w7_sentence_replay import NoTransport, read, write


def compact(text):
    return "".join(unicodedata.normalize("NFC", text).split())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root
    lab = root / "outputs/agent-results/R108-redesign/lab"
    out = lab / "perf/W7"
    sources = dict(
        lgchem=root / ".local/w7-inputs/lgchem-server",
        naver=lab / "perf/PA9/naver-server",
        kia=lab / "perf/PA9/kia-server",
    )
    gold_path = next((lab / "gold-return/20261010/raw").rglob("20261007*.json"))
    gold = read(gold_path)
    namespace = dict(re=re, unicodedata=unicodedata)
    matcher_hashes = {}
    for name, functions in (
        ("dl1_score.py", {"norm"}),
        ("dl2_score.py", {"clean", "literal_edge", "bipartite", "evaluate"}),
    ):
        path = root / ".local/docling-lab/scripts" / name
        nodes = [
            n
            for n in ast.parse(path.read_text()).body
            if isinstance(n, ast.FunctionDef) and n.name in functions
        ]
        assert len(nodes) == len(functions)
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), "exec"), namespace)
        matcher_hashes[name] = sha256(path.read_bytes()).hexdigest()
    identities = read(lab / "perf/QM1/source-identity.json")["pdfs"]
    sample = read(lab / "perf/QM1/source-verification-evidence.json")
    summary, audits, sample_audit = {}, [], []
    for name, state in sources.items():
        graph, _, _, snapshot, _ = fixture(state)
        blocks = {b.source_id: b for b in graph.blocks}
        settings = read(state / "settings.json")
        flags = {
            k: v for k, v in settings.items() if k.startswith("extraction_") and type(v) is bool
        }
        flags.update(
            position_order="position_context_order" in settings,
            display_text_profile=settings.get("display_text_policy", {}).get("profile"),
        )
        changes = {c["source_id"]: c for c in read(out / name / "changes.json")}
        final_diagnostics = {}
        after_missing = 0
        with tempfile.TemporaryDirectory() as tmp:
            extractor = UpstageClaimExtractor(
                NoTransport(), tmp, **flags, extraction_sentence_prefix=True
            )
            for p in (state / "extraction-receipts").glob("*/packet.json"):
                packet = read(p)
                if packet["parse_manifest_id"] != graph.parse_manifest_id:
                    continue
                data = packet["untrusted_document_data"]
                if data["source_id"] not in changes:
                    continue
                spans, diagnostics = extractor._resolve_payload(
                    json.loads(read(p.parent / "raw_response.json")["content"]),
                    data["text"],
                    data["source_id"],
                    packet=packet,
                    context_graph=graph,
                )
                actual = [asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in spans]
                # Same quote/offsets means all the already recomputed source
                # attestations remain applicable. Do not rerun unchanged OCR.
                assert actual == changes[data["source_id"]]["after"], "W7_FINAL_SELECTION_CHANGED"
                stable, remaining = expand_sentence_prefixes(
                    actual, data["text"], kind=data["kind"]
                )
                assert stable == actual, "W7_FINAL_PREFIX_NOT_STABLE"
                after_missing += sum(r["status"] == "expanded" for r in remaining)
                final_diagnostics[data["source_id"]] = diagnostics
            final_profile = asdict(extractor.profile)
        assert set(final_diagnostics) == set(changes)
        page_map = read(
            lab
            / (
                "perf/RS4/lgchem-t4g-pa7.result.json"
                if name == "lgchem"
                else f"perf/PB5/{name}-result.json"
            )
        )["page_map"]
        before, after = (
            read(out / name / (stage + "-claims.json")) for stage in ("before", "after")
        )
        before_keys = {
            (
                c["source_refs"][0]["source_id"],
                c["source_refs"][0]["char_start"],
                c["source_refs"][0]["char_end"],
            )
            for c in before
        }
        altered = [
            c
            for c in after
            if (
                c["source_refs"][0]["source_id"],
                c["source_refs"][0]["char_start"],
                c["source_refs"][0]["char_end"],
            )
            not in before_keys
        ]
        source = identities[name]
        pdf = Path(source["path"])
        assert sha256(pdf.read_bytes()).hexdigest() == source["sha256"]
        with pdfplumber.open(pdf) as native:
            for c in altered:
                ref = c["source_refs"][0]
                physical = page_map[ref["page_num"] - 1]
                cropped = native.pages[physical - 1].crop(tuple(ref["bbox"]))
                chars = "".join(ch["text"] for ch in cropped.chars)
                layout = cropped.extract_text(x_tolerance=2, y_tolerance=3) or ""
                literal = compact(c["quote"]) in compact(chars) or compact(c["quote"]) in compact(
                    layout
                )
                assert (
                    c["quote"]
                    == blocks[ref["source_id"]].normalized_text[ref["char_start"] : ref["char_end"]]
                )
                assert (
                    ref["raw_text_sha256"]
                    == sha256(blocks[ref["source_id"]].raw_text.encode()).hexdigest()
                )
                audits.append(
                    dict(
                        company=name,
                        page=physical,
                        claim_id=c["claim_id"],
                        quote=c["quote"],
                        bbox=ref["bbox"],
                        literal_at_bbox=literal,
                        source_verified=c["source_quality"] == "verified",
                    )
                )
                assert literal, "W7_NATIVE_BBOX_AUDIT_FAILED"
        clipped_before = sum(
            any(s["char_start"] == r["selected_start"] for s in changes[sid]["before"])
            for sid, d in final_diagnostics.items()
            for r in d["sentence_prefix"]
            if r["status"] == "expanded"
        )
        gg = [
            g
            for g in gold["sheets"]["1_전수목록"]
            if g["기업"] == name and g["비주장 여부"] == "주장"
        ]
        scores = {}
        for stage, records in (("before", before), ("after", after)):
            preds = [
                dict(
                    id=c["claim_id"],
                    quote=c["quote"],
                    page=page_map[c["source_refs"][0]["page_num"] - 1],
                )
                for c in records
            ]
            scores[stage] = (
                namespace["evaluate"](gg, preds)
                if gg
                else dict(
                    status="not_run",
                    reason="no LG gold in existing DL3 set",
                    gold_denominator=0,
                    strict_text_recall=None,
                    strict_text_precision=None,
                )
            )
        if name == "lgchem":
            for s in sample["records"]:
                if not s.get("sentence_prefix_clipped"):
                    continue
                matches = [
                    c
                    for c in after
                    if c["source_refs"][0]["source_id"] == s["source_ref"]["source_id"]
                    and c["quote"].endswith(s["quote"])
                ]
                assert len(matches) == 1
                assert compact(s["clipping_detail"]["missing_sentence_prefix"]) in compact(
                    matches[0]["quote"][: -len(s["quote"])]
                )
                sample_audit.append(
                    dict(
                        sample=s["sample"],
                        before_quote=s["quote"],
                        after_quote=matches[0]["quote"],
                        repaired=True,
                        source_verified=matches[0]["source_quality"] == "verified",
                    )
                )
        paragraph_count = sum(
            blocks[c["source_refs"][0]["source_id"]].kind == "paragraph" for c in before
        )
        summary[name] = dict(
            source=source,
            final_profile=final_profile,
            final_policy=POLICY,
            final_policy_sha256=canonical_hash(POLICY),
            final_selection_matches_attested_offsets=True,
            claim_counts=dict(before=len(before), after=len(after)),
            source_verified=dict(
                before=sum(c["source_quality"] == "verified" for c in before),
                after=sum(c["source_quality"] == "verified" for c in after),
            ),
            prefix_missing=dict(
                before=clipped_before,
                after=after_missing,
                denominator=paragraph_count,
                after_denominator=sum(
                    blocks[c["source_refs"][0]["source_id"]].kind == "paragraph" for c in after
                ),
                criterion="deterministically recoverable same-source prose prefixes; "
                "intentional independent clauses/headings excluded",
            ),
            changed_quotes=len(altered),
            scores=scores,
            retained_raw_replay=len(final_diagnostics),
            run_id=snapshot["run_id"],
        )
    assert len(sample_audit) == 7
    write(
        out / "source-audit.json",
        dict(
            method=(
                "independent original-PDF native chars/layout within exact bbox; "
                "NFC/whitespace only"
            ),
            records=audits,
            source_errors=sum(not a["literal_at_bbox"] for a in audits),
            verified_error_count=sum(
                a["source_verified"] and not a["literal_at_bbox"] for a in audits
            ),
            qm1_sample=dict(
                before_missing=7,
                after_missing=0,
                paragraph_denominator=15,
                all_citation_denominator=30,
                records=sample_audit,
            ),
            limitation=(
                "Changed quotes only; no whole-corpus zero-error claim or " "semantic certification"
            ),
        ),
    )
    write(
        out / "scores.json",
        dict(
            schema="w7-dl3-replay-v1",
            gold_sha256=sha256(gold_path.read_bytes()).hexdigest(),
            gold_status="draft AI + independent AI/domain sampled; not human R2",
            scorer_sha256=matcher_hashes,
            companies=summary,
            provider_calls=0,
            paid_usd="0",
            limitations=[
                "Strict textual proxy, not semantic/model accuracy",
                "LG gold absent",
                "New tagging and grades not_run; HX1 model-call regression outside W7",
            ],
        ),
    )
    print(
        json.dumps(
            {
                n: {
                    k: v
                    for k, v in s.items()
                    if k in ("claim_counts", "source_verified", "prefix_missing", "changed_quotes")
                }
                for n, s in summary.items()
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
