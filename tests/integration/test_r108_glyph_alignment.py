"""Opt-in spacing recovery must never repair content or cross source locations."""

from copy import deepcopy

import pytest
from proofops.adapters.local import glyph_alignment_verification as verifier


def reading():
    words = [
        dict(index=0, text="C", bbox=[0, 0, 5, 10]),
        dict(index=1, text="arbon", bbox=[5.5, 0, 30, 10]),
        dict(index=2, text="2024", bbox=[34, 0, 54, 10]),
        dict(index=3, text="10", bbox=[58, 0, 68, 10]),
        dict(index=4, text="tCO2e", bbox=[72, 0, 97, 10]),
    ]
    indices = [[0], list(range(1, 6)), list(range(7, 11)), [12, 13], list(range(15, 20))]
    return dict(
        reason="rendered_quote_unresolved",
        words=words,
        rendered=dict(status="read", text="Carbon 2024 10 tCO2e"),
        glyph_geometry=dict(
            source_sha256="a" * 64,
            physical_page=1,
            matched_words=[
                dict(native_word_index=w["index"], ink_bbox=w["bbox"], pdfium_char_indices=i)
                for w, i in zip(words, indices)
            ],
        ),
    )


def check(r=None, **kwargs):
    return verifier.align_reading(
        native="C arbon 2024 10 tCO2e",
        quote="C arbon 2024 10 tCO2e",
        reading=r or reading(),
        page_num=kwargs.get("page_num", 1),
        bbox=kwargs.get("bbox", [0, 0, 100, 12]),
        source_sha256="a" * 64,
    )


def test_artificial_space_requires_glyph_proof_and_reversible_offset():
    result = check()
    assert result["status"] == "verified"
    assert result["deleted_native_offsets"] == [1]
    assert result["native_text"] == "C arbon 2024 10 tCO2e"
    assert result["aligned_text"] == "Carbon 2024 10 tCO2e"
    assert result["aligned_to_native"] == [0] + list(range(2, len(result["native_text"])))


@pytest.mark.parametrize(
    "text",
    [
        "Carbon 2024 11 tCO2e",
        "Carbon 2025 10 tCO2e",
        "Carbon 2024 10 kgCO2e",
        "Carbon 2024 -10 tCO2e",
        "carbon 2024 10 tCO2e",
    ],
)
def test_content_veto(text):
    r = reading()
    r["rendered"]["text"] = text
    assert check(r)["reason"] == "character_veto"
    assert check(r)["status"] == "rejected"


def test_line_page_and_location_veto():
    r = reading()
    r["words"][1]["bbox"] = [5.5, 15, 30, 25]
    r["glyph_geometry"]["matched_words"][1]["ink_bbox"] = [5.5, 15, 30, 25]
    assert check(r, bbox=[0, 0, 100, 30])["status"] == "rejected"
    assert check(r, bbox=[0, 0, 100, 30])["reason"] == "cross_line_space_veto"
    assert check(page_num=2)["status"] == "rejected"
    assert check(bbox=[100, 0, 200, 12])["status"] == "rejected"


def test_actual_space_large_gap_missing_proof_and_ambiguity_remain_unresolved():
    r = reading()
    r["glyph_geometry"]["matched_words"][1]["pdfium_char_indices"] = list(range(2, 7))
    assert check(r)["status"] == "unresolved"
    r = reading()
    r["words"][1]["bbox"][0] = 8
    assert check(r)["status"] != "verified"
    r = reading()
    r.pop("glyph_geometry")
    assert check(r)["status"] == "unresolved"
    r = reading()
    r["rendered"]["text"] *= 2
    assert check(r)["status"] != "verified"


