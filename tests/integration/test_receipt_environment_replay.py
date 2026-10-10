from copy import deepcopy
from dataclasses import asdict

import pytest
from proofops.adapters.local import merged_table_verification as verifier
from proofops.adapters.local.receipt_environment_compat import (
    PROFILE,
    receipt_read_metadata,
    replay_receipt,
)
from proofops.domain.provenance import canonical_hash

from tests.integration.test_merged_table_verification import TENANT, fixture, ocr


def test_real_table_reader_os_compatibility(monkeypatch):
    source, graph = fixture()
    original_graph = canonical_hash(asdict(graph))
    reader_os = "old"

    def rendered(page, box, **kwargs):
        return dict(
            ocr(page, box, **kwargs),
            reader="Apple Vision",
            revision=3,
            os=reader_os,
            image_sha256="pixels",
        )

    monkeypatch.setattr(verifier, "_rendered_text", rendered)
    verifier._attest_json.cache_clear()
    try:
        saved = verifier.attest_tables(graph, source, tenant_id=TENANT)
        original = deepcopy(saved)
        strict = verifier.replay_tables(saved, graph, source, tenant_id=TENANT)
        reader_os = "new"
        verifier._attest_json.cache_clear()
        with pytest.raises(ValueError, match="table attestation mismatch"):
            verifier.replay_tables(saved, graph, source, tenant_id=TENANT)
        checked = replay_receipt(
            verifier.replay_tables, saved, graph, source, tenant_id=TENANT, profile=PROFILE
        )
        assert asdict(checked) == asdict(strict)
        meta = receipt_read_metadata(saved, profile=PROFILE)
        assert meta["environment_drift"]
        assert saved == original
        assert original_graph == canonical_hash(asdict(graph))
        # Explicit profile never modifies the shared module's strict function.
        with pytest.raises(ValueError, match="table attestation mismatch"):
            verifier.replay_tables(saved, graph, source, tenant_id=TENANT)
    finally:
        verifier._attest_json.cache_clear()


@pytest.mark.parametrize("layer", ["base", "render", "bullet", "typography"])
def test_claim_layers_os_drift_preserve_historical_span_identity(monkeypatch, layer):
    from proofops.adapters.local import claim_source_verification as base
    from proofops.adapters.local import claim_span_bullet_alignment as bullet
    from proofops.adapters.local import claim_span_render_resolution as render
    from proofops.adapters.local import claim_span_typography as typography
    from proofops.adapters.local import selected_cell_table_verification as cell

    from tests.integration.test_batch_attestation_cache import discovery_for
    from tests.integration.test_claim_span_typography import RENDERED_TEXT, dot_inputs

    source, graph, ref = dot_inputs()
    discovery = discovery_for(graph, [ref])
    reader_os = "old"

    def reading(*args, **kwargs):
        return dict(
            status="read",
            text=RENDERED_TEXT,
            reader="Apple Vision",
            os=reader_os,
            revision=3,
            image_sha256="pixels",
            scale=11,
        )

    monkeypatch.setattr(base, "_rendered_text", reading)
    monkeypatch.setattr(cell, "_rendered_cell", reading)
    reader = dict(base=base, render=render, bullet=bullet, typography=typography)[layer]
    saved = reader.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    strict = reader.replay_claim_spans(saved, graph, source, discovery, tenant_id=TENANT)
    reader_os = "new"
    with pytest.raises(ValueError):
        reader.replay_claim_spans(saved, graph, source, discovery, tenant_id=TENANT)
    checked = replay_receipt(
        reader.replay_claim_spans,
        saved,
        graph,
        source,
        discovery,
        tenant_id=TENANT,
        profile=PROFILE,
    )
    assert canonical_hash(asdict(checked[0])) == canonical_hash(asdict(strict[0]))
    assert asdict(checked[1]) == asdict(strict[1])
    assert receipt_read_metadata(saved, profile=PROFILE)["environment_drift"]
    tampered = deepcopy(saved)
    tampered["base_attestation_sha256" if layer != "base" else "artifact_sha256"] = "bad"
    with pytest.raises(ValueError):
        replay_receipt(
            reader.replay_claim_spans,
            tampered,
            graph,
            source,
            discovery,
            tenant_id=TENANT,
            profile=PROFILE,
        )


