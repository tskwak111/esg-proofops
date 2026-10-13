"""PS1: exact location recovery and source-preserving native sentence joins."""

import io
from dataclasses import asdict, replace
from hashlib import sha256
from uuid import uuid4

import pytest
from proofops.application.claims import ClaimScope, ExtractionProfile, discover_atomic_claims
from proofops.application.ingest.graph_fusion import (
    CandidateBatch,
    CandidateBlock,
    ParserProfile,
    SourceArtifact,
    candidates_from_snapshot,
    fuse_candidates,
)
from proofops.domain.documents import NativeSource, PageGeometry
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def fixture(lines):
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=300)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(
        "\n".join(f"BT /F1 10 Tf {x} {300-y} Td ({text}) Tj ET" for x, y, text in lines).encode()
    )
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    content = output.getvalue()
    source = SourceArtifact(
        str(uuid4()), str(uuid4()), str(uuid4()), sha256(content).hexdigest(), "1", content
    )
    manifest, run = str(uuid4()), str(uuid4())
    return source, manifest, run


def block(source, manifest, run, ident, text, box, *, kind="paragraph", context=()):
    native = None if box is None else (box[0], 300 - box[3], box[2], 300 - box[1])
    return CandidateBlock(
        kind,
        NativeSource(
            source.document_version_id,
            manifest,
            run,
            ident,
            1,
            None,
            native,
            "pdf_bottom_left_points",
            text,
            0,
            len(text),
        ),
        PageGeometry(400, 300, 0, (0, 0, 400, 300)),
        context,
    )


def batch(source, manifest, run, blocks):
    return CandidateBatch(
        source.tenant_id,
        source.document_version_id,
        manifest,
        source.sha256,
        run,
        "upstage_async_standard",
        "1",
        "upstage-document-parse",
        "a" * 64,
        tuple(blocks),
    )


def recover(source, batches):
    from proofops.adapters.parsing.source_recovery import recover_sources

    return recover_sources(source, tuple(batches))


def test_missing_location_recovers_unique_exact_native_text_without_verifying_it():
    source, manifest, run = fixture([(30, 50, "Annual energy consumption fell 20 percent.")])
    original = batch(
        source,
        manifest,
        run,
        [
            block(
                source,
                manifest,
                run,
                "a",
                "Annual energy consumption fell 20 percent.",
                None,
                context=("vision_only",),
            )
        ],
    )
    batches, receipt = recover(source, [original])
    candidate = batches[0].blocks[0]
    assert original.blocks[0].bbox is None
    assert candidate.bbox is not None and receipt["located"] == 1
    graph = fuse_candidates(batches, tenant_id=source.tenant_id)
    assert graph.blocks[0].quality == "unverified"
    assert graph.blocks[0].source_ref().verification_state == "candidate"


@pytest.mark.parametrize(
    "lines,text",
    [
        (
            [
                (30, 50, "Annual energy consumption fell 20 percent."),
                (230, 50, "Annual energy consumption fell 20 percent."),
            ],
            "Annual energy consumption fell 20 percent.",
        ),
        (
            [(30, 50, "Annual energy consumption fell 20 percent.")],
            "Annual energy consumption fell 21 percent.",
        ),
    ],
)
def test_ambiguous_or_changed_text_stays_unlocated(lines, text):
    source, manifest, run = fixture(lines)
    original = batch(
        source,
        manifest,
        run,
        [
            block(
                source,
                manifest,
                run,
                "a",
                text,
                None,
                context=("provider_bbox=25,35,150,60", "vision_only"),
            )
        ],
    )
    batches, receipt = recover(source, [original])
    assert batches[0].blocks[0].bbox is None and receipt["located"] == 0


