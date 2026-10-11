import pytest
from proofops_agent.upstage_extraction import UpstageClaimExtractor

from evaluation.w7_sentence_replay import NoTransport


def test_short_dispatch_selection_restores_original_offsets_and_rejects_uuid_echo(tmp_path):
    source = "00000000-0000-4000-8000-000000000001"
    text = "당사는 태양광 설비를 운영합니다."
    old = UpstageClaimExtractor(NoTransport(), tmp_path / "old", extraction_source_ids=True)
    new = UpstageClaimExtractor(
        NoTransport(), tmp_path / "new", extraction_source_ids=True, extraction_i4_identity=True
    )
    index = old._sentence_index(text, source, False)
    before, _ = old._resolve_sentence_ids({"sentence_ids": [index[0][0]]}, text, source)
    after, _ = new._resolve_sentence_ids({"sentence_ids": ["c0"]}, text, source)
    assert before == after
    assert new.profile != old.profile
    packet = dict(
        tenant_id=source,
        document_version_id=source,
        parse_manifest_id=source,
        source_sha256="0" * 64,
        untrusted_document_data=dict(source_id=source, kind="paragraph", text=text, page_num=1),
    )
    system, wire, _ = new._source_id_wire(packet, text, "0" * 64, None)
    assert wire["untrusted_document_data"]["source_sentences"] == [
        {"sentence_id": "c0", "text": text}
    ]
    assert "dispatch-local selectors c0" in system
    for ids in ([index[0][0]], ["c99"], ["c0", "c0"]):
        with pytest.raises(ValueError, match="unknown or repeated"):
            new._resolve_sentence_ids({"sentence_ids": ids}, text, source)