def test_native_cache_profile_isolation(monkeypatch):
    from proofops.adapters.local import native_replay_cache as cache
    from proofops.adapters.local import source_verification as reader

    from tests.integration.test_claim_source_verification import inputs

    source, graph, _ref = inputs()
    reader_os = "old"

    def reading(*args, **kwargs):
        return dict(
            status="read",
            text=graph.blocks[0].raw_text,
            reader="Apple Vision",
            os=reader_os,
            image_sha256="pixels",
            revision=3,
        )

    monkeypatch.setattr(reader, "_rendered_text", reading)
    cache._replays.clear()
    saved = reader.attest_native_sources(graph, source, tenant_id=TENANT)
    reader_os = "new"
    monkeypatch.setenv("PROOFOPS_RECEIPT_READ_PROFILE", PROFILE)
    result = cache.replay_cached(saved, graph, source, tenant_id=TENANT)
    assert result.blocks[0].quality == "verified"
    assert receipt_read_metadata(saved)["environment_drift"]
    assert asdict(cache.replay_cached(saved, graph, source, tenant_id=TENANT)) == asdict(result)
    monkeypatch.setenv("PROOFOPS_RECEIPT_READ_PROFILE", "strict-v1")
    with pytest.raises(ValueError, match="native attestation mismatch"):
        cache.replay_cached(saved, graph, source, tenant_id=TENANT)
    cache._replays.clear()


def test_frozen_native_reader_profile_preserves_bundle_bytes(monkeypatch):
    from proofops.adapters.local import frozen_native_replay as frozen

    from tests.integration.test_claim_source_verification import inputs

    source, graph, _ref = inputs()
    bundle = frozen.find_pinned_verifier(
        "cf201df19cfa9770a7f66ad67d1906388de7417863d7421ae84093938df0f8f6"
    )
    reader = frozen._load_frozen_verifier(bundle)
    reader_os = "old"

    def reading(*args, **kwargs):
        return dict(
            status="read",
            text=graph.blocks[0].raw_text,
            reader="Apple Vision",
            os=reader_os,
            image_sha256="pixels",
            revision=3,
        )

    monkeypatch.setattr(reader, "_rendered_text", reading)
    monkeypatch.setattr(frozen, "_load_frozen_verifier", lambda _bundle: reader)
    saved = reader.attest_native_sources(graph, source, tenant_id=TENANT)
    reader_os = "new"
    monkeypatch.setenv("PROOFOPS_RECEIPT_READ_PROFILE", PROFILE)
    result = frozen.replay_native_sources_frozen(bundle, saved, graph, source, tenant_id=TENANT)
    assert result.blocks[0].quality == "verified"
    assert frozen._verify_bundle_bytes(bundle).is_dir()
    monkeypatch.setenv("PROOFOPS_RECEIPT_READ_PROFILE", "strict-v1")
    with pytest.raises(ValueError):
        frozen.replay_native_sources_frozen(bundle, saved, graph, source, tenant_id=TENANT)


@pytest.mark.parametrize("requested", [False, True])
def test_selected_and_requested_cell_os_compatibility(monkeypatch, requested):
    from proofops.adapters.local import requested_table_verification as subset
    from proofops.adapters.local import selected_cell_table_verification as selected

    from tests.integration.test_selected_cell_table_verification import (
        LAYOUT_B_CELLS,
        LAYOUT_B_WORDS,
        grid_pdf,
        table_graph,
    )

    source = grid_pdf(LAYOUT_B_WORDS)
    graph = table_graph(source, LAYOUT_B_CELLS)
    reader_os = "old"

    def reading(page, box):
        return dict(
            status="read",
            text=page.crop(box).extract_text() or "",
            reader="Apple Vision",
            os=reader_os,
            image_sha256="pixels",
            revision=3,
            scale=3,
        )

    monkeypatch.setattr(selected, "_rendered_cell", reading)
    selected._attest_json.cache_clear()
    subset._attest_json.cache_clear()
    reader = subset if requested else selected
    ids = [b.source_id for b in graph.blocks if b.raw_text == "155,446"]
    args = (graph, source, ids) if requested else (graph, source)
    try:
        saved = reader.attest_tables(*args, tenant_id=TENANT)
        strict = reader.replay_tables(saved, *args, tenant_id=TENANT)
        reader_os = "new"
        reader._attest_json.cache_clear()
        checked = replay_receipt(
            reader.replay_tables, saved, *args, tenant_id=TENANT, profile=PROFILE
        )
        assert asdict(checked) == asdict(strict)
        assert receipt_read_metadata(saved, profile=PROFILE)["environment_drift"]
    finally:
        selected._attest_json.cache_clear()
        subset._attest_json.cache_clear()


