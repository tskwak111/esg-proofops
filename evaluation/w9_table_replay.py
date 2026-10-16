"""Read-only CR2/PB1 retained-response replay, including Linux native source gates.

New generic cell IDs cannot reuse old model choices as new model votes. Their
matching cell candidates are a projection for source/scorer checks only. No
classification, element state or grade is synthesized here.
"""

import argparse
import json
import socket
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from time import monotonic
from uuid import UUID, uuid5

from proofops.adapters.local import upstage_ocr_profile_v10 as native
from proofops.application.ingest.graph_fusion import candidates_from_snapshot, fuse_candidates
from proofops.application.ingest.pb1_tables import observations as old_observations
from proofops.application.ingest.w9_tables import POLICY, PROFILE, observations_for
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef
from proofops_agent.upstage_extraction import UpstageClaimExtractor


def restored(raw, *, w9=False):
    batches = candidates_from_snapshot(raw["candidates"])
    if w9:
        manifest = str(uuid5(UUID(raw["parse_manifest_id"]), canonical_hash(POLICY)))
        batches = tuple(
            replace(
                b,
                parse_manifest_id=manifest,
                blocks=tuple(
                    replace(
                        c,
                        source=replace(c.source, parse_manifest_id=manifest),
                        context=(*c.context, PROFILE),
                    )
                    for c in b.blocks
                ),
            )
            for b in batches
        )
    return fuse_candidates(batches, tenant_id=raw["tenant_id"], fusion_version=5, mixed_parser=True)


def source_for(lab, name, digest):
    base = lab / ("perf/PA7/server" if name == "lgchem" else f"perf/PA9/{name}-server")
    paths = [
        p
        for p in (base / "objects/original").rglob("*.pdf")
        if sha256(p.read_bytes()).hexdigest() == digest
    ]
    assert len(paths) == 1, ("source_hash_unresolved", name, digest)
    return paths[0].read_bytes()


def packet(graph, table):
    return dict(
        tenant_id=graph.tenant_id,
        document_version_id=graph.document_version_id,
        parse_manifest_id=graph.parse_manifest_id,
        source_sha256=graph.source_sha256,
        untrusted_document_data=dict(
            source_id=table.source_id,
            page_num=table.page_num,
            kind=table.kind,
            text=table.normalized_text,
        ),
    )


