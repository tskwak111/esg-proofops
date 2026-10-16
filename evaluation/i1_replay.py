"""Read-only integrated extraction replay; no transport or revision writer.

Changed table IDs are conservative candidate projections, never fresh model
votes. Prose uses retained raw responses. Exact unchanged W7 source attestations
are reused as measurement evidence; all table spans get fresh native cell proof.
"""

import argparse
import io
import json
import socket
from dataclasses import asdict, replace
from hashlib import sha256
from pathlib import Path
from time import monotonic

import pdfplumber
from proofops.adapters.local import upstage_ocr_profile_v10 as native
from proofops.application.analysis_profile import FINALS_I1_POLICY
from proofops.application.ingest.pb1_tables import observations as legacy_observations
from proofops.application.ingest.sentence_prefix import expand_sentence_prefixes
from proofops.application.ingest.w9_tables import PROFILE, observations_for
from proofops.application.tagging.dec24 import adjacent_table, table_footnote
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.d24_replay import load_scorer
from evaluation.pa9_source_gate import fixture
from evaluation.w7_sentence_replay import NoTransport


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def ref_key(ref):
    return ref.source_id, ref.char_start, ref.char_end, ref.quote, ref.raw_text_sha256


def main(*, integration_policy=FINALS_I1_POLICY, baseline_dir=None, retained_prose_only=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = monotonic()

    def deny(*a, **kw):
        raise AssertionError("I1_REPLAY_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    root, lab = args.root, args.root / "outputs/agent-results/R108-redesign/lab"
    j3 = bool(integration_policy.get("selected_span_refinement"))
    j7 = integration_policy.get("selected_span_refinement") == "j7-independent-clauses-v1"
    j8 = integration_policy.get("table_cells") == "j8-owned-cell-candidates-v1"
    k3 = bool(integration_policy.get("table_worker_routing"))
    k6 = bool(integration_policy.get("coverage_policy"))
    cell_selections = []
    selection_inputs = {}
    if j8:
        from evaluation.j8_cells_replay import selection_receipt

        for folder, filename, profile_key in (
            ("fix/J3", "live-cells.json", "extraction_profile"),
            ("fix/J8", "live-cells.json", "profile"),
        ):
            path = lab / folder / filename
            saved = read(path)
            selection_inputs[str(path)] = sha256(path.read_bytes()).hexdigest()
            for case in saved["cases"]:
                selection_receipt(
                    path.parent / "live-receipts", case, saved[profile_key], selection_inputs
                )
                cell_selections.append(case)
    baseline = read(lab / baseline_dir / "measurement.json") if baseline_dir else None
    score, scorer_hashes = load_scorer(root / ".local/docling-lab/scripts")
    gold_path = next((lab / "gold-return/20261010/raw").rglob("20261007*.json"))
    gold = read(gold_path)
    states = dict(
        lgchem=root / ".local/w7-inputs/lgchem-server",
        naver=lab / "perf/PA9/naver-server",
        kia=lab / "perf/PA9/kia-server",
    )
    summary, input_hashes, all_rows = {}, {}, {}
    if j8:
        input_hashes.update(selection_inputs)
    for name, state in states.items():
        phase = monotonic()
        graph, source, retained, snapshot, _ = fixture(state)
        settings = read(state / "settings.json")
        page_map = read(state / "result-1.json")["page_map"]
        blocks = {b.source_id: b for b in graph.blocks}
        # The experimental table profile changes context metadata only. Original
        # canonical IDs, cells, literal offsets and source bytes stay unchanged.
        new_graph = replace(
            graph,
            candidates=tuple(
                replace(
                    batch,
                    blocks=tuple(replace(c, context=(*c.context, PROFILE)) for c in batch.blocks),
                )
                for batch in graph.candidates
            ),
            blocks=tuple(
                replace(
                    b,
                    candidates=tuple(
                        replace(c, context=(*c.context, PROFILE)) for c in b.candidates
                    ),
                )
                for b in graph.blocks
            ),
        )
        new_blocks = {b.source_id: b for b in new_graph.blocks}
        if integration_policy.get("selected_boundary_recovery"):
            from proofops.adapters.local.h1_native_title import NativeTitleCatalog

            titles = NativeTitleCatalog(new_graph, source)
        flags = {
            k: v for k, v in settings.items() if k.startswith("extraction_") and type(v) is bool
        }
        flags.update(
            position_order="position_context_order" in settings,
            display_text_profile=settings.get("display_text_policy", {}).get("profile"),
        )
        old = UpstageClaimExtractor(NoTransport(), args.output / name / "old", **flags)
        new = UpstageClaimExtractor(
            NoTransport(),
            args.output / name / "new",
            **flags,
            extraction_w9=True,
            extraction_sentence_prefix=True,
            extraction_table_footnotes=True,
            extraction_j3=j3,
            extraction_j7=j7,
            extraction_j8=j8,
            extraction_i3_wire=bool(integration_policy.get("extraction_wire")),
            extraction_located_table_context=bool(integration_policy.get("located_table_context")),
            extraction_k1=bool(integration_policy.get("extraction_k1")),
            extraction_k3=k3,
            extraction_h1=bool(integration_policy.get("selected_boundary_recovery")),
            extraction_i5_tables=bool(integration_policy.get("table_failure_profile")),
            extraction_k6=k6,
            extraction_q1=bool(integration_policy.get("activity_table_policy")),
        )
        # The original byte-identical extractor options reproduce the retained
        # selection. Origin/main has these same policies; its hash is recorded.
        assert asdict(old.profile) == snapshot["extraction_profile"]
        proofs = {}
        for stage in ("before", "after"):
            path = lab / f"perf/W7/{name}/{stage}-attestation.json"
            receipt = read(path)
            assert (
                canonical_hash({k: v for k, v in receipt.items() if k != "artifact_sha256"})
                == (receipt["artifact_sha256"])
            )
            assert receipt["source_sha256"] == sha256(source).hexdigest()
            if not retained_prose_only:
                assert receipt["policy"] == native.claim_source_policy()
            # Explicit offline historical measurement: hashes/source identity
            # above still hold; native bbox literals below independently check
            # retained prose approvals. This never approves a runtime source or
            # claims that an unavailable current OCR runtime reproduced a proof.
            for item in receipt["records"]:
                ref = item["ref"]
                key = (
                    ref["source_id"],
                    ref["char_start"],
                    ref["char_end"],
                    ref["quote"],
                    ref["raw_text_sha256"],
                )
                proofs[key] = dict(
                    status=item["status"], artifact_sha256=receipt["artifact_sha256"]
                )
            input_hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
        raw = {}
        for path in (state / "extraction-receipts").glob("*/packet.json"):
            packet = read(path)
            response = path.parent / "raw_response.json"
            if packet["parse_manifest_id"] == graph.parse_manifest_id and response.exists():
                sid = packet["untrusted_document_data"]["source_id"]
                raw[sid] = packet, json.loads(read(response)["content"])
                input_hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
                input_hashes[str(response)] = sha256(response.read_bytes()).hexdigest()
        before, after, projected, failures, exclusions = [], [], [], [], []
        for receipt in retained.receipts:
            sid = receipt.source_id
            if receipt.status == "failed":
                failures.append(sid)
                continue
            block, current = blocks[sid], new_blocks[sid]
            packet = dict(
                tenant_id=graph.tenant_id,
                document_version_id=graph.document_version_id,
                parse_manifest_id=graph.parse_manifest_id,
                source_sha256=graph.source_sha256,
                untrusted_document_data=dict(
                    source_id=sid,
                    page_num=block.page_num,
                    kind=block.kind,
                    text=block.normalized_text,
                ),
            )
            previous = json.loads(receipt.raw_response_json)["spans"]
            before.extend((block, span) for span in previous if span["kind"] == "claim")
            if sid in raw and block.kind == "paragraph":
                saved_packet, payload = raw[sid]
                assert saved_packet["untrusted_document_data"] == packet["untrusted_document_data"]
                recovered, _ = old._resolve_payload(
                    payload, block.normalized_text, sid, packet=saved_packet, context_graph=graph
                )
                assert [
                    asdict(s) | dict(topic_ids=list(s.topic_ids)) for s in recovered
                ] == previous
                spans, _ = new._resolve_payload(
                    payload,
                    block.normalized_text,
                    sid,
                    packet=(
                        saved_packet | {"h1_native_title": titles.proof(sid)}
                        if integration_policy.get("selected_boundary_recovery")
                        else saved_packet
                    ),
                    context_graph=graph,
                )
                selected = [asdict(s) for s in spans]
            elif block.kind == "table":
                if k6:
                    from proofops.application.ingest.k6_coverage import (
                        observations_for as table_rows,
                    )
                else:
                    table_rows = observations_for
                rows = table_rows(current, new_graph)
                if rows:
                    # Exercise the combined W9/DEC-24 deterministic live path.
                    selected = new.extract(packet, context_graph=new_graph)["spans"]
                else:
                    entries = new._row_entries(
                        packet, current.normalized_text, [], context_graph=new_graph
                    )
                    extra = set()
                    if j8:
                        for case in cell_selections:
                            if (
                                case["company"] == name
                                and case["physical_page"] == page_map[current.page_num - 1]
                                and case["table_text"] == current.normalized_text
                            ):
                                extra.update(
                                    (s["char_start"], s["char_end"]) for s in case["spans"]
                                )
                    selected = [
                        dict(
                            char_start=e["char_start"],
                            char_end=e["char_end"],
                            quote=e["text"],
                            kind="claim",
                            topic_ids=["environment"],
                            reason=None,
                        )
                        for e in entries
                        if (e["char_start"], e["char_end"]) in extra
                        or any(
                            s["char_start"] < e["char_end"] and e["char_start"] < s["char_end"]
                            for s in previous
                            if s["kind"] == "claim"
                        )
                    ]
                    projected.append(sid)
                    if j8:
                        payload = dict(
                            sentence_ids=[
                                e["sentence_id"]
                                for e in entries
                                if any(
                                    s["char_start"] == e["char_start"]
                                    and s["char_end"] == e["char_end"]
                                    for s in selected
                                )
                            ]
                        )
                        if payload["sentence_ids"]:
                            resolved, _ = new._resolve_payload(
                                payload,
                                current.normalized_text,
                                sid,
                                packet=packet,
                                context_graph=new_graph,
                            )
                            selected = [asdict(s) for s in resolved]
                    elif j3:
                        from proofops.application.ingest.j3_recall import refine_selected
                        from proofops.application.ingest.w9_tables import graph_cells

                        refined, _ = refine_selected(
                            selected,
                            current.normalized_text,
                            kind=current.kind,
                            cells=graph_cells(current, new_graph),
                        )
                        try:
                            selected = [
                                asdict(s)
                                for s in new._validate_spans(
                                    {"spans": refined}, current.normalized_text
                                )
                            ]
                        except ValueError:
                            pass  # retain the complete parent on invalid refinements
            elif block.kind == "figure":
                selected = []
            else:
                selected = previous
            for span in selected:
                if span["kind"] != "claim":
                    continue
                if table_footnote(
                    span["quote"], kind=block.kind, table_context=adjacent_table(packet, graph)
                ):
                    exclusions.append(dict(source_id=sid, quote=span["quote"]))
                else:
                    after.append((current, span))
        if baseline_dir:
            path = lab / baseline_dir / f"{name}-after.json"
            input_hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
            before = []
            for row in read(path):
                ref = row["source_ref"]
                block = blocks[ref["source_id"]]
                assert (
                    block.source_ref(
                        normalized_char_start=ref["char_start"],
                        normalized_char_end=ref["char_end"],
                    ).quote
                    == row["quote"]
                )
                before.append(
                    (
                        block,
                        dict(
                            char_start=ref["char_start"],
                            char_end=ref["char_end"],
                            quote=row["quote"],
                            kind="claim",
                        ),
                    )
                )
            old_keys = {
                ref_key(
                    b.source_ref(
                        normalized_char_start=s["char_start"], normalized_char_end=s["char_end"]
                    )
                )
                for b, s in before
            }
            changed_refs = [
                b.source_ref(
                    normalized_char_start=s["char_start"], normalized_char_end=s["char_end"]
                )
                for b, s in after
                if b.kind == "paragraph"
            ]
            changed_refs = [r for r in changed_refs if ref_key(r) not in old_keys]
            if changed_refs:
                from proofops.adapters.local.claim_source_verification import attest_claim_spans

                if k3:
                    from proofops.adapters.local import upstage_ocr_profile_v11
                    from proofops_api.hosted_ocr import ReplayOCRStore, reader_scope

                    ocr = state / "upstage.sqlite3"
                    input_hashes[str(ocr)] = sha256(ocr.read_bytes()).hexdigest()
                    with reader_scope(ReplayOCRStore(ocr)):
                        changed_reader = upstage_ocr_profile_v11
                        if (
                            integration_policy.get("extraction_candidate_profile")
                            == "extraction-atomic-v3"
                        ):
                            from proofops.adapters.local import upstage_ocr_profile_v21

                            changed_reader = upstage_ocr_profile_v21
                        receipt = changed_reader.attest_claim_spans(
                            new_graph,
                            source,
                            changed_refs,
                            tenant_id=graph.tenant_id,
                            run_id=snapshot["run_id"],
                        )
                else:
                    receipt = attest_claim_spans(
                        new_graph, source, changed_refs, tenant_id=graph.tenant_id
                    )
                write(args.output / f"{name}-changed-paragraph-attestation.json", receipt)
                for item in receipt["records"]:
                    ref = item["ref"]
                    key = (
                        ref["source_id"],
                        ref["char_start"],
                        ref["char_end"],
                        ref["quote"],
                        ref["raw_text_sha256"],
                    )
                    proofs[key] = dict(item, artifact_sha256=receipt["artifact_sha256"])
        if baseline_dir:
            prior = lab / baseline_dir / f"{name}-changed-paragraph-attestation.json"
            # Integrated replays may inherit unchanged proofs from an earlier
            # baseline. Follow only the exact receipt hashes in its manifest.
            priors = [prior] if prior.is_file() else []
            for path, digest in baseline["input_sha256"].items():
                candidate = Path(path)
                if candidate.name == prior.name and candidate not in priors:
                    assert sha256(candidate.read_bytes()).hexdigest() == digest
                    priors.append(candidate)
            for prior in priors:
                receipt = read(prior)
                input_hashes[str(prior)] = sha256(prior.read_bytes()).hexdigest()
                assert (
                    canonical_hash({k: v for k, v in receipt.items() if k != "artifact_sha256"})
                    == receipt["artifact_sha256"]
                )
                assert receipt["source_sha256"] == sha256(source).hexdigest()
                for item in receipt["records"]:
                    ref = item["ref"]
                    block = blocks[ref["source_id"]]
                    assert (
                        block.source_ref(
                            normalized_char_start=ref["char_start"],
                            normalized_char_end=ref["char_end"],
                        ).quote
                        == ref["quote"]
                    )
                    proofs[
                        (
                            ref["source_id"],
                            ref["char_start"],
                            ref["char_end"],
                            ref["quote"],
                            ref["raw_text_sha256"],
                        )
                    ] = dict(item, artifact_sha256=receipt["artifact_sha256"])
        outputs = {}
        native_pdf = pdfplumber.open(io.BytesIO(source))
        for stage, selections in (("before", before), ("after", after)):
            prefix_missing = {}
            for sid in {block.source_id for block, _ in selections}:
                selected = [span for block, span in selections if block.source_id == sid]
                block = blocks[sid]
                prefix_missing[sid] = {
                    detail["selected_start"]
                    for detail in expand_sentence_prefixes(
                        selected, block.normalized_text, kind=block.kind
                    )[1]
                    if detail["status"] == "expanded"
                }
            refs = [
                b.source_ref(
                    normalized_char_start=s["char_start"], normalized_char_end=s["char_end"]
                )
                for b, s in selections
            ]
            table_indices = [
                i for i, (b, _) in enumerate(selections) if b.kind in {"table", "table_cell"}
            ]
            table_reader = native
            if k3 and (
                stage == "after"
                or bool(baseline and baseline["integration_policy"].get("table_worker_routing"))
            ):
                from proofops.adapters.local import upstage_ocr_profile_v11

                table_reader = upstage_ocr_profile_v11
            cell_proofs = (
                table_reader.cell_proof(
                    graph if stage == "before" else new_graph,
                    source,
                    [refs[i] for i in table_indices],
                    tenant_id=graph.tenant_id,
                )
                if table_indices
                else []
            )
            checked = dict(zip(table_indices, cell_proofs, strict=True))
            rows = []
            for index, ((block, span), ref) in enumerate(zip(selections, refs, strict=True)):
                assert ref.quote == span["quote"]
                proof = checked.get(index) or proofs.get(ref_key(ref))
                verified = bool(proof and proof["status"] == "verified")
                literal = None
                fragments = None
                if verified:
                    cropped = native_pdf.pages[ref.page_num - 1].crop(tuple(ref.bbox))
                    characters = "".join(c["text"] for c in cropped.chars)
                    layout = cropped.extract_text(x_tolerance=2, y_tolerance=3) or ""

                    def compact(text):
                        return "".join(text.split())

                    literal = compact(ref.quote) in compact(characters) or compact(
                        ref.quote
                    ) in compact(layout)
                    if not literal and block.kind == "table":
                        # Native cell proofs above establish ownership/order;
                        # PDF text serialization need not join cells identically.
                        fragments = [
                            compact(part) in compact(characters) or compact(part) in compact(layout)
                            for part in ref.quote.split("\t")
                            if part.strip()
                        ]
                rows.append(
                    dict(
                        id=str(index),
                        quote=ref.quote,
                        page=page_map[block.page_num - 1],
                        source_ref=asdict(ref),
                        source_verified=verified,
                        native_literal_at_bbox=literal,
                        native_cell_fragments=fragments,
                        source_proof=proof,
                        kind=block.kind,
                        prefix_missing=int(span["char_start"] in prefix_missing[block.source_id]),
                    )
                )
            expected = [
                g
                for g in gold["sheets"]["1_전수목록"]
                if g["기업"] == name and g["비주장 여부"] == "주장"
            ]
            measured = score(expected, rows) if expected else None
            outputs[stage] = dict(
                claims=len(rows),
                source_verified=sum(r["source_verified"] for r in rows),
                prefix_missing=sum(r["prefix_missing"] for r in rows),
                score=measured,
                native_table_proofs=cell_proofs,
                latest_year_rows=sum(
                    len(
                        legacy_observations(
                            b.normalized_text, context=" ".join(b.candidates[b.winner].context)
                        )
                        if stage == "before" and not baseline_dir
                        else observations_for(new_blocks[b.source_id], new_graph)
                    )
                    for b in blocks.values()
                    if b.kind == "table"
                    and b.winner is not None
                    and b.page_num in retained.scope.selected_pages
                ),
                false_verified=sum(
                    r["source_verified"]
                    and not r["native_literal_at_bbox"]
                    and not (r["native_cell_fragments"] and all(r["native_cell_fragments"]))
                    for r in rows
                ),
                false_verified_scope=(
                    "native bbox literals; tabular cell fragments with owned-cell proofs"
                ),
            )
            write(args.output / f"{name}-{stage}.json", rows)
            all_rows[name + "-" + stage] = rows
        native_pdf.close()
        summary[name] = dict(
            outputs=outputs,
            physical_claim_pages=[page_map[p - 1] for p in retained.scope.selected_pages],
            frozen_document_pages=page_map,
            retained_failures=failures,
            projected_table_sources=projected,
            excluded_table_notes=exclusions,
            seconds=monotonic() - phase,
        )
        for path in (state / "state.sqlite3", state / "settings.json"):
            input_hashes[str(path)] = sha256(path.read_bytes()).hexdigest()
        print(
            name,
            {
                k: {
                    f: v[f]
                    for f in ("claims", "source_verified", "prefix_missing", "latest_year_rows")
                }
                for k, v in outputs.items()
            },
            flush=True,
        )
    combined = {}
    for phase in ("before", "after"):
        values = [
            s["outputs"][phase]["score"] for s in summary.values() if s["outputs"][phase]["score"]
        ]
        matched = sum(s["one_to_one_matches"] for s in values)
        predictions = sum(s["predictions"] for s in values)
        denominator = sum(s["gold_denominator"] for s in values)
        combined[phase] = dict(
            matches=matched,
            predictions=predictions,
            gold=denominator,
            recall=matched / denominator,
            precision=matched / predictions,
        )
    regressions = [
        name
        for name, item in summary.items()
        if item["outputs"]["after"]["score"]
        and item["outputs"]["after"]["score"]["strict_text_precision"]
        < (0.95 if baseline_dir else item["outputs"]["before"]["score"]["strict_text_precision"])
    ]
    regressions += [
        name + ":false_verified"
        for name, item in summary.items()
        if item["outputs"]["after"]["false_verified"]
    ]
    unchanged = all(
        sha256(Path(p).read_bytes()).hexdigest() == digest for p, digest in input_hashes.items()
    )
    assert unchanged
    if baseline:
        assert combined["before"] == baseline["combined_score"]["after"]
        for name, item in summary.items():
            for metric in (
                "claims",
                "source_verified",
                "prefix_missing",
                "latest_year_rows",
                "false_verified",
            ):
                assert (
                    item["outputs"]["before"][metric]
                    == (baseline["summary"][name]["outputs"]["after"][metric])
                ), (name, metric)
    write(
        args.output / "measurement.json",
        dict(
            schema="i2-integrated-offline-replay-v1"
            if baseline_dir
            else "i1-integrated-offline-replay-v1",
            summary=summary,
            combined_score=combined,
            regressions=regressions,
            stage_b_allowed=not regressions,
            integration_policy=integration_policy,
            policy_sha256=canonical_hash(integration_policy),
            baseline_policy_sha256=baseline["policy_sha256"]
            if baseline
            else "3acefc784aeff5e2c922ceb4cc9d8aed06e089f28eff1980524458e9baf7f1b8",
            input_sha256=input_hashes,
            inputs_unchanged=unchanged,
            scorer_sha256=scorer_hashes,
            gold_sha256=sha256(gold_path.read_bytes()).hexdigest(),
            seconds=monotonic() - started,
            provider_calls=0,
            paid_usd="0",
            production_revisions_written=0,
            limitations=[
                "Frozen draft DL3 literal 1:1 claim proxy; LG gold absent.",
                "New table IDs use conservative overlap projections, not new model votes.",
                "Changed quotes need fresh tagging; old grades are not transferred.",
                "W3 overlap remains disabled; server timing is not measured.",
                *(
                    [
                        "Prose uses immutable historical attestations plus fresh native "
                        "bbox literals; "
                        "current OCR policy equivalence not_run."
                    ]
                    if retained_prose_only
                    else []
                ),
            ],
        ),
    )
    print(combined, "regressions", regressions, flush=True)


if __name__ == "__main__":
    main()
