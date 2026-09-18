"""Real source-bound Upstage extraction: fake transport, no network, no approvals."""

import json

import pytest
from proofops.application.claims import ExtractionOutputError, ExtractionProfile
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import SYSTEM_PROMPT, UpstageClaimExtractor

TEXT = "회사는 2030년까지 배출량을 20% 줄이기로 했다. 일반 산업 설명이다."


def test_overlapping_quote_occurrences_are_ambiguous(tmp_path):
    probe = FakeProbe(json.dumps({"claims": ["가가"]}))
    extractor, data = make_extractor(probe, tmp_path)
    data["untrusted_document_data"]["text"] = "가가가"
    with pytest.raises(ExtractionOutputError, match="MODEL_SPAN_OR_SCHEMA_INVALID"):
        extractor.extract(data)


def test_invalid_source_hash_rejected_before_call(tmp_path):
    probe = FakeProbe('{"claims": []}')
    extractor, data = make_extractor(probe, tmp_path)
    data["source_sha256"] = "not-a-hash"
    with pytest.raises(ValueError, match="EXTRACTION_PACKET_IDENTITY_INVALID"):
        extractor.extract(data)
    assert not probe.calls


def packet(text=TEXT):
    return {
        "tenant_id": "b490d4e4-0192-426c-9dff-c6c7b8c498d3",
        "document_version_id": "35d03dcb-c9d0-40d6-a3d1-8f9dc7322ee1",
        "parse_manifest_id": "62919374-bd2d-4273-85b4-7a1f793b8c14",
        "source_sha256": "c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde",
        "extraction_profile": None,  # replaced per-extractor below
        "untrusted_document_data": {
            "source_id": "11111111-2222-4333-8444-555555555555",
            "page_num": 25,
            "kind": "paragraph",
            "text": text,
        },
    }


class FakeProbe:
    """Caller-owned transport double; never touches the network."""

    def __init__(self, content=None, error=None):
        self.content = content
        self.error = error
        self.calls = []

    def complete(self, system, user_json, *, request_id, max_tokens=1024, json_mode=False):
        self.calls.append(
            {
                "system": system,
                "user_json": user_json,
                "request_id": request_id,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            }
        )
        if self.error is not None:
            raise self.error
        return {
            "model": "solar-pro3",
            "provider_request_id": "fake-provider-id",
            "provider_model": "solar-pro3-260323",
            "input_tokens": 50,
            "output_tokens": 10,
            "price_snapshot": {"fake": True},
            "cost_with_vat_reserve_usd": "0.0000099",
            "response_sha256": canonical_hash(self.content),
            "content": self.content,
        }


def make_extractor(probe, tmp_path):
    extractor = UpstageClaimExtractor(probe, tmp_path / "receipts")
    data = packet()
    data["extraction_profile"] = json.loads(
        json.dumps(
            {
                "model_sha256": extractor.profile.model_sha256,
                "prompt_sha256": extractor.profile.prompt_sha256,
                "rule_sha256": extractor.profile.rule_sha256,
                "synthetic": extractor.profile.synthetic,
                "replicate_id": extractor.profile.replicate_id,
                "extraction_epoch": extractor.profile.extraction_epoch,
            }
        )
    )
    return extractor, data


def test_profile_is_pinned_and_non_synthetic(tmp_path):
    first = UpstageClaimExtractor(FakeProbe('{"claims": []}'), tmp_path / "a")
    second = UpstageClaimExtractor(FakeProbe('{"claims": []}'), tmp_path / "b")
    assert isinstance(first.profile, ExtractionProfile)
    assert first.profile.synthetic is False
    assert (first.profile.model_sha256, first.profile.prompt_sha256, first.profile.rule_sha256) == (
        second.profile.model_sha256,
        second.profile.prompt_sha256,
        second.profile.rule_sha256,
    )
    assert first.profile.prompt_sha256 == canonical_hash(SYSTEM_PROMPT)


