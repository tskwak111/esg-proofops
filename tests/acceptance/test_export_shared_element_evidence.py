"""F10: lossless shared search records, hostile references, and bounded renderers."""

import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from proofops.application.element_evidence_encoding import (
    ELEMENT_EVIDENCE_INLINE,
    ELEMENT_EVIDENCE_V1,
    encode_element_evidence,
    iter_element_evidence,
)
from proofops.application.exports import MAX_EXPORT_BYTES, ExportRejected, build_export
from proofops.application.reporting import build_report_model, render_report
from proofops.domain.provenance import canonical_hash
from proofops.domain.rulepacks import canonical_json
from proofops_agent.extraction import SyntheticClaimExtractor

from tests.acceptance.test_exports import archive, create, exports

SCOPE = {
    "tenant_id": "tenant-a",
    "run_id": "run-a",
    "document_version_id": "doc-a",
    "parse_manifest_id": "parse-a",
    "source_sha256": "a" * 64,
}


def evidence(quote="원문\n😀\u0007", count=3):
    item = {"page_num": 207, "char_start": 7, "char_end": 15, "quote": quote}
    candidate = item | {"citation_verified": False, "rejection_reason": "unreviewed"}
    search = {
        "hits": [item] * count,
        "native_candidates": [candidate] * count,
        "profile_sha256": "b" * 64,
        "document_search_sha256": "c" * 64,
        "absence_admissible": False,
        "truncated": False,
        "coverage": {"searched_pages": [1, 207], "missing_pages": [], "unreadable_pages": [2]},
        "terms": ["원문"],
    }
    return [
        {
            "element_id": "G1",
            "evidence_status": "undetermined",
            "engine_state": "unknown",
            "evidence_refs": [],
            "candidate_refs": [],
            "search": search,
        }
    ]


def encoded_manifest():
    manifest = SCOPE | {
        "claim_revision_refs": [],
        "element_evidence_encoding": ELEMENT_EVIDENCE_V1,
        "element_evidence_lists": {},
        "element_evidence_quotes": {},
        "element_evidence_records": {},
    }
    originals, records = {}, {}
    for index in range(3):
        claim_id = f"claim-{index}"
        record = SCOPE | {
            "claim_id": claim_id,
            "tag_revision": index,
            "decision_revision": 0,
            "element_evidence": evidence(),
        }
        originals[claim_id] = record["element_evidence"]
        manifest["claim_revision_refs"].append(
            {k: record[k] for k in ("claim_id", "tag_revision", "decision_revision")}
        )
        records[claim_id] = encode_element_evidence(record, manifest)
    return manifest, records, originals


def test_canonical_round_trip_preserves_every_field_order_duplicate_and_scope():
    manifest, records, originals = encoded_manifest()
    assert len(manifest["element_evidence_lists"]) == 2
    assert len(manifest["element_evidence_quotes"]) == 1
    assert canonical_json(dict(iter_element_evidence(manifest, records))) == canonical_json(
        originals
    )
    assert MAX_EXPORT_BYTES == 33_554_432
    for record in records.values():
        assert "hits" not in record["element_evidence"][0]["search"]
    # Envelopes cannot consume coincidentally named original data.
    raw = SCOPE | {
        "claim_id": "claim-0",
        "tag_revision": 0,
        "decision_revision": 0,
        "element_evidence": evidence(),
    }
    raw["element_evidence"][0]["search"]["__shared_search__"] = {"user": "data"}
    raw["element_evidence"][0]["search"]["hits"][0]["__shared_quote__"] = None
    manifest["element_evidence_lists"].clear()
    manifest["element_evidence_quotes"].clear()
    manifest["element_evidence_records"].clear()
    manifest["claim_revision_refs"] = manifest["claim_revision_refs"][:1]
    compact = encode_element_evidence(raw, manifest)
    assert (
        dict(iter_element_evidence(manifest, {"claim-0": compact}))["claim-0"]
        == raw["element_evidence"]
    )


