"""R14 source-ID claim selection: real stored responses and real source text, offline.

No network, no key, no ledger: every model answer here is a byte-copy of an
actual stored Upstage response from the root's own R13 experiments
(``outputs/agent-results/R13-cross-model/solar-pro4/receipts`` and
``outputs/agent-results/R13-id-selection``), replayed through a fake transport.

The regression these tests exist for is a real observed loss: solar-pro4 chose
the right Lotte achievement sentence but retyped ``2023 년`` as ``2023년``, so
the exact-quote locator (correctly) refused it. Citation matching is NOT relaxed
anywhere below; the source-ID profile simply removes the model's opportunity to
retype the source at all.
"""

import json
from dataclasses import asdict

import pytest
from proofops.application.claims import ExtractionOutputError
from proofops_agent.upstage_extraction import (
    _MAX_SOURCE_SENTENCES,
    SOURCE_ID_CONTEXT_SUFFIX,
    SOURCE_ID_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    UpstageClaimExtractor,
    _profile,
    _profile_with_options,
)

from tests.integration.test_upstage_extraction import FakeProbe

# Real parser output for Lotte p.29, sentence by sentence (byte-copy of the
# stored packet text; note the literal `2023 년` and `환경 부` spacing).
LOTTE_SENTENCES = (
    "2 폐기물 순환자원 인정 롯데케미칼의 주요 사업장(여수, 대산, 울산)은 순환경제 활성화를 "
    "목적으로 환경 부에서 실시하고 있는 순환자원 인정제도*에 적극적으로 참여하고 있습니다.",
    "2023 년부터 순환자원 인정을 취득하여 사업장별 1건 이상 인정 취득이라는 당사 목표를 "
    "달성했습니다.",
    "이후, 선순환시스템 구축을 위해 순환자원을 원료로 활용하기 위한 노력을 계속하고 있습니다.",
    "또한, 2026년부터 울산사업장을 대상으로 폐기물 매립 제로(Zero Waste To Landfill, ZWTL) "
    "검증 취득을 본격적으로 추진할 예정입니다.",
)
LOTTE_SOURCE = " ".join(LOTTE_SENTENCES)
LOTTE_SOURCE_ID = "84bac7d1-4110-5582-8f0f-35d56053cb9d"
ACHIEVEMENT = LOTTE_SENTENCES[1]
# Byte-copy of the stored solar-pro4 quote-copy response for that exact source:
# `환경 부` became `환경부`, the `*` marker vanished and `2023 년` became `2023년`.
REAL_PRO4_QUOTE_RESPONSE = json.dumps(
    {
        "claims": [
            "롯데케미칼의 주요 사업장(여수, 대산, 울산)은 순환경제 활성화를 목적으로 환경부에서 "
            "실시하고 있는 순환자원 인정제도에 적극적으로 참여하고 있습니다.",
            "2023년부터 순환자원 인정을 취득하여 사업장별 1건 이상 인정 취득이라는 당사 목표를 "
            "달성했습니다.",
            LOTTE_SENTENCES[2],
            LOTTE_SENTENCES[3],
        ]
    },
    ensure_ascii=False,
)
# Byte-copy of the stored solar-pro4 source-ID response for the same source.
REAL_PRO4_ID_RESPONSE = json.dumps(
    {"sentence_ids": [f"{LOTTE_SOURCE_ID}:{index}" for index in range(4)]}
)
# Real Kia target heading and the real bare category cell from R13-id-selection.
KIA_TARGET = "2045년 탄소중립 달성"
KIA_TARGET_SOURCE_ID = "3e89415c-e2e7-5ed7-b17e-84872fcdfe9c"
BARE_CATEGORY = "폐수"
BARE_CATEGORY_SOURCE_ID = "b11cbe07-1bc3-5d13-bbdf-b4793de7383e"


def packet(extractor, *, text=LOTTE_SOURCE, source_id=LOTTE_SOURCE_ID):
    """Real run identity (Lotte p.29) with this extractor's own frozen profile."""
    return {
        "tenant_id": "1ce4bf3f-95f7-455f-aa90-1ee812fda1a6",
        "document_version_id": "e28a7998-2a85-41b3-b74f-0fe3bcfc5d63",
        "parse_manifest_id": "4a51485d-ebab-521b-b562-b8f1b68a27d1",
        "source_sha256": "d8dd4f3e510428fcfd86c4e0003b19f35f2d5a8b30fdf9f55ccee166d0bd5a52",
        "extraction_profile": asdict(extractor.profile),
        "untrusted_document_data": {
            "source_id": source_id,
            "page_num": 29,
            "kind": "paragraph",
            "text": text,
        },
    }


def id_extractor(tmp_path, content, **flags):
    probe = FakeProbe(content)
    extractor = UpstageClaimExtractor(
        probe, tmp_path / "receipts", extraction_source_ids=True, **flags
    )
    return probe, extractor