def test_valid_quotes_resolve_to_source_spans_with_receipts(tmp_path):
    quote = "배출량을 20% 줄이기로 했다"
    probe = FakeProbe(json.dumps({"claims": [quote]}, ensure_ascii=False))
    extractor, data = make_extractor(probe, tmp_path)
    result = extractor.extract(data)
    start = TEXT.index(quote)
    assert result == {
        "spans": [
            {
                "char_start": start,
                "char_end": start + len(quote),
                "quote": quote,
                "kind": "claim",
                "reason": None,
                "topic_ids": ["environment"],
            }
        ]
    }
    assert set(probe.calls[0]) == {"system", "user_json", "request_id", "max_tokens", "json_mode"}
    assert probe.calls[0]["system"] == SYSTEM_PROMPT
    assert "회사는" in probe.calls[0]["user_json"]  # model receives Korean, not escapes
    sent = json.loads(probe.calls[0]["user_json"])
    assert sent["tenant_id"] == data["tenant_id"]
    assert sent["document_version_id"] == data["document_version_id"]
    assert sent["parse_manifest_id"] == data["parse_manifest_id"]
    assert (
        sent["untrusted_document_data"]["source_id"] == data["untrusted_document_data"]["source_id"]
    )
    assert sent["untrusted_document_data"]["text"] == TEXT
    receipt = tmp_path / "receipts" / probe.calls[0]["request_id"]
    for name in ("packet.json", "request.json", "raw_response.json", "result.json"):
        assert (receipt / name).is_file()
    stored = json.loads((receipt / "raw_response.json").read_text())
    assert stored["provider_model"] == "solar-pro3-260323"
    assert stored["content"] == probe.content
    record = json.loads((receipt / "result.json").read_text())
    assert record["packet_sha256"] == canonical_hash(data)
    assert record["request_id"] == probe.calls[0]["request_id"]
    assert record["profile"]["synthetic"] is False
    assert "grade" not in json.dumps(result) and "label" not in json.dumps(result)


def test_request_id_is_derived_and_unique_per_packet(tmp_path):
    probe = FakeProbe(json.dumps({"claims": []}))
    first, data = make_extractor(probe, tmp_path)
    first.extract(data)
    other_probe = FakeProbe(json.dumps({"claims": []}))
    other = UpstageClaimExtractor(other_probe, tmp_path / "other")
    data["extraction_profile"] = {
        "model_sha256": other.profile.model_sha256,
        "prompt_sha256": other.profile.prompt_sha256,
        "rule_sha256": other.profile.rule_sha256,
        "synthetic": other.profile.synthetic,
        "replicate_id": other.profile.replicate_id,
        "extraction_epoch": other.profile.extraction_epoch,
    }
    other.extract(data)
    assert probe.calls[0]["request_id"] == other_probe.calls[0]["request_id"]
    assert 1 <= len(probe.calls[0]["request_id"]) <= 128


def test_duplicate_packet_refuses_to_overwrite_receipts(tmp_path):
    probe = FakeProbe(json.dumps({"claims": []}))
    extractor, data = make_extractor(probe, tmp_path)
    extractor.extract(data)
    receipt = tmp_path / "receipts" / probe.calls[0]["request_id"]
    before = {name: (receipt / name).read_bytes() for name in ("packet.json", "raw_response.json")}
    with pytest.raises(ValueError, match="EXTRACTION_RECEIPT_EXISTS"):
        extractor.extract(data)
    assert len(probe.calls) == 1
    for name, content in before.items():
        assert (receipt / name).read_bytes() == content