@pytest.mark.parametrize(
    "damage",
    [
        "missing_list",
        "missing_quote",
        "list_hash",
        "quote_hash",
        "list_scope",
        "quote_scope",
        "run",
        "source",
        "revision",
        "claim",
        "search_profile",
        "document_search",
        "bad_ref",
        "inline",
        "extra_list",
        "extra_quote",
        "extra_record",
        "unsupported",
        "missing_encoding",
    ],
)
def test_forged_references_and_scope_fail_closed(damage):
    manifest, records, _ = encoded_manifest()
    record = records["claim-0"]
    search = record["element_evidence"][0]["search"]
    lists, quotes = manifest["element_evidence_lists"], manifest["element_evidence_quotes"]
    ld, qd = next(iter(lists)), next(iter(quotes))
    if damage == "missing_list":
        del lists[ld]
    elif damage == "missing_quote":
        del quotes[qd]
    elif damage == "list_hash":
        lists[ld]["value"][0]["page_num"] += 1
    elif damage == "quote_hash":
        quotes[qd]["value"] += "tamper"
    elif damage == "list_scope":
        lists[ld]["scope"]["tenant_id"] = "other"
    elif damage == "quote_scope":
        quotes[qd]["scope"]["document_version_id"] = "other"
    elif damage == "run":
        manifest["run_id"] = "other"
    elif damage == "source":
        record["source_sha256"] = "d" * 64
    elif damage == "revision":
        record["tag_revision"] += 1
    elif damage == "claim":
        record["claim_id"] = "claim-1"
    elif damage == "search_profile":
        search["profile_sha256"] = "d" * 64
    elif damage == "document_search":
        search["document_search_sha256"] = "d" * 64
    elif damage == "bad_ref":
        search["__shared_search__"]["refs"]["hits"] = "sha256:bad"
    elif damage == "inline":
        search["hits"] = []
    elif damage == "extra_list":
        lists["0" * 64] = deepcopy(lists[ld])
    elif damage == "extra_quote":
        quotes["0" * 64] = deepcopy(quotes[qd])
    elif damage == "extra_record":
        manifest["element_evidence_records"]["extra"] = {}
    elif damage == "unsupported":
        manifest["element_evidence_encoding"] = "future"
    else:
        del manifest["element_evidence_encoding"]
    with pytest.raises(ValueError):
        list(iter_element_evidence(manifest, records))


def test_legacy_inline_evidence_is_unchanged():
    raw = {"claim-0": {"element_evidence": evidence()}}
    raw["claim-0"]["element_evidence"][0]["search"]["__shared_search__"] = {"user": "data"}
    assert dict(iter_element_evidence({}, raw)) == {"claim-0": raw["claim-0"]["element_evidence"]}


def test_expansion_is_bounded_across_all_lists_in_one_claim(monkeypatch):
    import proofops.application.element_evidence_encoding as codec

    manifest, records, _ = encoded_manifest()
    # Each list fits, but their combined restored claim does not.
    digest = next(iter(manifest["element_evidence_lists"]))
    assert len(canonical_json(manifest["element_evidence_lists"][digest]["value"]).encode()) < 1000
    monkeypatch.setattr(codec, "MAX_EXPANDED_BYTES", 1000)
    with pytest.raises(ValueError, match="expansion exceeds"):
        list(iter_element_evidence(manifest, records))


def test_inline_quotes_are_refused_even_with_a_matching_restored_hash():
    manifest, records, _ = encoded_manifest()
    search = records["claim-0"]["element_evidence"][0]["search"]
    reference = search["__shared_search__"]["refs"]["hits"]
    table = manifest["element_evidence_lists"]
    entry = deepcopy(table.pop(reference[7:]))
    quote_digest = entry["value"][0]["__shared_quote__"]["refs"].pop("quote")[7:]
    entry["value"][0]["quote"] = manifest["element_evidence_quotes"][quote_digest]["value"]
    table[reference[7:]] = entry
    with pytest.raises(ValueError, match="inline quote"):
        list(iter_element_evidence(manifest, records))