def test_real_quote_copy_loses_the_achievement_sentence_that_ids_recover(tmp_path):
    """The actual regression: retyped quotes drop a real claim; ids keep it exactly."""
    quote_probe = FakeProbe(REAL_PRO4_QUOTE_RESPONSE)
    quote_extractor = UpstageClaimExtractor(quote_probe, tmp_path / "quotes")
    quoted = quote_extractor.extract(packet(quote_extractor))["spans"]
    # Both retyped quotes are absent from the source, so the exact locator drops
    # them -- the achievement sentence is lost even though it was selected.
    assert ACHIEVEMENT in LOTTE_SOURCE  # the sentence really is in the parsed source
    assert not [span for span in quoted if "달성했습니다" in span["quote"]]
    assert len(quoted) == 2
    stored = json.loads(
        (tmp_path / "quotes" / quote_probe.calls[0]["request_id"] / "result.json").read_text()
    )
    assert stored["rejected_quote_indices"] == [0, 1]

    probe, extractor = id_extractor(tmp_path / "ids", REAL_PRO4_ID_RESPONSE)
    spans = extractor.extract(packet(extractor))["spans"]
    assert [span["quote"] for span in spans] == list(LOTTE_SENTENCES)
    assert [(span["char_start"], span["char_end"]) for span in spans] == [
        (0, 99),
        (100, 157),
        (158, 208),
        (209, 296),
    ]
    achievement = [span for span in spans if "달성했습니다" in span["quote"]]
    assert len(achievement) == 1
    # The literal source spacing is preserved because the span is restored from
    # the original offsets, never from the response.
    assert achievement[0]["quote"] == ACHIEVEMENT
    assert "2023 년부터" in achievement[0]["quote"]
    assert LOTTE_SOURCE[achievement[0]["char_start"] : achievement[0]["char_end"]] == ACHIEVEMENT
    assert json.loads(probe.calls[0]["user_json"])["untrusted_document_data"].get("text") is None


def test_real_target_is_kept_and_a_bare_category_cell_selects_nothing(tmp_path):
    """Both real R13 single-sentence sources behave as observed, offline."""
    _, target = id_extractor(
        tmp_path / "target", json.dumps({"sentence_ids": [f"{KIA_TARGET_SOURCE_ID}:0"]})
    )
    assert target.extract(packet(target, text=KIA_TARGET, source_id=KIA_TARGET_SOURCE_ID)) == {
        "spans": [
            {
                "char_start": 0,
                "char_end": len(KIA_TARGET),
                "quote": KIA_TARGET,
                "kind": "claim",
                "reason": None,
                "topic_ids": ["environment"],
            }
        ]
    }
    _, bare = id_extractor(tmp_path / "bare", json.dumps({"sentence_ids": []}))
    # An empty selection is not an absence finding: the source stays uncovered
    # and its coverage is decided downstream, exactly as for quote mode.
    assert bare.extract(
        packet(bare, text=BARE_CATEGORY, source_id=BARE_CATEGORY_SOURCE_ID)
    ) == {"spans": []}


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"sentence_ids": [f"{LOTTE_SOURCE_ID}:99"]}),  # unknown index
        json.dumps({"sentence_ids": [f"{LOTTE_SOURCE_ID}:1", f"{LOTTE_SOURCE_ID}:1"]}),  # repeated
        json.dumps({"sentence_ids": [f"{KIA_TARGET_SOURCE_ID}:0"]}),  # another source's id
        json.dumps({"sentence_ids": [BARE_CATEGORY_SOURCE_ID]}),  # a context block id
        json.dumps({"sentence_ids": ["1"]}),  # id not bound to the source
        json.dumps({"sentence_ids": [1]}),  # not a string
        json.dumps({"sentence_ids": [f"{LOTTE_SOURCE_ID}:1"], "claims": [ACHIEVEMENT]}),  # extra
        json.dumps({"claims": [ACHIEVEMENT]}, ensure_ascii=False),  # quote-copy shape
        json.dumps({"sentence_ids": {"0": True}}),  # not a list
        json.dumps({"spans": [{"char_start": 0, "char_end": 5}]}),  # invented offsets
    ],
)
def test_only_the_exact_supplied_ids_are_accepted(tmp_path, content):
    probe, extractor = id_extractor(tmp_path, content)
    with pytest.raises(ExtractionOutputError, match="MODEL_SPAN_OR_SCHEMA_INVALID"):
        extractor.extract(packet(extractor))
    # The refusal is durable, so a replay cannot turn it into a result.
    directory = tmp_path / "receipts" / probe.calls[0]["request_id"]
    assert json.loads((directory / "failure.json").read_text())["error"] == (
        "MODEL_SPAN_OR_SCHEMA_INVALID"
    )
    with pytest.raises(ExtractionOutputError, match="MODEL_SPAN_OR_SCHEMA_INVALID"):
        extractor.extract(packet(extractor))
    assert len(probe.calls) == 1


def test_replay_serves_the_stored_response_without_a_second_call(tmp_path):
    probe, extractor = id_extractor(tmp_path, REAL_PRO4_ID_RESPONSE)
    first = extractor.extract(packet(extractor))
    second = extractor.extract(packet(extractor))
    assert first == second
    assert len(probe.calls) == 1
    directory = tmp_path / "receipts" / probe.calls[0]["request_id"]
    stored = json.loads((directory / "result.json").read_text())
    assert stored["profile"] == asdict(extractor.profile)
    assert stored["rejected_sentence_ids"] == []