def test_join_preserves_fragment_refs_and_requests_the_whole_span():
    source, manifest, run = fixture(
        [(30, 50, "Annual energy consumption fell"), (30, 64, "20 percent.")]
    )
    original = batch(
        source,
        manifest,
        run,
        [
            block(source, manifest, run, "a", "Annual energy consumption fell", (30, 40, 200, 52)),
            block(source, manifest, run, "b", "20 percent.", (30, 54, 90, 66)),
        ],
    )
    batches, receipt = recover(source, [original])
    graph = fuse_candidates(batches, tenant_id=source.tenant_id)
    assert receipt["joined"] == 1

    class Extractor:
        profile = ExtractionProfile("1" * 64, "2" * 64, "3" * 64, True)
        calls = []

        def extract(self, packet):
            text = packet["untrusted_document_data"]["text"]
            self.calls.append(text)
            return {
                "spans": [
                    dict(
                        char_start=0,
                        char_end=len(text),
                        quote=text,
                        kind="claim",
                        topic_ids=["climate"],
                        reason=None,
                    )
                ]
            }

    extractor = Extractor()
    result = discover_atomic_claims(
        graph,
        ClaimScope(source.tenant_id, source.document_version_id, manifest),
        extractor=extractor,
    )
    assert extractor.calls == ["Annual energy consumption fell\n20 percent."]
    (claim,) = result.claims
    assert claim.quote == "Annual energy consumption fell\n20 percent."
    assert [ref.quote for ref in claim.source_refs] == [
        claim.quote,
        "Annual energy consumption fell",
        "20 percent.",
    ]
    assert [ref.bbox for ref in claim.source_refs[1:]] == [b.bbox for b in original.blocks]
    assert all(ref.verification_state == "candidate" for ref in claim.source_refs)
    from proofops_worker.extract_runner import select_stable_paragraph_sources

    assert select_stable_paragraph_sources(graph, result.scope, 1) == {
        claim.source_refs[0].source_id
    }
    replay = fuse_candidates(
        candidates_from_snapshot([asdict(b) for b in batches]), tenant_id=source.tenant_id
    )
    assert asdict(replay) == asdict(graph)


def test_qc_existing_ps1_restores_esg_reporting_with_exclusion_and_both_refs():
    first = "We report renewable energy performance to the ESG"
    last = "committee regularly, except the cancelled project."
    source, manifest, run = fixture([(30, 50, first), (30, 64, last)])
    original = batch(
        source,
        manifest,
        run,
        [
            block(source, manifest, run, "front", first, (30, 40, 290, 52)),
            block(source, manifest, run, "tail", last, (30, 54, 280, 66)),
        ],
    )
    recovered, receipt = recover(source, [original])
    assert receipt["joined"] == 1
    assert [b.source.raw_text for b in recovered[0].blocks[:2]] == [first, last]
    graph = fuse_candidates(recovered, tenant_id=source.tenant_id)
    from proofops.application.ingest.source_continuations import continuations, fragment_refs

    (parts,) = continuations(graph).values()
    refs = fragment_refs(parts, 0, len(first) + 1 + len(last))
    assert [r.quote for r in refs] == [first, last]
    assert all(r.verification_state == "candidate" for r in refs)
    assert receipt["joins"][0]["quote"] == first + "\n" + last
    assert "cancelled" in refs[-1].quote


@pytest.mark.parametrize(
    "kind,text,box",
    [
        ("heading", "20 percent.", (30, 54, 90, 66)),
        ("table", "20 percent.", (30, 54, 90, 66)),
        ("paragraph", "20 percent.", (230, 54, 290, 66)),
        ("paragraph", "20 percent.", (30, 154, 90, 166)),
        ("paragraph", "- 20 percent.", (30, 54, 90, 66)),
    ],
)
def test_join_rejects_other_columns_headings_tables_gaps_and_bullets(kind, text, box):
    source, manifest, run = fixture(
        [(30, 50, "Annual energy consumption fell"), (box[0], box[1] + 10, text)]
    )
    original = batch(
        source,
        manifest,
        run,
        [
            block(source, manifest, run, "a", "Annual energy consumption fell", (30, 40, 200, 52)),
            block(source, manifest, run, "b", text, box, kind=kind),
        ],
    )
    _, receipt = recover(source, [original])
    assert receipt["joined"] == 0


def test_profile_is_versioned_and_absent_from_historical_hashes():
    legacy = ParserProfile(str(uuid4()))
    assert "source_recovery" not in legacy.invocation_snapshot()
    new = replace(legacy, source_recovery="ps1-v1")
    assert new.config_hash() != legacy.config_hash()
    with pytest.raises(ValueError, match="source recovery"):
        replace(legacy, source_recovery="guess")