def test_live_raster_composition_revalidates_native_with_profile(tmp_path, monkeypatch):
    from proofops.adapters.local import source_verification as reader
    from proofops.adapters.local.raster_checkpoint import replay_raster_records
    from proofops.adapters.local.receipt_environment_compat import replay_raster_with_profile

    from tests.integration.test_raster_request_authorization import setup_request

    service, _, lease, graph, _, snapshot = setup_request(tmp_path, monkeypatch)
    reader_os = "old"

    def reading(*a, **kw):
        return dict(
            status="read",
            text="unresolved OCR",
            reader="Apple Vision",
            os=reader_os,
            image_sha256="pixels",
            revision=3,
        )

    monkeypatch.setattr(reader, "_rendered_text", reading)
    source = service.uploads.read_original(lease.message.tenant_id, graph.document_version_id)
    saved = reader.attest_native_sources(
        graph, source, tenant_id=graph.tenant_id, geometry_mode="glyph"
    )
    args = (snapshot, lease.message, saved, graph, source, (), {})
    strict = replay_raster_records(*args)
    reader_os = "new"
    with pytest.raises(ValueError):
        replay_raster_records(*args)
    monkeypatch.setenv("PROOFOPS_RECEIPT_READ_PROFILE", PROFILE)
    checked = replay_raster_with_profile(replay_raster_records, *args)
    assert asdict(checked[0]) == asdict(strict[0])
    assert checked[1:] == strict[1:]
    assert receipt_read_metadata(saved)["environment_drift"]


def test_context_cell_header_replay_checks_both_receipts(monkeypatch):
    from proofops.adapters.local import claim_source_verification as base
    from proofops.adapters.local import reviewed_context_verification as context
    from proofops.adapters.local import selected_cell_table_verification as selected

    from tests.integration.test_selected_cell_table_verification import (
        LAYOUT_B_CELLS,
        LAYOUT_B_WORDS,
        grid_pdf,
        table_graph,
    )

    source = grid_pdf(LAYOUT_B_WORDS)
    graph = table_graph(source, LAYOUT_B_CELLS)
    reader_os = "old"

    def reading(page, box, **kw):
        return dict(
            status="read",
            text=page.crop(box).extract_text() or "",
            reader="Apple Vision",
            os=reader_os,
            image_sha256="pixels",
            revision=3,
            scale=3,
        )

    monkeypatch.setattr(selected, "_rendered_cell", reading)
    monkeypatch.setattr(base, "_rendered_text", reading)
    selected._attest_json.cache_clear()
    context._attest_json.cache_clear()
    ids = [b.source_id for b in graph.blocks if b.raw_text == "Total"]
    try:
        header = selected.attest_tables(graph, source, tenant_id=TENANT)
        saved = context.attest_context_cells(
            graph, source, ids, tenant_id=TENANT, header_receipt=header
        )
        strict = context.replay_context_cells(
            saved, graph, source, ids, tenant_id=TENANT, header_receipt=header
        )
        reader_os = "new"
        selected._attest_json.cache_clear()
        context._attest_json.cache_clear()
        with pytest.raises(ValueError, match="SELECTED_CELL_RECEIPT_MISMATCH"):
            context.replay_context_cells(
                saved, graph, source, ids, tenant_id=TENANT, header_receipt=header
            )
        checked = replay_receipt(
            context.replay_context_cells,
            saved,
            graph,
            source,
            ids,
            tenant_id=TENANT,
            header_receipt=header,
            profile=PROFILE,
        )
        assert asdict(checked) == asdict(strict)
        assert receipt_read_metadata(header, profile=PROFILE)["environment_drift"]
        assert receipt_read_metadata(saved, profile=PROFILE)["read_profile"] == PROFILE
    finally:
        selected._attest_json.cache_clear()
        context._attest_json.cache_clear()