def test_a_tampered_stored_request_is_refused_instead_of_replayed(tmp_path):
    probe, extractor = id_extractor(tmp_path, REAL_PRO4_ID_RESPONSE)
    extractor.extract(packet(extractor))
    request_path = tmp_path / "receipts" / probe.calls[0]["request_id"] / "request.json"
    request_path.chmod(0o600)
    body = json.loads(request_path.read_text())
    body["system_prompt"] = SYSTEM_PROMPT
    request_path.write_text(json.dumps(body, sort_keys=True, ensure_ascii=False))
    with pytest.raises(ValueError, match="EXTRACTION_RECEIPT_EXISTS"):
        extractor.extract(packet(extractor))
    assert len(probe.calls) == 1


def test_the_source_id_profile_is_distinct_from_every_existing_profile():
    source_ids = _profile_with_options(source_ids=True)
    existing = [
        _profile(),
        _profile_with_options(year_notation=True),
        _profile_with_options(extraction_context=True),
        _profile_with_options(extraction_context=True, extraction_table_context=True),
    ]
    assert _profile() == _profile_with_options()  # legacy hash unchanged
    assert all(source_ids.rule_sha256 != other.rule_sha256 for other in existing)
    assert all(source_ids.prompt_sha256 != other.prompt_sha256 for other in existing)
    assert source_ids.synthetic is False
    combined = _profile_with_options(extraction_context=True, source_ids=True)
    assert combined.rule_sha256 != source_ids.rule_sha256
    assert combined.prompt_sha256 != source_ids.prompt_sha256
    assert SOURCE_ID_SYSTEM_PROMPT != SYSTEM_PROMPT


def test_the_sent_wire_carries_only_locally_minted_ids_and_the_id_prompt(tmp_path):
    probe, extractor = id_extractor(tmp_path, json.dumps({"sentence_ids": []}))
    extractor.extract(packet(extractor))
    call = probe.calls[0]
    assert call["system"] == SOURCE_ID_SYSTEM_PROMPT
    assert call["json_mode"] is True
    sent = json.loads(call["user_json"])["untrusted_document_data"]
    assert set(sent) == {"source_id", "source_sentences"}
    assert [item["sentence_id"] for item in sent["source_sentences"]] == [
        f"{LOTTE_SOURCE_ID}:{index}" for index in range(4)
    ]
    # Every sent sentence is a literal substring of the real source text.
    assert all(item["text"] in LOTTE_SOURCE for item in sent["source_sentences"])


def test_a_source_with_too_many_sentences_is_not_served_and_costs_nothing(tmp_path):
    probe, extractor = id_extractor(tmp_path, json.dumps({"sentence_ids": []}))
    crowded = " ".join(
        f"문장 {index} 배출량을 줄였습니다." for index in range(_MAX_SOURCE_SENTENCES + 1)
    )
    with pytest.raises(ExtractionOutputError, match="EXTRACTION_SOURCE_SENTENCES_UNBOUNDED"):
        extractor.extract(packet(extractor, text=crowded))
    assert not probe.calls
    # No receipt, no charge, and the source simply stays unknown for a later run.
    assert not list((tmp_path / "receipts").iterdir())


def test_context_mode_still_requires_its_graph_and_plain_mode_refuses_one(tmp_path):
    from tests.acceptance.test_preliminary_table_sources import table_corpus

    graph, _claim, block = table_corpus()
    loose = block("loose")
    _, contextual = id_extractor(
        tmp_path / "context", json.dumps({"sentence_ids": []}), extraction_context=True
    )
    data = packet(contextual, text=loose.normalized_text, source_id=loose.source_id)
    data["tenant_id"] = graph.tenant_id
    data["document_version_id"] = graph.document_version_id
    data["parse_manifest_id"] = graph.parse_manifest_id
    data["source_sha256"] = graph.source_sha256
    data["untrusted_document_data"]["kind"] = loose.kind
    data["untrusted_document_data"]["page_num"] = loose.page_num
    with pytest.raises(ValueError, match="EXTRACTION_CONTEXT_REQUIRED"):
        contextual.extract(data)
    context_probe = contextual._probe
    assert contextual.extract(data, context_graph=graph) == {"spans": []}
    assert context_probe.calls[-1]["system"] == SOURCE_ID_SYSTEM_PROMPT + SOURCE_ID_CONTEXT_SUFFIX
    sent = json.loads(context_probe.calls[-1]["user_json"])["untrusted_document_data"]
    assert set(sent) == {
        "source_id",
        "source_sentences",
        "context_blocks",
        "omitted_source_ids",
    }
    # Context blocks never carry a selectable id.
    assert all("sentence_id" not in entry for entry in sent["context_blocks"])

    _, plain = id_extractor(tmp_path / "plain", json.dumps({"sentence_ids": []}))
    with pytest.raises(ValueError, match="EXTRACTION_CONTEXT_UNEXPECTED"):
        plain.extract(packet(plain), context_graph=graph)
