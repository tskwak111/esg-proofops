"""CF4 admits only native glyphs corroborated by trusted original-region OCR."""

import io
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from PIL import Image

from tests.acceptance.test_parsing import TENANT
from tests.integration.test_claim_source_v4_visibility import TEXT, changed_pdf


def test_region_pixels_and_inverse_transform():
    import pypdfium2 as pdfium
    from proofops.adapters.local.cf4_source_region import render_region

    source, _ = changed_pdf()
    image = render_region(source, 1, (70.125, 49.25, 340.75, 91.875))
    m = image["manifest"]
    with pdfium.PdfDocument(source) as doc:
        page = doc[0]
        bitmap = page.render(scale=3, draw_annots=True)
        with bitmap.to_pil() as full, Image.open(io.BytesIO(image["png"])) as crop:
            assert (
                crop.crop(
                    (
                        6,
                        m["vertical_padding_px"],
                        crop.width - 6,
                        crop.height - m["vertical_padding_px"],
                    )
                )
                .convert("RGB")
                .tobytes()
                == full.crop(m["pixel_bbox"]).convert("RGB").tobytes()
            )
        bitmap.close()
        page.close()
    assert m["crop_to_pdf"] == [
        1 / 3,
        0,
        0,
        1 / 3,
        (m["pixel_bbox"][0] - 6) / 3,
        (m["pixel_bbox"][1] - m["vertical_padding_px"]) / 3,
    ]


class Store:
    def __init__(self, text=TEXT, confidence=0.99, shift=0):
        self.text, self.confidence, self.shift = text, confidence, shift
        self.calls = 0
        self.collections = {}

    def fetch(self, image, **kwargs):
        self.calls += 1
        w, h = image["manifest"]["pixel_size"]
        raw = json.dumps(
            dict(
                apiVersion="1.1",
                modelVersion="ocr-260930",
                numBilledPages=1,
                pages=[
                    dict(
                        id=0,
                        width=w,
                        height=h,
                        words=[
                            dict(
                                id=1,
                                text=self.text,
                                confidence=self.confidence,
                                boundingBox=dict(
                                    vertices=[
                                        dict(x=x, y=(h - 1 if self.shift and y == 0 else y))
                                        for x, y in ((0, 0), (w, 0), (w, h), (0, h))
                                    ]
                                ),
                            )
                        ],
                    )
                ],
            )
        ).encode()
        collection = dict(response_hex=raw.hex(), manifest=image["manifest"])
        self.collections[image["manifest"]["png_sha256"]] = collection
        return collection

    def validate(self, collection, image, **kwargs):
        if collection != self.collections.get(image["manifest"]["png_sha256"]):
            raise ValueError("OCR_COLLECTION_MISMATCH")
        return collection


def attestation(store, *, mutation=None):
    from proofops.adapters.local.cf4_source_region import attest_regions

    source, graph = changed_pdf(b"0 0 m 600 800 l 0 800 l h W n")
    ref = graph.blocks[0].source_ref()
    if mutation:
        ref = mutation(ref)
    return attest_regions(
        graph, source, (ref,), tenant_id=TENANT, run_id="cf4-test", store=store
    ), (source, graph, ref)


def test_exact_dual_read_replays_without_provider_and_preserves_ref():
    from proofops.adapters.local.cf4_source_region import attest_regions

    store = Store()
    result, (source, graph, ref) = attestation(store)
    assert result["records"][0]["status"] == "verified"
    assert result["records"][0]["ref"]["bbox"] == ref.bbox
    count = store.calls
    replay = attest_regions(
        graph,
        source,
        (ref,),
        tenant_id=TENANT,
        run_id="cf4-test",
        store=store,
        saved_regions=result["region_reads"],
    )
    assert replay == result and store.calls == count
    tampered = deepcopy(result["region_reads"])
    tampered[0]["collection"]["response_hex"] = b"{}".hex()
    with pytest.raises(ValueError, match="MISMATCH"):
        attest_regions(
            graph,
            source,
            (ref,),
            tenant_id=TENANT,
            run_id="cf4-test",
            store=store,
            saved_regions=tampered,
        )


@pytest.mark.parametrize(
    "store",
    [
        Store(TEXT.replace("1234", "1235")),
        Store(confidence=0.979),
        Store(shift=20),
        Store("An adjacent sentence."),
    ],
)
def test_disagreement_low_confidence_and_neighbor_never_verify(store):
    result, _ = attestation(store)
    assert result["records"][0]["status"] == "unresolved"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: replace(r, quote=r.quote + "!"),
        lambda r: replace(r, char_start=r.char_start + 1),
        lambda r: replace(r, page_num=2),
        lambda r: replace(r, bbox=(1, 1, 3, 3)),
    ],
)
def test_bad_ref_rejected_before_paid_dispatch(mutation):
    store = Store()
    result, _ = attestation(store, mutation=mutation)
    assert result["records"][0]["status"] == "unresolved"
    assert store.calls == 0