def test_fresh_wrapper_proof_retains_its_canonical_integrity(monkeypatch):
    from proofops.adapters.local import claim_source_verification as base
    from proofops.adapters.local import claim_span_render_resolution as wrapper
    from proofops.adapters.local import selected_cell_table_verification as cell

    from tests.integration.test_claim_span_typography import RENDERED_TEXT, dot_inputs

    source, graph, ref = dot_inputs()
    reader_os = "old"

    def reading(*a, **kw):
        return dict(
            status="read",
            text=RENDERED_TEXT,
            reader="Apple Vision",
            os=reader_os,
            image_sha256="pixels",
            revision=3,
            scale=11,
        )

    monkeypatch.setattr(base, "_rendered_text", reading)
    monkeypatch.setattr(cell, "_rendered_cell", reading)
    saved = wrapper.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    reader_os = "new"
    _, proof = replay_receipt(
        wrapper.replay_render_resolution, saved, graph, source, tenant_id=TENANT, profile=PROFILE
    )
    assert proof["artifact_sha256"] == canonical_hash(
        {k: v for k, v in proof.items() if k != "artifact_sha256"}
    )
    assert receipt_read_metadata(saved, profile=PROFILE)["environment_drift"]


@pytest.fixture
def os_drift_claim(monkeypatch):
    from proofops.adapters.local import claim_source_verification as base
    from proofops.adapters.local import native_replay_cache as cache
    from proofops.adapters.local import receipt_environment_compat as compat
    from proofops.adapters.local import selected_cell_table_verification as cell

    from tests.integration.test_batch_attestation_cache import discovery_for
    from tests.integration.test_claim_span_typography import RENDERED_TEXT, dot_inputs

    source, graph, ref = dot_inputs()
    state = ["old"]

    def reading(*args, **kwargs):
        return dict(
            status="read",
            text=RENDERED_TEXT,
            reader="Apple Vision",
            os=state[0],
            revision=3,
            image_sha256="pixels",
            scale=11,
        )

    monkeypatch.setattr(base, "_rendered_text", reading)
    monkeypatch.setattr(cell, "_rendered_cell", reading)
    monkeypatch.setenv(compat.PROFILE_ENV, PROFILE)
    for entries in (cache._claim_replays, cache._claim_attestations, cache._claim_wrapper_receipts):
        entries.clear()
    yield source, graph, ref, discovery_for(graph, [ref]), state
    for entries in (cache._claim_replays, cache._claim_attestations, cache._claim_wrapper_receipts):
        entries.clear()
    compat._meta.clear()


def evict_read_metadata():
    from proofops.adapters.local import receipt_environment_compat as compat

    for index in range(256):
        compat.compare_receipts({"filler": index}, {"filler": index}, profile=PROFILE)


def test_compatible_read_cannot_publish_historical_os(os_drift_claim):
    from proofops.adapters.local import claim_source_verification as base
    from proofops.adapters.local import native_replay_cache as cache
    from proofops.adapters.local.claim_source_policies import attest_claims
    from proofops.domain.rulepacks import canonical_json

    source, graph, ref, discovery, state = os_drift_claim
    saved = base.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    saved_bytes = canonical_json(saved).encode()
    strict = base.replay_claim_spans(saved, graph, source, discovery, tenant_id=TENANT)
    state[0] = "new"
    result = cache.replay_claims_cached(
        reader=base,
        policy=base.claim_source_policy(),
        receipt=saved,
        graph=graph,
        source=source,
        discovery=discovery,
        tenant_id=TENANT,
    )
    assert [asdict(x) for x in result] == [asdict(x) for x in strict]
    for refs in ((ref,), (graph.blocks[0].source_ref(), ref, ref)):
        fresh = base.attest_claim_spans(graph, source, refs, tenant_id=TENANT)
        published = attest_claims(
            reader=base,
            graph=graph,
            source=source,
            refs=refs,
            tenant_id=TENANT,
            cache=True,
        )
        assert canonical_json(published).encode() == canonical_json(fresh).encode()
    assert canonical_json(saved).encode() == saved_bytes


