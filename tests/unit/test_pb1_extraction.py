from proofops.application.ingest.pb1_tables import observations
from proofops_agent.upstage_extraction import join_selected_linewraps


def test_latest_year_one_claim_per_row_comparisons_retained():
    text = "지표명\t단위\t2022\t2023\t2024\n직접 배출량(Scope 1)\t천tCO2eq\t379.9\t353.9\t386.3"
    rows = observations(text)
    assert len(rows) == 1
    row = rows[0]
    assert row["year"] == "2024"
    assert row["value"] == "386.3"
    assert [v["year"] for v in row["comparisons"]] == ["2022", "2023"]
    assert text[row["start"] : row["end"]] == row["quote"]
    assert row["value_column"] == 4


def test_header_and_footnote_never_claims():
    assert observations("온실가스\t단위\t2024\n지표명\t천tCO2eq\t2024") == []
    assert observations("온실가스\t단위\t2024\n1) 산정방법\t천tCO2eq\t20") == []
    assert observations("온실가스\t단위\t2024\n총 배출량\t천tCO2eq\t1,178.51)") == []


def test_no_year_guess_or_cross_row_unit():
    assert observations("지표명\t단위\n온실가스\ttCO2eq\n폐기물\t15") == []
    assert (
        observations("지표명\t단위\t2024\n온실가스\ttCO2eq\t15\n인원\t명\t20")[0]["value"] == "15"
    )


def test_fragment_guard_pb1_joins_or_excludes():
    def span(text, a, b):
        return dict(
            char_start=a, char_end=b, quote=text[a:b], kind="claim", reason=None, topic_ids=[]
        )

    text = "환경 정보를 보고서를\n통해 공개하고 있습니다."
    cut = text.index("\n")
    assert (
        join_selected_linewraps(
            [span(text, 0, cut), span(text, cut + 1, len(text))], text, fragment_guard="pb1-v1"
        )[0]["quote"]
        == text
    )
    assert (
        join_selected_linewraps([span(text, cut + 1, len(text))], text, fragment_guard="pb1-v1")
        == []
    )
    text = "환경 정책을 수립하고"
    assert join_selected_linewraps([span(text, 0, len(text))], text, fragment_guard="pb1-v1") == []


def test_table_technology_footnote_is_context_without_erasing_main_bullet(tmp_path):
    from proofops_agent.upstage_extraction import UpstageClaimExtractor

    class Probe:
        model = "solar-pro3"

        def complete(self, *a, **kw):
            raise AssertionError("offline response replay must not dispatch")

    text = "* 적용기술: 2.3MW 태양광 설비 설치로 에너지를 절감하는 기술\t방법론"
    packet = dict(untrusted_document_data=dict(kind="table", source_id="source", text=text))
    old = UpstageClaimExtractor(
        Probe(),
        tmp_path / "old",
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_pb1=True,
    )
    guarded = UpstageClaimExtractor(
        Probe(),
        tmp_path / "new",
        extraction_source_ids=True,
        extraction_table_rows=True,
        extraction_pb1=True,
        extraction_pb1_context_guard=True,
    )
    entries = old._row_entries(packet, text, [])
    assert len(entries) == 1
    response = dict(sentence_ids=[entries[0]["sentence_id"]])
    spans, _ = old._resolve_payload(response, text, "source", packet=packet)
    assert len(spans) == 1
    spans, diagnostics = guarded._resolve_payload(response, text, "source", packet=packet)
    assert spans == () and len(diagnostics["table_context_excluded"]) == 1
    assert old.profile.rule_sha256 != guarded.profile.rule_sha256
    from proofops.application.ingest.pb1_fragments import table_context_row

    assert not table_context_row("* 당사는 2025년 태양광 설비를 설치하였다.")