def test_http_shared_capture_and_all_renderers_keep_lists_in_manifest(tmp_path, monkeypatch):
    extract = SyntheticClaimExtractor.extract

    def two_claims(self, packet):
        original = extract(self, packet)["spans"][0]
        split = original["quote"].index(" 1234") + original["char_start"]
        return {
            "spans": [
                original | {"char_end": split, "quote": original["quote"][:split]},
                original | {"char_start": split + 1, "quote": original["quote"][split + 1 :]},
            ]
        }

    monkeypatch.setattr(SyntheticClaimExtractor, "extract", two_claims)
    ws = exports(tmp_path, monkeypatch)
    # A repeated Unicode quote makes old rendering too large; new references fit.
    raw = evidence("공시 원문😀" * 20_000, count=20)
    monkeypatch.setattr(ws["runner"].claims, "missing_evidence", lambda *a, **k: deepcopy(raw))
    result = create(ws)
    assert result.status_code == 202, result.text
    bundle, _, _ = archive(ws, result.json())
    manifest = json.loads(bundle.read("manifest.json"))
    frozen = ws["export_store"].frozen(ws["actor"].tenant_id, result.json()["export_id"])
    unsupported = deepcopy(frozen)
    unsupported["manifest"]["element_evidence_encoding"] = "future"
    with pytest.raises(ExportRejected, match="EXPORT_INTEGRITY_FAILED"):
        build_export(unsupported, ["json"])
    assert manifest["element_evidence_encoding"] == ELEMENT_EVIDENCE_V1
    assert len(canonical_json(frozen).encode()) < MAX_EXPORT_BYTES
    restored = dict(iter_element_evidence(manifest, frozen["decisions"]))
    assert all(canonical_hash(item) == canonical_hash(raw) for item in restored.values())
    for fmt in ("json", "csv", "html"):
        content = bundle.read(f"report.{fmt}")
        assert len(content) < 100_000
        assert b"manifest.json" in content
    legacy = deepcopy(frozen)
    for claim_id, value in restored.items():
        legacy["decisions"][claim_id]["element_evidence"] = value
    for key in list(legacy["manifest"]):
        if key.startswith("element_evidence_"):
            del legacy["manifest"][key]
    model = build_report_model(legacy["manifest"], legacy["decisions"])
    assert all(c["element_evidence"] == raw for c in model["claims"])
    assert len(render_report(model, "json")) > MAX_EXPORT_BYTES
    with pytest.raises(ValueError, match="EXPORT_SIZE_LIMIT"):
        build_export(legacy, ["json"])


def test_writer_rollback_pins_requests_and_keeps_shared_frozen_reader(tmp_path, monkeypatch):
    ws = exports(tmp_path, monkeypatch)
    store, actor, run = ws["export_store"], ws["actor"], ws["run"]
    body = {"formats": ["json"], "allow_partial": True}
    first = store.reserve(actor, run, body, "shared-reservation", now=ws["now"][0])
    store.element_evidence_encoding = ELEMENT_EVIDENCE_INLINE
    snapshot = store.capture(actor.tenant_id, first)
    assert snapshot["manifest"]["element_evidence_encoding"] == ELEMENT_EVIDENCE_V1
    assert store.freeze(actor.tenant_id, first, snapshot)
    assert build_export(store.frozen(actor.tenant_id, first), ["json"])[0]
    assert store.reserve(actor, run, body, "shared-reservation", now=ws["now"][0]) == first
    second = store.reserve(actor, run, body, "inline-reservation", now=ws["now"][0])
    assert "element_evidence_encoding" not in store.capture(actor.tenant_id, second)["manifest"]
    # A pre-F10 queued reservation must use its original inline writer even
    # when the current process defaults to shared encoding.
    with store.jobs._transaction() as db:
        old_state = store._state(db, actor.tenant_id, second)
        del old_state["element_evidence_encoding"]
        store.jobs._put(db, actor.tenant_id, run, "export_state", second, old_state)
    store.element_evidence_encoding = ELEMENT_EVIDENCE_V1
    assert "element_evidence_encoding" not in store.capture(actor.tenant_id, second)["manifest"]


