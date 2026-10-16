"""Split diagnostic children retain exact source identity without parent credit."""

import pytest

from evaluation.i25_replay import refine_with_provenance


def test_children_keep_offsets_but_never_parent_verification():
    quote = (
        "SK하이닉스는 2050년까지 넷 제로 및 RE100 달성을 장기 목표로 설정하고 "
        "이를 이행하기 위해 2030년까지 Scope 1&2 온실가스 배출량 2020년 수준 유지"
    )
    ref = dict(
        quote=quote,
        char_start=17,
        char_end=17 + len(quote),
        document_version_id="version",
        verification_state="verified",
    )
    parent = dict(
        id="parent",
        company="SK하이닉스",
        page=19,
        quote=quote,
        source_verified=True,
        source_refs=[ref],
    )
    children = refine_with_provenance([parent])
    assert len(children) == 3
    for child in children:
        source = child["source_refs"][0]
        assert quote[source["char_start"] - 17 : source["char_end"] - 17] == child["quote"]
        assert source["document_version_id"] == "version"
        assert source["verification_state"] == "unverified"
        assert child["source_verified"] is False
        assert child["parent_source_refs"] == [ref]
    assert ref["verification_state"] == "verified"
    with pytest.raises(ValueError, match="CHILD_SOURCE_NOT_EXACT"):
        refine_with_provenance([parent | dict(source_refs=[ref | dict(quote="other")])])