def test_join_rejects_completed_sentence_and_unselected_native_text():
    for first, native_middle in [
        ("Annual energy consumption fell.", ""),
        ("Annual energy consumption fell", "Extra unrelated words"),
    ]:
        lines = [(30, 50, first), (30, 64, "20 percent.")]
        if native_middle:
            lines.insert(1, (30, 57, native_middle))
        source, manifest, run = fixture(lines)
        original = batch(
            source,
            manifest,
            run,
            [
                block(source, manifest, run, "a", first, (30, 40, 200, 52)),
                block(source, manifest, run, "b", "20 percent.", (30, 54, 90, 66)),
            ],
        )
        _, receipt = recover(source, [original])
        assert receipt["joined"] == 0


def test_whole_join_is_rechecked_by_source_verifier(monkeypatch):
    from proofops.adapters.local import claim_source_verification as verifier

    source, manifest, run = fixture(
        [(30, 50, "Annual energy consumption fell"), (30, 64, "20 percent.")]
    )
    original = batch(
        source,
        manifest,
        run,
        [
            block(source, manifest, run, "a", "Annual energy consumption fell", (30, 40, 200, 52)),
            block(source, manifest, run, "b", "20 percent.", (30, 54, 90, 66)),
        ],
    )
    batches, _ = recover(source, [original])
    graph = fuse_candidates(batches, tenant_id=source.tenant_id)
    joined = next(
        b for b in graph.blocks if b.raw_text == "Annual energy consumption fell\n20 percent."
    )
    seen = []

    def reading(document, pdf, block, interactive, glyphs):
        seen.append(block.raw_text)
        return dict(
            reason="rendered_quote_unresolved",
            rendered={"text": "Annual energy consumption fell 20 percent."},
        )

    monkeypatch.setattr(verifier, "_read_paragraph", reading)
    receipt = verifier.attest_claim_spans(
        graph, source.content, (joined.source_ref(),), tenant_id=source.tenant_id
    )
    assert seen == [joined.raw_text] and receipt["records"][0]["status"] == "verified"
    monkeypatch.setattr(
        verifier,
        "_read_paragraph",
        lambda *a: dict(
            reason="rendered_quote_unresolved",
            rendered={"text": "Annual energy consumption fell 21 percent."},
        ),
    )
    assert (
        verifier.attest_claim_spans(
            graph, source.content, (joined.source_ref(),), tenant_id=source.tenant_id
        )["records"][0]["status"]
        == "unresolved"
    )


def test_parser_wires_opt_in_into_new_immutable_artifact(tmp_path):
    from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser

    from tests.integration.test_mixed_parser import document, profile

    source = document()
    config = replace(
        profile(), parser_mode="local", claim_physical_pages=(), source_recovery="ps1-v1"
    )
    parser = OpenDataLoaderParser(artifact_root=tmp_path)
    artifact = parser.parse(source, config, tenant_id=source.tenant_id)
    directory = tmp_path / source.tenant_id / source.document_version_id / config.parse_manifest_id
    assert (directory / "source-recovery.json").is_file()
    assert asdict(parser.load_verified(source, config, tenant_id=source.tenant_id)) == asdict(
        artifact
    )


def test_alternative_native_word_order_never_drops_unmapped_text():
    from proofops.adapters.parsing.source_recovery import _locate, _streams

    def word(text, x):
        return dict(text=text, x0=x, x1=x + 20, top=20, bottom=30)

    words = [word("Energy", 10), word("unrelated", 35), word("fell", 60)]
    alternative = [words[0], word("unrelated merged", 35), words[2]]
    assert _locate("Energy fell", words, _streams(words, [], alternative)) is None


def test_mislabeled_paragraph_heading_is_vetoed_by_native_typography():
    from types import SimpleNamespace

    from proofops.adapters.parsing.source_recovery import _heading_like, _typography

    text = "Section heading" + "Long ordinary paragraph content describing energy use."
    chars = [
        dict(text=char, size=14 if i < 15 else 10, fontname="Helvetica")
        for i, char in enumerate(text)
    ]
    typography = _typography(SimpleNamespace(chars=chars))
    assert _heading_like("Section heading", typography)
    assert not _heading_like("Long ordinary paragraph content describing energy use.", typography)


def test_nominal_heading_does_not_join_at_the_same_body_font_size():
    from proofops.adapters.parsing.source_recovery import _continues

    source, manifest, run = fixture([])
    heading = block(
        source, manifest, run, "a", "최고 의사결정기구의 책임 및 역할", (30, 40, 200, 52)
    )
    prose = block(
        source, manifest, run, "b", "기후 관련 위험과 기회를 감독합니다.", (30, 54, 200, 66)
    )
    assert not _continues(heading, prose)
