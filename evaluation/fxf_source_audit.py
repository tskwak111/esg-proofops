"""Offline literal mutations, trusted-store tampering and original-pixel lineage."""

import argparse
import io
import json
import socket
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

from PIL import Image
from proofops.adapters.local import claim_source_fxf as verifier
from proofops.adapters.local.claim_source_verification_v4 import _exact_source_ref
from proofops.adapters.local.source_fxf import render_page
from proofops.application.ingest.graph_fusion import fuse_candidates
from proofops.domain.provenance import canonical_hash
from proofops.domain.values import SourceRef

from evaluation.fxe_source_replay import load_fixture
from evaluation.fxf_source_replay import SavedStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("input", "fxe_receipt", "ledger", "original", "page_map", "output"):
        parser.add_argument("--" + name.replace("_", "-"), type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    def deny(*args, **kwargs):
        raise AssertionError("FXF_NETWORK_FORBIDDEN")

    socket.socket.connect = socket.socket.connect_ex = socket.create_connection = deny
    graph, source, discovery, old = load_fixture(args.input)
    baseline = json.loads(args.fxe_receipt.read_bytes())
    refs = tuple(SourceRef(**r["ref"]) for r in baseline["records"] if r["status"] != "verified")
    store = SavedStore(args.ledger)
    receipt = verifier.attest_claim_spans(
        graph, source, refs, tenant_id=graph.tenant_id, run_id=old["run_id"], store=store
    )
    (args.output / "prose-receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2)
    )
    gained = [r for r in receipt["records"] if r["status"] == "verified"]
    print("recovery", Counter(r["status"] for r in receipt["records"]), flush=True)
    original = args.original.read_bytes()
    assert (
        sha256(original).hexdigest()
        == "9ae1cfcf07c923c1c2529f66e1215b42b380e62c600a4bc02ebcc41a223ff8fc"
    )
    pages = json.loads(args.page_map.read_bytes())["page_map"]
    blocks = {b.source_id: b for b in graph.blocks}
    images = {}
    checks = []
    for index, record in enumerate(gained, 1):
        ref = SourceRef(**record["ref"])
        if ref.page_num not in images:
            selected = render_page(source, ref.page_num)
            full = render_page(original, pages[ref.page_num - 1])
            assert selected["png"] == full["png"]
            saved = next(p for p in receipt["page_reads"] if p["physical_page"] == ref.page_num)
            assert selected["manifest"] == saved["manifest"]
            images[ref.page_num] = selected
        image = images[ref.page_num]
        glyphs = record["normalization"]["glyphs"]
        box = [
            min(g["bbox"][0] for g in glyphs),
            min(g["bbox"][1] for g in glyphs),
            max(g["bbox"][2] for g in glyphs),
            max(g["bbox"][3] for g in glyphs),
        ]
        filename = f"gained-{index:02}-p{pages[ref.page_num-1]}.png"
        m = image["manifest"]
        sx, sy = m["pixel_size"][0] / m["width_pt"], m["pixel_size"][1] / m["height_pt"]
        with Image.open(io.BytesIO(image["png"])) as bitmap:
            bitmap.crop(
                (
                    int(box[0] * sx) - 6,
                    int(box[1] * sy) - 6,
                    int(box[2] * sx) + 7,
                    int(box[3] * sy) + 7,
                )
            ).save(args.output / filename)
        candidate = blocks[ref.source_id].candidates[blocks[ref.source_id].winner]
        raw = candidate.source.raw_text
        offset = next((i for i in range(ref.char_start, ref.char_end) if raw[i].isdigit()), None)
        if offset is None:
            offset = next(i for i in range(ref.char_start, ref.char_end) if raw[i].isalpha())
        char = str((int(raw[offset]) + 1) % 10) if raw[offset].isdigit() else "X"
        changed = raw[:offset] + char + raw[offset + 1 :]
        forged = replace(candidate, source=replace(candidate.source, raw_text=changed))
        batch = next(b for b in graph.candidates if candidate in b.blocks)
        mutated = fuse_candidates(
            (replace(batch, blocks=(forged,), edges=()),),
            tenant_id=graph.tenant_id,
            mixed_parser=True,
        )
        block = mutated.blocks[0]
        forged_ref = replace(
            ref,
            source_id=block.source_id,
            raw_text_sha256=sha256(changed.encode()).hexdigest(),
            quote=changed[ref.char_start : ref.char_end],
        )
        assert _exact_source_ref(mutated, block, forged_ref, graph.tenant_id)
        rejected = verifier.attest_claim_spans(
            mutated,
            source,
            (forged_ref,),
            tenant_id=graph.tenant_id,
            run_id=old["run_id"],
            store=store,
        )["records"][0]
        assert rejected["status"] != "verified"
        checks.append(
            dict(
                ref=record["ref"],
                original_page=pages[ref.page_num - 1],
                crop=filename,
                png_sha256=m["png_sha256"],
                literal_mutation=forged_ref.quote,
                mutation_status=rejected["status"],
                mutation_reason=rejected["reason"],
            )
        )
    # Even fully rehashed OCR text is not trusted without the original ledger row.
    page = receipt["page_reads"][0]
    image = images[page["physical_page"]]
    collection = deepcopy(page["collection"])
    data = json.loads(bytes.fromhex(collection["response_hex"]))
    data["pages"][0]["words"][0]["text"] = "FORGED"
    raw = json.dumps(data).encode()
    collection["response_hex"] = raw.hex()
    collection["response_sha256"] = sha256(raw).hexdigest()
    from proofops.adapters.local.upstage_ocr_page import parse_response

    collection["derived_sha256"] = canonical_hash(parse_response(raw))
    collection["artifact_sha256"] = canonical_hash(
        {k: v for k, v in collection.items() if k != "artifact_sha256"}
    )
    try:
        store.validate(collection, image, tenant_id=graph.tenant_id)
    except ValueError as exc:
        assert str(exc) == "OCR_COLLECTION_UNTRUSTED"
    else:
        raise AssertionError("forged OCR admitted")
    result = dict(
        recovered_refs=len(gained),
        literal_mutations_rejected=len(checks),
        false_verified_mutations=0,
        rehashed_ocr_forgery_rejected=True,
        all_original_selected_page_pixels_identical=True,
        original_source_sha256=sha256(original).hexdigest(),
        checks=checks,
        network="denied",
        paid_calls=0,
    )
    (args.output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print({k: v for k, v in result.items() if k != "checks"}, flush=True)


if __name__ == "__main__":
    main()