@pytest.mark.parametrize(
    "content",
    [
        json.dumps({"claims": ["missing quote"]}, ensure_ascii=False),
        json.dumps({"claims": ["다."]}, ensure_ascii=False),  # ambiguous: twice in TEXT
        json.dumps(
            {"claims": ["배출량을 20% 줄이기로 했다", "20% 줄이기로 했다"]}, ensure_ascii=False
        ),
        json.dumps({"claims": [""]}, ensure_ascii=False),
        json.dumps({"claims": ["배출량을 20% 줄이기로 했다"], "grade": "E3"}, ensure_ascii=False),
        "not json at all",
    ],
)
def test_raw_invalid_responses_retained_with_sanitized_error(tmp_path, content):
    probe = FakeProbe(content)
    extractor, data = make_extractor(probe, tmp_path)
    with pytest.raises(ExtractionOutputError, match="MODEL_SPAN_OR_SCHEMA_INVALID") as error:
        extractor.extract(data)
    assert content not in str(error.value)
    receipt = tmp_path / "receipts" / probe.calls[0]["request_id"]
    assert (receipt / "packet.json").is_file()
    assert (receipt / "request.json").is_file()
    assert json.loads((receipt / "raw_response.json").read_text())["content"] == content
    failure = json.loads((receipt / "failure.json").read_text())
    assert failure["error"] == "MODEL_SPAN_OR_SCHEMA_INVALID"
    assert failure["packet_sha256"] == canonical_hash(data)


def test_transport_failure_is_sanitized_retryable_and_recorded(tmp_path):
    probe = FakeProbe(error=OSError("boom secret-credential"))
    extractor, data = make_extractor(probe, tmp_path)
    with pytest.raises(ValueError, match="UPSTREAM_UNAVAILABLE"):
        extractor.extract(data)
    receipt = tmp_path / "receipts" / probe.calls[0]["request_id"]
    assert (receipt / "packet.json").is_file()
    assert (receipt / "request.json").is_file()
    failure = json.loads((receipt / "failure.json").read_text())
    assert failure["error"] == "UPSTREAM_UNAVAILABLE"
    assert "boom" not in json.dumps(failure) and "secret" not in json.dumps(failure)


def test_packet_identity_is_required(tmp_path):
    extractor, data = make_extractor(FakeProbe(json.dumps({"claims": []})), tmp_path)
    del data["parse_manifest_id"]
    with pytest.raises(ValueError, match="EXTRACTION_PACKET_IDENTITY_INVALID"):
        extractor.extract(data)


def test_no_source_quality_or_grade_is_ever_approved(tmp_path):
    quote = "배출량을 20% 줄이기로 했다"
    probe = FakeProbe(json.dumps({"claims": [quote]}, ensure_ascii=False))
    extractor, data = make_extractor(probe, tmp_path)
    result = extractor.extract(data)
    assert "source_quality" not in json.dumps(result)
    record_text = (tmp_path / "receipts" / probe.calls[0]["request_id"] / "result.json").read_text()
    assert "source_quality" not in record_text


@pytest.mark.parametrize(
    "code",
    [
        "BUDGET_EXHAUSTED",
        "BUDGET_SETTLEMENT_INVALID",
        "PRICE_RECHECK_REQUIRED",
        "PROBE_REQUEST_TOO_LARGE",
        "UPSTAGE_REQUEST_FAILED",
        "UPSTAGE_RECEIPT_INVALID_RESERVATION_RETAINED",
        "UPSTREAM_UNAVAILABLE",
        "UPSTAGE_HTTP_400",
        "UPSTAGE_HTTP_429",
        "UPSTAGE_HTTP_500",
        "UPSTAGE_HTTP_503",
    ],
)
def test_budget_and_provider_stop_are_not_transient(tmp_path, code):
    extractor, data = make_extractor(FakeProbe(error=ValueError(code)), tmp_path)
    with pytest.raises(ValueError, match=code):
        extractor.extract(data)


def test_pro4_profile_is_explicit_and_rejects_pro3_packet_before_call(tmp_path):
    from dataclasses import asdict

    from proofops_agent.upstage_extraction import _profile

    probe = FakeProbe('{"claims": []}')
    probe.model = "solar-pro4"
    extractor = UpstageClaimExtractor(probe, tmp_path / "pro4")
    assert extractor.profile == _profile("solar-pro4")
    data = packet()
    data["extraction_profile"] = asdict(_profile())
    with pytest.raises(ValueError, match="EXTRACTION_PACKET_IDENTITY_INVALID"):
        extractor.extract(data)
    assert not probe.calls
    data["extraction_profile"] = asdict(extractor.profile)
    assert extractor.extract(data) == {"spans": []}