def test_opt_in_policy_leaves_default_and_historical_hashes():
    from proofops.adapters.local import cf4_claim_source as current
    from proofops.adapters.local.claim_source_policies import publication_reader
    from proofops.application import analysis_profile as profiles
    from proofops.domain.provenance import canonical_hash

    assert (
        profiles.policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.FINALS_I27_POLICY)
        )
        == profiles.FINALS_I27_POLICY
    )
    assert (
        profiles.publication_policy_for(
            profiles.V2_PROFILE, pinned_hash=canonical_hash(profiles.CF4_SOURCE_POLICY)
        )
        == profiles.CF4_SOURCE_POLICY
    )
    assert publication_reader(current.claim_source_policy()) is current
    bad = current.claim_source_policy() | {"verifier_sha256": "0" * 64}
    with pytest.raises(ValueError):
        publication_reader(bad)


def test_composition_replays_nested_baseline_and_refuses_rewritten_receipt(tmp_path, monkeypatch):
    from proofops.adapters.local import cf4_claim_source as current
    from proofops.adapters.local import claim_source_verification_v4 as v4
    from proofops.adapters.local import upstage_ocr_profile_v21 as old
    from proofops.domain.provenance import canonical_hash

    from tests.integration.test_claim_source_verification import inputs
    from tests.integration.test_upstage_ocr_page import store

    source, graph, ref = inputs()
    db = store(tmp_path)
    monkeypatch.setattr(current.PageOCRStore, "from_env", lambda: db)
    monkeypatch.setattr(old.previous, "_post_png", db.transport)
    monkeypatch.setattr(
        v4, "_render_type_proof", lambda *_: dict(status="pixel_required", reason="inventory")
    )
    reader = current.for_run("cf4-pixel")
    receipt = reader.attest_claim_spans(graph, source, (ref,), tenant_id=graph.tenant_id)
    assert receipt["records"][0]["status"] == "verified"
    assert receipt["previous_receipt"]["policy"] == current.previous.claim_source_policy()
    assert receipt["recovery_receipt"] is None
    db.transport = lambda *_: pytest.fail("cold replay must not acquire OCR")
    assert (
        reader.recompute_claim_receipt(receipt, graph, source, (ref,), tenant_id=graph.tenant_id)
        == receipt
    )
    for level in ((), ("previous_receipt",), ("previous_receipt", "previous_receipt")):
        forged = deepcopy(receipt)
        target = forged
        for name in level:
            target = target[name]
        target["records"][0]["status"] = "unresolved"
        forged["artifact_sha256"] = canonical_hash(
            {k: v for k, v in forged.items() if k != "artifact_sha256"}
        )
        with pytest.raises(ValueError):
            reader.recompute_claim_receipt(forged, graph, source, (ref,), tenant_id=graph.tenant_id)


def test_source_tenant_and_retained_region_identity_are_required():
    from proofops.adapters.local.cf4_source_region import attest_regions

    store = Store()
    receipt, (source, graph, ref) = attestation(store)
    for supplied_source, tenant in ((source + b"x", TENANT), (source, "other-tenant")):
        with pytest.raises(ValueError):
            attest_regions(
                graph, supplied_source, (ref,), tenant_id=tenant, run_id="cf4-test", store=store
            )
    for saved in ([], receipt["region_reads"] * 2):
        with pytest.raises(ValueError, match="CF4_"):
            attest_regions(
                graph,
                source,
                (ref,),
                tenant_id=TENANT,
                run_id="cf4-test",
                store=store,
                saved_regions=saved,
            )


def test_region_limit_and_acquisition_failure_stay_unresolved(monkeypatch):
    from proofops.adapters.local import cf4_source_region as region

    store = Store()
    monkeypatch.setattr(region, "MAX_REGIONS", 0)
    receipt, _ = attestation(store)
    assert receipt["records"][0]["reason"] == "cf4_region_limit"
    assert store.calls == 0
    monkeypatch.setattr(region, "MAX_REGIONS", 24)

    def unavailable(*args, **kwargs):
        raise ValueError("OCR_COLLECTION_FAILED_RESERVATION_RETAINED:OCR_RESPONSE_INVALID")

    store.fetch = unavailable
    receipt, (source, graph, ref) = attestation(store)
    assert receipt["records"][0]["status"] == "unresolved"
    assert receipt["region_reads"][0]["failure"] == "OCR_RESPONSE_INVALID"
    assert (
        region.attest_regions(
            graph,
            source,
            (ref,),
            tenant_id=TENANT,
            run_id="cf4-test",
            store=store,
            saved_regions=receipt["region_reads"],
        )
        == receipt
    )