def test_stale_reading_digest_is_rejected_before_equality_shortcut(os_drift_claim):
    from proofops.adapters.local import claim_source_verification as base

    source, graph, ref, discovery, state = os_drift_claim
    current = base.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    saved = deepcopy(current)
    for reading in saved["readings"].values():
        reading["rendered"]["os"] = "older OS"
    saved["artifact_sha256"] = canonical_hash(
        {key: value for key, value in saved.items() if key != "artifact_sha256"}
    )
    assert any(
        record["reading_sha256"] != canonical_hash(saved["readings"][record["ref"]["source_id"]])
        for record in saved["records"]
        if "reading_sha256" in record
    )
    with pytest.raises(ValueError, match="RECEIPT_DERIVED_HASH_MISMATCH"):
        replay_receipt(
            base.replay_claim_spans,
            saved,
            graph,
            source,
            discovery,
            tenant_id=TENANT,
            profile=PROFILE,
        )


def test_wrapper_cache_retains_drift_after_sidecar_eviction(os_drift_claim):
    from proofops.adapters.local import claim_span_bullet_alignment as bullet
    from proofops.adapters.local import native_replay_cache as cache

    source, graph, ref, discovery, state = os_drift_claim
    saved = bullet.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    state[0] = "new"
    kwargs = dict(
        reader=bullet,
        policy=bullet.claim_source_policy(),
        receipt=saved,
        graph=graph,
        source=source,
        discovery=discovery,
        tenant_id=TENANT,
    )
    first = cache.replay_claims_cached(**kwargs)
    metadata = receipt_read_metadata(saved)
    assert metadata["environment_drift"]
    assert not cache._claim_wrapper_receipts
    evict_read_metadata()
    assert receipt_read_metadata(saved) is None
    assert cache.replay_claims_cached(**kwargs) == first
    assert receipt_read_metadata(saved) == metadata


def test_raster_cache_retains_drift_after_sidecar_eviction(tmp_path, monkeypatch):
    from proofops.adapters.local import native_replay_cache as cache
    from proofops.adapters.local import receipt_environment_compat as compat
    from proofops.adapters.local import source_verification as reader

    from tests.integration.test_raster_request_authorization import setup_request

    service, _, lease, graph, _, snapshot = setup_request(tmp_path, monkeypatch)
    state = ["old"]

    def reading(*args, **kwargs):
        return dict(
            status="read",
            text="unresolved OCR",
            reader="Apple Vision",
            os=state[0],
            image_sha256="pixels",
            revision=3,
        )

    monkeypatch.setattr(reader, "_rendered_text", reading)
    source = service.uploads.read_original(lease.message.tenant_id, graph.document_version_id)
    saved = reader.attest_native_sources(
        graph,
        source,
        tenant_id=graph.tenant_id,
        geometry_mode="glyph",
    )
    state[0] = "new"
    monkeypatch.setenv(compat.PROFILE_ENV, PROFILE)
    cache._raster_replays.clear()
    try:
        args = (snapshot, lease.message, saved, graph, source, (), {})
        first = cache.replay_raster_cached(*args)
        metadata = receipt_read_metadata(saved)
        assert metadata["environment_drift"]
        evict_read_metadata()
        assert receipt_read_metadata(saved) is None
        assert cache.replay_raster_cached(*args) == first
        assert receipt_read_metadata(saved) == metadata
    finally:
        cache._raster_replays.clear()
        compat._meta.clear()


