import json
from dataclasses import asdict
from types import SimpleNamespace
from uuid import uuid4

import pytest
from proofops.application.ingest.table_row_candidates import row_candidates
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_extraction import UpstageClaimExtractor, _profile_with_options
from proofops_worker.extract_runner import select_stable_paragraph_sources


class Probe:
    model = "openai/gpt-6-luna"
    wire_policy_version = 2

    def complete(self, system, user, **kwargs):
        self.system = system
        data = json.loads(user)["untrusted_document_data"]
        return {
            "content": json.dumps(
                {"sentence_ids": [s["sentence_id"] for s in data["source_sentences"]]}
            )
        }


def packet(text, kind="table"):
    return {
        **{k: str(uuid4()) for k in ("tenant_id", "document_version_id", "parse_manifest_id")},
        "source_sha256": "a" * 64,
        "untrusted_document_data": {
            "source_id": str(uuid4()),
            "page_num": 1,
            "kind": kind,
            "text": text,
        },
    }


def test_row_quote_and_offsets_never_contain_header_or_other_row():
    text = "지표\t단위\t2024년 실적\n온실가스 배출량\ttCO2-eq\t123\n용수 사용량\t㎥\t456"
    rows = row_candidates(text, kind="table")
    assert [text[r.start : r.end] for r in rows] == [
        "온실가스 배출량\ttCO2-eq\t123",
        "용수 사용량\t㎥\t456",
    ]
    assert all(text[r.header_start : r.header_end] == "지표\t단위\t2024년 실적" for r in rows)
    assert not row_candidates("2030 2040 2050\n10% 30% 50%", kind="figure")
    assert not row_candidates("123", kind="table_cell")
    assert row_candidates(
        "123", kind="table_cell", table_context=("온실가스 배출량", "2024년 tCO2e")
    )


def test_profiles_pin_separate_rules_and_legacy_hashes(tmp_path):
    base = _profile_with_options(source_ids=True)
    a = _profile_with_options(source_ids=True, extraction_table_rows=True)
    b = _profile_with_options(source_ids=True, extraction_recall_prompt=True)
    both = _profile_with_options(
        source_ids=True, extraction_table_rows=True, extraction_recall_prompt=True
    )
    assert len({x.rule_sha256 for x in (base, a, b, both)}) == 4
    assert len({x.prompt_sha256 for x in (base, a, b, both)}) == 4
    for option in ("extraction_table_rows", "extraction_recall_prompt"):
        with pytest.raises(ValueError):
            _profile_with_options(**{option: True})
        with pytest.raises(ValueError):
            _profile_with_options(source_ids=True, extraction_atomic=True, **{option: True})
    probe = Probe()
    ex = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_recall_prompt=True,
    )
    p = packet("지표\t단위\t2024년\n온실가스 배출량\ttCO2e\t123")
    result = ex.extract(p)
    assert result["spans"][0]["quote"] == "온실가스 배출량\ttCO2e\t123"
    assert "할 계획" in probe.system and "감독" in probe.system
    assert ex.extract(p) == result
    request = json.loads(next(tmp_path.glob("*/request.json")).read_text())
    assert canonical_hash(request["system_prompt"]) == ex.profile.prompt_sha256
    entry = json.loads(request["user_json"])["untrusted_document_data"]["source_sentences"][0]
    assert entry["parent_context"][0]["text"] == "지표\t단위\t2024년"
    assert "sentence_id" not in entry["parent_context"][0]
    assert (
        asdict(ex.profile)
        == json.loads(next(tmp_path.glob("*/result.json")).read_text())["profile"]
    )


def test_worker_default_excludes_rows_opt_in_includes_them():
    blocks = [
        SimpleNamespace(
            source_id=str(i),
            page_num=1,
            kind=kind,
            quality="unverified",
            winner=0,
            bbox=None,
            normalized_text=text,
        )
        for i, (kind, text) in enumerate(
            [
                ("paragraph", "당사는 환경 관리체계를 운영합니다."),
                ("table", "지표\t단위\t2024년\n온실가스 배출량\ttCO2e\t123"),
                ("figure", "2030 2040\n10% 30%"),
            ]
        )
    ]
    graph = SimpleNamespace(blocks=blocks)
    scope = SimpleNamespace(mode="declared_subset", selected_pages=(1,))
    assert select_stable_paragraph_sources(graph, scope, 8) == {"0"}
    assert select_stable_paragraph_sources(graph, scope, 8, extraction_table_rows=True) == {
        "0",
        "1",
    }


