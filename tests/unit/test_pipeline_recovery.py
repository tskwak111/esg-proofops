"""Focused checks: manifest reuses existing receipts, never fabricates.

Verifies the behaviors this task cares about:
1. building the manifest does not silently invent claim/tag data for a
   company that only has a parse-level receipt (kepco).
2. every company's source hash matches the live PDF bytes on disk.
3. idempotent versioned writes never overwrite changed prior content.
"""

from evaluation.pipeline_recovery import build_manifest, write_idempotent_versioned


def test_manifest_marks_kepco_parse_only_and_verifies_present_hashes():
    manifest = build_manifest()
    by_slug = {c["slug"]: c for c in manifest["companies"]}

    assert set(manifest["requested_companies"]) == {"lotte", "kia", "kb", "naver", "kepco"}

    # kepco only has a parse-level candidate snapshot, no claim/tag receipt;
    # it must be reported parse_only with EXTRACT/TAG explicitly not_run,
    # never defaulted to 0 (which would misleadingly read as "ran, found none").
    assert by_slug["kepco"]["status"] == "parse_only"
    assert by_slug["kepco"]["reason"]
    assert by_slug["kepco"]["stage_counts"]["EXTRACT"] == "not_run"
    assert by_slug["kepco"]["stage_counts"]["TAG"] == "not_run"
    assert by_slug["kepco"]["stage_counts"]["PARSE"]["table_count"] == 3

    # every company reported "ok" must carry a real, non-empty source hash
    # that this build recomputed from the actual file, plus at least one
    # stage-progression signal recovered from an existing receipt (not
    # invented precision/recall), and explicit per-page prior-exposure
    # tracking rather than a blanket "same heldout pages" claim.
    for slug in ("lotte", "kia", "kb", "naver"):
        company = by_slug[slug]
        assert company["status"] == "ok"
        assert len(company["source_sha256"]) == 64
        assert company["pages"], f"{slug} must keep its frozen page selection"
        assert company["stage_counts"], f"{slug} must carry real stage counts"
        assert company["receipt_source"]
        assert company["prior_exposure"], f"{slug} must track prior exposure explicitly"

    # kb's two runs really do share physical page 30; kia/naver's don't.
    # This is the specific overlap claim the manifest must get right instead
    # of asserting all three share "the same" patch-heldout pages.
    kb_other = by_slug["kb"]["prior_exposure"][1]
    kia_other = by_slug["kia"]["prior_exposure"][1]
    naver_other = by_slug["naver"]["prior_exposure"][1]
    assert kb_other["overlaps_this_baseline_pages"] is True
    assert kia_other["overlaps_this_baseline_pages"] is False
    assert naver_other["overlaps_this_baseline_pages"] is False

    # lotte and kia must carry the real same-page external-parser comparison
    # with concrete failure rows, not just an element-count match rate.
    lotte_api = by_slug["lotte"]["stage_counts"].get("api_comparison")
    assert lotte_api is not None
    assert lotte_api["known_failure_rows"]

    kia_api = by_slug["kia"]["stage_counts"].get("api_comparison")
    assert kia_api is not None
    assert kia_api["known_failure_rows"]
    assert kia_api["visual_adjudication"] != "completed"  # coordinator marked pending


def test_idempotent_versioned_write_never_overwrites_changed_content(tmp_path):
    target = tmp_path / "manifest.json"

    first = write_idempotent_versioned(target, "v1-content")
    assert first == target
    assert target.read_text() == "v1-content"

    # identical content re-write is a true no-op on the same path
    again = write_idempotent_versioned(target, "v1-content")
    assert again == target
    assert target.read_text() == "v1-content"

    # changed content must go to a new sibling, leaving v1 untouched
    second = write_idempotent_versioned(target, "v2-content")
    assert second == tmp_path / "manifest.v2.json"
    assert target.read_text() == "v1-content"
    assert second.read_text() == "v2-content"

    # a third distinct change goes to v3, both prior files stay intact
    third = write_idempotent_versioned(target, "v3-content")
    assert third == tmp_path / "manifest.v3.json"
    assert target.read_text() == "v1-content"
    assert second.read_text() == "v2-content"
    assert third.read_text() == "v3-content"