@pytest.mark.parametrize("encoding", [ELEMENT_EVIDENCE_V1, ELEMENT_EVIDENCE_INLINE])
def test_expansion_limit_persists_failure_without_recapture(tmp_path, monkeypatch, encoding):
    ws = exports(tmp_path, monkeypatch)
    store, actor = ws["export_store"], ws["actor"]
    store.element_evidence_encoding = encoding
    raw = evidence("x" * 1_000_000, count=17)
    assert len(canonical_json(raw).encode()) > MAX_EXPORT_BYTES
    monkeypatch.setattr(ws["runner"].claims, "missing_evidence", lambda *a, **k: deepcopy(raw))
    capture = Mock(wraps=store.capture)
    monkeypatch.setattr(store, "capture", capture)
    export_id = store.reserve(
        actor,
        ws["run"],
        {"formats": ["json"], "allow_partial": True},
        "f10b-expansion-state",
        now=ws["now"][0],
    )
    try:
        first = ws["exports"].get(actor, export_id, now=ws["now"][0])
        assert first["state"] == "failed"
        assert store.state(actor.tenant_id, export_id)["errors"] == ["EXPORT_SIZE_LIMIT"]
        second = ws["exports"].get(actor, export_id, now=ws["now"][0] + 10)
        assert second == first
        assert capture.call_count == 1
        assert store.frozen(actor.tenant_id, export_id) is None
        with store.jobs._transaction() as db:
            assert not store.jobs._all(db, actor.tenant_id, ws["run"], "export_artifact")
    finally:
        ws["http"].close()


@pytest.mark.parametrize("encoding", [ELEMENT_EVIDENCE_V1, ELEMENT_EVIDENCE_INLINE])
def test_http_expansion_limit_keeps_size_code_and_idempotent_failure(
    tmp_path, monkeypatch, encoding
):
    ws = exports(tmp_path, monkeypatch)
    store, actor = ws["export_store"], ws["actor"]
    store.element_evidence_encoding = encoding
    raw = evidence("x" * 1_000_000, count=17)
    monkeypatch.setattr(ws["runner"].claims, "missing_evidence", lambda *a, **k: deepcopy(raw))
    capture = Mock(wraps=store.capture)
    monkeypatch.setattr(store, "capture", capture)
    try:
        for _ in range(2):
            response = create(ws, formats=["json"])
            assert response.status_code == 409, response.text
            assert response.json()["error"]["code"] == "EXPORT_SIZE_LIMIT"
            ws["now"][0] += 10
        with store.jobs._transaction() as db:
            states = store.jobs._all(db, actor.tenant_id, ws["run"], "export_state")
        assert len(states) == 1
        export_id = states[0]["response"]["export_id"]
        metadata = ws["http"].get(f"/v1/exports/{export_id}")
        assert metadata.status_code == 200
        assert metadata.json()["state"] == "failed"
        assert store.state(actor.tenant_id, export_id)["errors"] == ["EXPORT_SIZE_LIMIT"]
        assert capture.call_count == 1
        assert store.frozen(actor.tenant_id, export_id) is None
    finally:
        ws["http"].close()


@pytest.mark.parametrize("damage", ["quote_hash", "list_scope"])
def test_http_shared_integrity_failure_keeps_separate_error_code(tmp_path, monkeypatch, damage):
    ws = exports(tmp_path, monkeypatch)
    store = ws["export_store"]
    monkeypatch.setattr(
        ws["runner"].claims, "missing_evidence", lambda *a, **k: deepcopy(evidence())
    )
    capture = store.capture

    def damaged_capture(*args):
        captured = capture(*args)
        manifest = captured["manifest"]
        if damage == "quote_hash":
            next(iter(manifest["element_evidence_quotes"].values()))["value"] += "tamper"
        else:
            next(iter(manifest["element_evidence_lists"].values()))["scope"]["tenant_id"] = "other"
        return captured

    monkeypatch.setattr(store, "capture", damaged_capture)
    try:
        response = create(ws, formats=["json"])
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "EXPORT_INTEGRITY_FAILED"
        with store.jobs._transaction() as db:
            assert not store.jobs._all(db, ws["actor"].tenant_id, ws["run"], "export_snapshot")
    finally:
        ws["http"].close()