@pytest.mark.parametrize("option", ["extraction_table_rows", "extraction_recall_prompt"])
def test_pilot_opt_in_frozen_and_resume_restored(tmp_path, monkeypatch, option):
    import sys

    from pypdf import PdfWriter

    from evaluation import local_upstage_pilot as pilot

    pdf = tmp_path / "source.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(pdf)
    state = tmp_path / "state"
    argv = [
        "pilot",
        "--state",
        str(state),
        "--pdf",
        str(pdf),
        "--report-year",
        "2025",
        "--period-start",
        "2025-01-01",
        "--period-end",
        "2025-12-31",
        "--parser",
        "local",
        "--extraction-source-ids",
        "--" + option.replace("_", "-"),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    assert pilot.main() == 0
    settings = json.loads((state / "settings.json").read_text())
    manifest = json.loads((state / "pilot.json").read_text())
    assert settings[option] is True and manifest[option] is True
    expected = _profile_with_options(
        "openai/gpt-6-luna", source_ids=True, wire_policy_version=2, **{option: True}
    )
    assert settings["extraction_profile"] == asdict(expected)
    before = (state / "pilot.json").read_bytes()
    monkeypatch.setattr(sys, "argv", ["pilot", "--resume", "--state", str(state)])
    assert pilot.main() == 0
    assert (state / "pilot.json").read_bytes() == before
    monkeypatch.setattr(sys, "argv", argv[:-1])
    with pytest.raises(ValueError, match="policy changed"):
        pilot.main()


@pytest.mark.parametrize("option", ["extraction_table_rows", "extraction_recall_prompt"])
@pytest.mark.parametrize(
    "value,source,atomic,accepted",
    [
        (True, True, False, True),
        (False, True, False, False),
        ("yes", True, False, False),
        (True, False, False, False),
        (True, True, True, False),
    ],
)
def test_runtime_rejects_invalid_recall_profile(tmp_path, option, value, source, atomic, accepted):
    from proofops_api.local_runtime import load_local_runtime

    from tests.integration.test_local_runtime_config import (
        _budget_limits,
        _parser_snapshot,
        _probe_extraction_profile,
        _write_json,
    )

    parser = _write_json(tmp_path / "parser.json", _parser_snapshot())
    settings = _write_json(
        tmp_path / "settings.json",
        {
            "build_root": str(tmp_path),
            "budget_limits": _budget_limits(),
            "extraction_profile": _probe_extraction_profile(),
            "extraction_limits": {"max_calls": 2, "max_output_tokens": 128},
            option: value,
            **({"extraction_source_ids": True} if source else {}),
            **({"extraction_atomic": True} if atomic else {}),
        },
    )
    env = {
        "LOCAL_PARSER_PROFILE_PATH": str(parser),
        "LOCAL_RUN_SETTINGS_PATH": str(settings),
        "LOCAL_EXTRACTION_MODE": "upstage_probe",
    }
    if accepted:
        assert load_local_runtime(env)["extraction_mode"] == "upstage_probe"
    else:
        with pytest.raises(ValueError, match="LOCAL_RUNTIME_CONFIG_INVALID"):
            load_local_runtime(env)


def test_unlocated_rows_and_conflicts_stay_excluded():
    text = "지표\t단위\t2024년\n온실가스 배출량\ttCO2e\t123"
    blocks = [
        SimpleNamespace(
            source_id=str(i),
            page_num=1,
            kind="table",
            quality=quality,
            winner=winner,
            bbox=None,
            normalized_text=text,
        )
        for i, (quality, winner) in enumerate([("unlocated", 0), ("conflicted", None)])
    ]
    assert not select_stable_paragraph_sources(
        SimpleNamespace(blocks=blocks),
        SimpleNamespace(mode="declared_subset", selected_pages=(1,)),
        8,
        extraction_table_rows=True,
    )


def test_resolved_cell_axes_are_parent_only_and_same_table(tmp_path):
    from tests.acceptance.test_preliminary_table_sources import table_corpus

    graph, claim, *_ = table_corpus(verified_axes=False)
    cell = next(b for b in graph.blocks if b.kind == "table_cell" and b.normalized_text == "900")
    p = {
        "tenant_id": graph.tenant_id,
        "document_version_id": graph.document_version_id,
        "parse_manifest_id": graph.parse_manifest_id,
        "source_sha256": graph.source_sha256,
        "untrusted_document_data": {
            "source_id": cell.source_id,
            "page_num": cell.page_num,
            "kind": cell.kind,
            "text": cell.normalized_text,
        },
    }
    probe = Probe()
    ex = UpstageClaimExtractor(
        probe,
        tmp_path,
        extraction_source_ids=True,
        extraction_context=True,
        extraction_table_context=True,
        extraction_table_rows=True,
    )
    result = ex.extract(p, context_graph=graph)
    assert result["spans"][0]["quote"] == "900"
    request = json.loads(next(tmp_path.glob("*/request.json")).read_text())
    parents = json.loads(request["user_json"])["untrusted_document_data"]["source_sentences"][0][
        "parent_context"
    ]
    text = " ".join(b["text"] for b in parents)
    assert "온실가스" in text and "2025" in text and "tCO2e" in text
    assert "2024" not in text and "용수" not in text and "4,800" not in text
    assert all("sentence_id" not in b for b in parents)


def test_first_data_row_cannot_be_used_as_another_rows_header():
    text = "온실가스 감축 목표\t2030년\t40%\n에너지 감축\t10%"
    rows = row_candidates(text, kind="table")
    assert text[rows[0].start : rows[0].end] == "온실가스 감축 목표\t2030년\t40%"
    assert all(r.header_start is None for r in rows)
    rows = row_candidates("온실가스 배출 지표\t2024년\t100 tCO2e\n123", kind="table")
    assert len(rows) == 1 and rows[0].header_start is None