@pytest.mark.parametrize("side", ["stored", "current"])
@pytest.mark.parametrize("digest", ["reading", "rendered", "layer"])
def test_typography_reference_integrity_on_both_sides(os_drift_claim, side, digest):
    from proofops.adapters.local import claim_span_typography as typography
    from proofops.adapters.local.receipt_environment_compat import compare_receipts

    source, graph, ref, discovery, state = os_drift_claim
    saved = typography.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    state[0] = "new"
    current = typography.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    assert compare_receipts(saved, current, profile=PROFILE)["environment_drift"]
    target = saved if side == "stored" else current
    other = current if side == "stored" else saved
    if digest == "reading":
        # The unchanged lower hashes must not bypass validation of the reading.
        target["records"][0]["reading_sha256"] = other["records"][0]["reading_sha256"]
    elif digest == "rendered":
        assert target["typography_reads"]
        entry = next(iter(target["typography_reads"]))
        target["typography_reads"][entry]["rendered_read_sha256"] = other["typography_reads"][
            entry
        ]["rendered_read_sha256"]
    else:
        target["base_attestation_sha256"] = target["baseline_attestation_sha256"]
    target["artifact_sha256"] = canonical_hash(
        {key: value for key, value in target.items() if key != "artifact_sha256"}
    )
    with pytest.raises(ValueError, match="RECEIPT_DERIVED_HASH_MISMATCH"):
        compare_receipts(saved, current, profile=PROFILE)


def test_glyph_os_replay_preserves_historical_identity(os_drift_claim):
    from proofops.adapters.local import glyph_alignment_verification as glyph

    source, graph, ref, discovery, state = os_drift_claim
    saved = glyph.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
    strict = glyph.replay_claim_spans(saved, graph, source, discovery, tenant_id=TENANT)
    state[0] = "new"
    result = replay_receipt(
        glyph.replay_claim_spans,
        saved,
        graph,
        source,
        discovery,
        tenant_id=TENANT,
        profile=PROFILE,
    )
    assert [asdict(x) for x in result] == [asdict(x) for x in strict]
    assert receipt_read_metadata(saved)["environment_drift"]


def test_verified_span_read_then_publish_uses_current_attestation(monkeypatch):
    from proofops.adapters.local import claim_source_verification as base
    from proofops.adapters.local import native_replay_cache as cache
    from proofops.adapters.local import receipt_environment_compat as compat
    from proofops.adapters.local.claim_source_policies import attest_claims
    from proofops.domain.rulepacks import canonical_json

    from tests.integration.test_batch_attestation_cache import discovery_for
    from tests.integration.test_claim_source_verification import inputs

    source, graph, ref = inputs()
    state = ["old"]

    def reading(*args, **kwargs):
        return dict(
            status="read",
            text=graph.blocks[0].raw_text,
            reader="Apple Vision",
            os=state[0],
            revision=3,
            image_sha256="pixels",
        )

    monkeypatch.setattr(base, "_rendered_text", reading)
    monkeypatch.setenv(compat.PROFILE_ENV, PROFILE)
    cache._claim_replays.clear()
    cache._claim_attestations.clear()
    try:
        discovery = discovery_for(graph, (ref,))
        saved = base.attest_claim_spans(graph, source, (ref,), tenant_id=TENANT)
        original = canonical_json(saved).encode()
        strict = base.replay_claim_spans(saved, graph, source, discovery, tenant_id=TENANT)
        assert strict[1].verified_spans
        state[0] = "new"
        result = cache.replay_claims_cached(
            reader=base,
            policy=base.claim_source_policy(),
            receipt=saved,
            graph=graph,
            source=source,
            discovery=discovery,
            tenant_id=TENANT,
        )
        assert [asdict(x) for x in result] == [asdict(x) for x in strict]
        refs = (ref, graph.blocks[0].source_ref(), ref)
        current = base.attest_claim_spans(graph, source, refs, tenant_id=TENANT)
        published = attest_claims(
            reader=base,
            graph=graph,
            source=source,
            refs=refs,
            tenant_id=TENANT,
            cache=True,
        )
        assert canonical_json(published).encode() == canonical_json(current).encode()
        assert published["readings"][ref.source_id]["rendered"]["os"] == "new"
        assert canonical_json(saved).encode() == original
    finally:
        cache._claim_replays.clear()
        cache._claim_attestations.clear()