@pytest.mark.parametrize("model", ["solar-pro99", None, []])
def test_unsupported_extraction_model_rejected_before_receipts(tmp_path, model):
    probe = FakeProbe('{"claims": []}')
    probe.model = model
    with pytest.raises(ValueError, match="UPSTAGE_MODEL_MISMATCH"):
        UpstageClaimExtractor(probe, tmp_path / "unsupported")
    assert not (tmp_path / "unsupported").exists()


def test_new_profile_rejects_cut_quotation_without_changing_legacy_span_replay(tmp_path):
    from proofops.application.claims import validate_extraction_response

    text = "두산밥캣은 KPI에 ‘2030 온실가스 감축 목표 달성을 위한 지역별"
    old_response = {
        "spans": [
            dict(
                char_start=0,
                char_end=len(text),
                quote=text,
                kind="claim",
                reason=None,
                topic_ids=["environment"],
            )
        ]
    }
    assert validate_extraction_response(old_response, text)[0].quote == text
    probe = FakeProbe(json.dumps({"claims": [text]}, ensure_ascii=False))
    extractor, data = make_extractor(probe, tmp_path)
    data["untrusted_document_data"]["text"] = text
    with pytest.raises(ExtractionOutputError, match="MODEL_SPAN_OR_SCHEMA_INVALID"):
        extractor.extract(data)
    assert len(list((tmp_path / "receipts").glob("*/raw_response.json"))) == 1


def test_invalid_quote_does_not_discard_exact_sibling_or_hide_uncovered_text(tmp_path):
    from proofops.application.claims import ClaimScope, discover_atomic_claims

    from tests.acceptance.test_claims import MANIFEST, TENANT, VERSION, graph_of

    text = "회사는 소재 기준을 정의했습니다. 새로운 소재가 환경영향을 줄일 것입니다."
    valid = "회사는 소재 기준을 정의했습니다."
    rewritten = "신소재는 친환경적입니다."
    extractor = UpstageClaimExtractor(
        FakeProbe(json.dumps({"claims": [rewritten, valid]}, ensure_ascii=False)),
        tmp_path / "receipts",
    )
    result = discover_atomic_claims(
        graph_of(text), ClaimScope(TENANT, VERSION, MANIFEST), extractor=extractor
    )
    assert [c.quote for c in result.claims] == [valid]
    assert any(e.state == "unknown" for e in result.exclusions)
    receipt = json.loads(next((tmp_path / "receipts").glob("*/result.json")).read_text())
    assert receipt["rejected_quote_indices"] == [0]


@pytest.mark.parametrize("expired", [False, True])
def test_duplicate_receipt_root_cannot_count_historical_spend(tmp_path, monkeypatch, expired):
    from datetime import UTC, datetime

    from proofops.adapters.local import upstage

    from tests.integration.test_upstage_probe import response

    now = [datetime(2026, 9, 18, tzinfo=UTC)]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now[0]

    monkeypatch.setattr(upstage, "datetime", Clock)
    probe = upstage.UpstageProbe("offline-key", tmp_path / "budget.sqlite3")
    raw = response()
    raw["choices"][0]["message"]["content"] = '{"claims": []}'
    calls = []
    monkeypatch.setattr(probe, "_post", lambda body: calls.append(body) or raw)
    first, data = make_extractor(probe, tmp_path / "first")
    first.extract(data)
    if expired:
        now[0] = datetime(2026, 9, 25, tzinfo=UTC)
    second, _ = make_extractor(probe, tmp_path / "second")
    code = "PRICE_RECHECK_REQUIRED" if expired else "DUPLICATE_PROBE_REQUEST"
    with pytest.raises(ValueError, match=code):
        second.extract(data)
    assert len(calls) == 1
    assert second.usage["model_calls"] == 0
    assert second.usage["committed_or_reserved_usd"] == "0"