class OfflineProbe:
    model = "solar-pro3"

    def complete(self, *args, **kwargs):
        raise AssertionError("W9_PROVIDER_CALL_FORBIDDEN")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    lab = args.lab.resolve()
    root = lab.parents[3]
    casefile = lab / "review/CR2/table-cases.json"
    original = casefile.read_bytes()
    review = json.loads(original)
    start = monotonic()

    def deny(*a, **kw):
        raise AssertionError("W9_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    cache, results, input_hashes = {}, [], {str(casefile): sha256(original).hexdigest()}
    extractor = UpstageClaimExtractor(
        OfflineProbe(),
        args.output / "receipts",
        extraction_source_ids=True,
        extraction_context=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_pb1_context_guard=True,
        extraction_w9=True,
    )
    for case in review["cases"] + review["chart_cases"]:
        name = case["company"]
        if name not in cache:
            path = root / case["graph_path"]
            raw_bytes = path.read_bytes()
            raw = json.loads(raw_bytes)
            before, after = restored(raw), restored(raw, w9=True)
            source = source_for(lab, name, raw["source_sha256"])
            cache[name] = before, after, source
            input_hashes[str(path)] = sha256(raw_bytes).hexdigest()
        before, after, source = cache[name]
        table = next(b for b in before.blocks if b.source_id == case["source_id"])
        origin = table.candidates[table.winner].source
        new_table = next(
            b
            for b in after.blocks
            if b.kind == table.kind
            and b.winner is not None
            and b.candidates[b.winner].source.source_native_id == origin.source_native_id
            and b.candidates[b.winner].source.parser_run_id == origin.parser_run_id
        )
        assert new_table.raw_text == table.raw_text == case["parser_source"]["raw_text"]
        pb1_before = old_observations(
            table.normalized_text, context=" ".join(table.candidates[table.winner].context)
        )
        assert len(pb1_before) == len(case["pb1_observations"])
        old_refs = [
            replace(SourceRef(**c["source_refs"][0]), verification_state="candidate")
            for c in case["stored_v10_claims"]
        ]
        old_proofs = native.cell_proof(before, source, old_refs, tenant_id=before.tenant_id)
        candidates, rows = [], []
        if table.kind == "table":
            rows = observations_for(new_table, after)
            if rows:
                extracted = extractor.extract(packet(after, new_table), context_graph=after)
                assert [s["quote"] for s in extracted["spans"]] == [r["quote"] for r in rows]
                candidates = [
                    dict(char_start=r["start"], char_end=r["end"], text=r["quote"]) for r in rows
                ]
            else:
                entries = extractor._row_entries(
                    packet(after, new_table), new_table.normalized_text, [], context_graph=after
                )
                # Keep old selected areas for a conservative offline projection.
                candidates = [
                    e
                    for e in entries
                    if any(
                        e["char_start"] < r.char_end and r.char_start < e["char_end"]
                        for r in old_refs
                    )
                ]
        else:
            assert extractor.extract(packet(after, new_table), context_graph=after) == {"spans": []}
        new_refs = [
            new_table.source_ref(
                normalized_char_start=e["char_start"], normalized_char_end=e["char_end"]
            )
            for e in candidates
        ]
        new_proofs = native.cell_proof(after, source, new_refs, tenant_id=after.tenant_id)
        combined = (
            sum("\t" in e["text"] for e in candidates) if case["case_id"] in {"T12", "T13"} else 0
        )
        assert combined == 0, "W9_CROSS_COLUMN_CELL_CANDIDATE"
        if case.get("visually_eligible_latest_year_numeric_rows") is not None:
            assert len(rows) == case["visually_eligible_latest_year_numeric_rows"]
        if case["case_id"] in {"T15", "T16", "T17", "T18", "C02"}:
            assert not candidates, ("W9_NEGATIVE_CASE_ADMITTED", case["case_id"])
        results.append(
            dict(
                case_id=case["case_id"],
                company=name,
                physical_page=case["physical_page"],
                prepared_page=case["prepared_page"],
                source_sha256=after.source_sha256,
                before_observations=pb1_before,
                after_observations=rows,
                before_claims=case["stored_v10_claims"],
                before_native_proofs=old_proofs,
                after_candidate_projection=candidates,
                after_native_proofs=new_proofs,
                old_unresolved_quotes=[
                    p["ref"]["quote"] for p in old_proofs if p["status"] != "verified"
                ],
                before_verified=sum(p["status"] == "verified" for p in old_proofs),
                after_verified=sum(p["status"] == "verified" for p in new_proofs),
                cross_column_combinations_after=combined,
                new_model_selection=(
                    "not_run; deterministic PB1 or old-selection-overlap candidate projection"
                ),
            )
        )
        print(
            case["case_id"],
            len(pb1_before),
            "->",
            len(rows),
            "candidates",
            len(candidates),
            "verified",
            sum(p["status"] == "verified" for p in new_proofs),
            flush=True,
        )
    for path, digest in input_hashes.items():
        assert sha256(Path(path).read_bytes()).hexdigest() == digest, "W9_INPUT_MUTATED"
    summary = dict(
        observations_before=sum(len(c["before_observations"]) for c in results),
        observations_after=sum(len(c["after_observations"]) for c in results),
        claims_before=sum(len(c["before_claims"]) for c in results),
        candidates_after=sum(len(c["after_candidate_projection"]) for c in results),
        source_verified_before=sum(c["before_verified"] for c in results),
        source_verified_after=sum(c["after_verified"] for c in results),
        source_unresolved_after=sum(
            len(c["after_native_proofs"]) - c["after_verified"] for c in results
        ),
        cross_column_combinations_after=sum(c["cross_column_combinations_after"] for c in results),
        seconds=monotonic() - start,
        paid_calls=0,
        cost_usd="0",
        network="denied",
        historical_inputs_unchanged=True,
        new_tags_and_grades="not_run",
    )
    assert summary["observations_before"] == 52 and summary["observations_after"] == 83
    (args.output / "replay.json").write_text(
        json.dumps(
            dict(
                schema="w9-cr2-retained-replay-v1",
                policy=POLICY,
                policy_sha256=canonical_hash(POLICY),
                input_hashes=input_hashes,
                cases=results,
                summary=summary,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