def test_policy_is_opt_in_and_tampered_policy_refused():
    from proofops.adapters.local import claim_source_policies as registry
    from proofops.adapters.local import claim_source_verification as strict
    from proofops.adapters.local import claim_span_typography as typography

    assert registry.publication_reader(strict.claim_source_policy()) is strict
    assert registry.claim_source_reader(typography.claim_source_policy()) is typography
    policy = verifier.claim_source_policy()
    assert registry.publication_reader(policy) is verifier
    assert registry.claim_source_reader(policy) is verifier
    changed = deepcopy(policy)
    changed["wrapper_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        registry.claim_source_reader(changed)


def test_original_pdf_writer_replay_and_provenance_guards(monkeypatch):
    from dataclasses import dataclass, replace

    from proofops.adapters.local import claim_source_verification as strict

    from tests.integration.test_claim_source_verification import TENANT, inputs

    source, graph, ref = inputs()
    monkeypatch.setattr(
        strict,
        "_rendered_text",
        lambda *a, **k: dict(status="read", text="Page 1 emissions 1234 tCO2e"),
    )
    receipt = verifier.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert receipt["records"][0]["status"] == "verified"
    assert receipt["baseline_receipt"]["records"][0]["status"] == "verified"
    assert graph.blocks[0].quality == "unverified"

    # Receipt equality must be checked before any claim/source promotion.
    @dataclass(frozen=True)
    class ClaimFixture:
        source_quality: str
        source_refs: tuple

    @dataclass(frozen=True)
    class DiscoveryFixture:
        claims: tuple

    discovery = DiscoveryFixture((ClaimFixture("unverified", (ref,)),))
    replayed, scoped = verifier.replay_claim_spans(
        receipt, graph, source, discovery, tenant_id=TENANT
    )
    assert replayed.claims[0].source_quality == "verified"
    assert scoped.verified_spans[0].quote == ref.quote
    assert all(b.quality != "verified" for b in scoped.blocks)
    tampered = deepcopy(receipt)
    tampered["records"][0]["ref"]["quote"] = "emissions 1235 tCO2e"
    with pytest.raises(ValueError, match="GLYPH_ALIGNMENT_RECEIPT_MISMATCH"):
        verifier.replay_claim_spans(tampered, graph, source, discovery, tenant_id=TENANT)
    with pytest.raises(ValueError):
        verifier.attest_claim_spans(graph, source + b"x", (ref,), tenant_id=TENANT)
    with pytest.raises(ValueError):
        verifier.attest_claim_spans(graph, source, (ref,), tenant_id="foreign")
    for bad in (
        replace(ref, page_num=2),
        replace(ref, bbox=(0, 0, 20, 20)),
        replace(ref, quote=ref.quote.replace("1234", "1235")),
        replace(ref, document_version_id="55555555-5555-4555-8555-555555555555"),
    ):
        bad_receipt = verifier.attest_claim_spans(graph, source, (bad,), tenant_id=TENANT)
        assert bad_receipt["records"][0]["status"] == "unresolved"


@pytest.mark.parametrize("field,value", [("source_sha256", "b" * 64), ("physical_page", 2)])
def test_glyph_identity_cannot_be_borrowed(field, value):
    r = reading()
    r["glyph_geometry"][field] = value
    assert check(r)["status"] == "rejected"


def test_failed_native_or_ocr_guards_are_never_recovered():
    r = reading()
    r["reason"] = "interactive_visibility_requires_review"
    assert check(r)["status"] == "unresolved"
    r = reading()
    r["rendered"]["status"] = "unresolved"
    assert check(r)["status"] == "unresolved"
    r = reading()
    r["words"][1]["bbox"][0] = float("nan")
    assert check(r)["status"] == "rejected"


def test_run_service_accepts_explicit_profile_without_changing_default(tmp_path):
    from proofops.application.runs import RunService

    from tests.integration import test_run_lifecycle as lifecycle

    service, _ = lifecycle.setup(tmp_path)
    assert service.claim_source_policy is None
    opted_in = RunService(
        service.store,
        service.uploads,
        service.registry,
        extraction_profile=service.extraction_profile,
        extraction_mode="upstage_probe",
        claim_source_policy=verifier.claim_source_policy(),
    )
    assert opted_in.claim_source_policy["profile"] == "glyph-alignment-v1"
    assert service.claim_source_policy is None


def test_new_recovery_does_not_fold_unicode_characters():
    r = reading()
    r["rendered"]["text"] = "cafe\u0301"
    result = verifier.align_reading(
        native="café",
        quote="café",
        reading=r,
        page_num=1,
        bbox=[0, 0, 100, 12],
        source_sha256="a" * 64,
    )
    assert result["reason"] == "character_veto"
    assert result["status"] == "rejected"
