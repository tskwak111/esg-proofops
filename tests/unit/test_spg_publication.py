"""SPG never imports persisted approvals or relaxes source/lease checks."""

import json
import sqlite3
from contextvars import ContextVar
from copy import deepcopy
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID, uuid4, uuid5

import pytest
from proofops.adapters.local import spg_verified_evidence as reuse
from proofops.application.analysis_profile import (
    FINALS_I29B_POLICY,
    SPG_POLICY,
    V2_PROFILE,
    policy_for,
    publication_policy_for,
)
from proofops.application.spg_publication import POLICY
from proofops.domain.provenance import canonical_hash


def test_spg_is_opt_in_and_only_adds_execution_policy():
    assert (
        policy_for(V2_PROFILE, pinned_hash=canonical_hash(FINALS_I29B_POLICY)) == FINALS_I29B_POLICY
    )
    assert SPG_POLICY == FINALS_I29B_POLICY | {
        "integration_profile": "spg_publication_v1",
        "spg_publication": POLICY,
    }
    pin = canonical_hash(SPG_POLICY)
    assert pin != canonical_hash(FINALS_I29B_POLICY)
    assert policy_for(V2_PROFILE, pinned_hash=pin) == SPG_POLICY
    assert publication_policy_for(V2_PROFILE, pinned_hash=pin) == SPG_POLICY


@pytest.fixture
def cache(tmp_path, monkeypatch):
    pins = {"source": "original", "checkpoint": "verified", "runtime": "current"}
    monkeypatch.setattr(reuse.Session, "fingerprint", lambda *a: canonical_hash(pins))
    calls = []
    checks = []
    claims = SimpleNamespace(
        receipt_read_compatibility=[], _read_compatibility=SimpleNamespace(set=lambda x: None)
    )
    expected = ({"claim_source_attestation": {"records": []}}, {"claims": ["same"]}, "graph")

    def cold():
        calls.append(1)
        return deepcopy(expected)

    session = reuse.Session(tmp_path, "tenant", ("hosted-run", 7), lambda: checks.append(1))
    return session, claims, pins, cold, calls, checks, expected


def test_verified_memory_is_reused_without_exposing_mutable_cache(cache):
    session, claims, _, cold, calls, checks, expected = cache
    first = session.read(claims, "tenant", "run", cold)
    first[1]["claims"].clear()
    assert session.read(claims, "tenant", "run", cold) == expected
    assert calls == [1]
    assert len(checks) >= 4


@pytest.mark.parametrize("changed", ["source", "checkpoint", "runtime"])
def test_changed_pin_replays_fully(cache, changed):
    session, claims, pins, cold, calls, _, _ = cache
    session.read(claims, "tenant", "run", cold)
    pins[changed] = "tampered"
    session.read(claims, "tenant", "run", cold)
    assert calls == [1, 1]


def test_mutation_during_verification_cannot_seed_cache(cache):
    session, claims, pins, cold, calls, _, _ = cache

    def raced():
        result = cold()
        pins["source"] = "changed while checking"
        return result

    session.read(claims, "tenant", "run", raced)
    session.read(claims, "tenant", "run", cold)
    assert calls == [1, 1]


def test_lost_lease_never_reuses_or_replays(cache):
    session, claims, _, cold, calls, _, _ = cache
    session.read(claims, "tenant", "run", cold)

    def lost():
        raise ValueError("LEASE_LOST")

    session.check_lease = lost
    with pytest.raises(ValueError, match="LEASE_LOST"):
        session.read(claims, "tenant", "run", cold)
    assert calls == [1]


def test_new_session_and_corrupted_memory_require_full_replay(cache):
    session, claims, _, cold, calls, _, expected = cache
    session.read(claims, "tenant", "run", cold)
    session.encoded = b"corrupted"
    assert session.read(claims, "tenant", "run", cold) == expected
    fresh = reuse.Session(session.path, "tenant", ("hosted-run", 8), session.check_lease)
    assert fresh.read(claims, "tenant", "run", cold) == expected
    assert calls == [1, 1, 1]


def test_failed_full_verification_cannot_seed_and_negative_states_never_promote(cache):
    session, claims, _, cold, calls, _, _ = cache

    def failed():
        raise ValueError("OCR_CLAIM_RECEIPT_MISMATCH")

    with pytest.raises(ValueError, match="OCR_CLAIM_RECEIPT_MISMATCH"):
        session.read(claims, "tenant", "run", failed)
    assert session.encoded is None

    def checked():
        result = cold()
        result[0]["claim_source_attestation"]["records"] = [
            {"status": "unresolved", "reason": "rendered_reader_unavailable"}
        ]
        return result

    result = session.read(claims, "tenant", "run", checked)
    assert session.read(claims, "tenant", "run", failed) == result
    assert calls == [1]


@pytest.fixture
def pinned(tmp_path, monkeypatch):
    """Real checkpoint/source fingerprint; only expensive runtime discovery is stubbed."""
    from proofops.adapters.local.job_store import LocalSQLiteJobStore
    from proofops.application.ingest.graph_fusion import ParserProfile

    tenant, run_id, version = (str(uuid4()) for _ in range(3))
    original = tmp_path / "original.pdf"
    original.write_bytes(b"source bytes")
    profile = ParserProfile(str(uuid4()), physical_pages=(1,))
    doc = dict(
        version_id=version,
        document_id=str(uuid4()),
        object_version_id="v1",
        sha256=sha256(original.read_bytes()).hexdigest(),
        page_count=1,
    )
    snapshot = dict(
        tenant_id=tenant,
        run_id=run_id,
        document=doc,
        selected_pages=[1],
        parser_profile=profile.config_snapshot(),
        parser_profile_hash=profile.config_hash(),
        pipeline_profile=V2_PROFILE,
        analysis_profile_policy=deepcopy(SPG_POLICY),
        analysis_profile_policy_sha256=canonical_hash(SPG_POLICY),
        claim_source_policy={},
    )
    snapshot["input_hash"] = canonical_hash(snapshot)
    manifest_id = str(uuid5(UUID(run_id), "parse:" + snapshot["input_hash"]))
    parser = SimpleNamespace(artifact_root=tmp_path / "parser-prepared")
    artifact = parser.artifact_root / tenant / version / manifest_id / "manifest.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_text('{"graph":"verified bytes"}')
    jobs = LocalSQLiteJobStore(tmp_path / "state.sqlite3")
    run = dict(
        tenant_id=tenant,
        run_id=run_id,
        document_version_id=version,
        claim_snapshot_sha256=sha256(b"extract").hexdigest(),
        cancellation_requested=False,
    )
    with jobs._transaction() as db:
        for stage in ("parse", "extract"):
            message = dict(
                tenant_id=tenant,
                run_id=run_id,
                document_version_id=version,
                job_id=str(uuid4()),
                stage=stage,
                shard="1",
                input_hash=snapshot["input_hash"],
            )
            run[stage + "_job"] = message
            payload = stage.encode()
            jobs._put(
                db,
                tenant,
                run_id,
                "job",
                message["job_id"],
                dict(
                    message=message,
                    artifact_ref=dict(
                        key=stage, sha256=sha256(payload).hexdigest(), byte_size=len(payload)
                    ),
                ),
            )
            jobs._put(db, tenant, run_id, "artifact", stage, payload)
        jobs._put(db, tenant, run_id, "run", "META", run)
        jobs._put(db, tenant, run_id, "parser_native_policy", "parse", {"pin": "native"})
    (tmp_path / "pilot.json").write_text(json.dumps(dict(tenant_id=tenant, run_id=run_id)))
    with sqlite3.connect(tmp_path / "upstage.sqlite3") as db:
        db.execute("CREATE TABLE ocr_response_bytes(request_id TEXT, body BLOB, sha256 TEXT)")
        db.execute(
            "INSERT INTO ocr_response_bytes VALUES ('request',?,?)",
            (b"source", sha256(b"source").hexdigest()),
        )
    claims = SimpleNamespace(
        store=SimpleNamespace(
            path=str(tmp_path / "state.sqlite3"), jobs=jobs, snapshot=lambda *_: snapshot
        ),
        uploads=SimpleNamespace(
            version_snapshot=lambda *_: doc, read_original=lambda *_: original.read_bytes()
        ),
        parser=parser,
        _read_compatibility=ContextVar("test_spg", default=[]),
        receipt_read_compatibility=[],
    )
    runtime = {"code": "same", "version": "same"}
    monkeypatch.setattr(reuse, "_runtime", lambda _: runtime)
    session = reuse.Session(tmp_path, tenant, ("hosted", 7), lambda: None)
    return session, claims, tenant, run_id, snapshot, original, artifact, runtime


@pytest.mark.parametrize(
    "mutation",
    [
        "original",
        "parse",
        "extract",
        "parser",
        "ocr",
        "runtime",
        "lease",
        "tenant",
        "run",
        "policy",
        "native",
        "symlink",
    ],
)
def test_real_input_fingerprint_rejects_every_changed_proof(pinned, mutation):
    session, claims, tenant, run_id, snapshot, original, artifact, runtime = pinned
    key = session.fingerprint(claims, tenant, run_id)
    assert key is not None
    if mutation == "original":
        original.write_bytes(b"changed bytes")
    elif mutation in ("parse", "extract", "native"):
        kind, record = (
            ("parser_native_policy", "parse") if mutation == "native" else ("artifact", mutation)
        )
        with claims.store.jobs._transaction() as db:
            db.execute(
                "UPDATE job_records SET value=? WHERE kind=? AND record_id=?",
                (b"tampered", kind, record),
            )
    elif mutation == "parser":
        artifact.write_text('{"graph":"tampered bytes"}')
    elif mutation == "ocr":
        with sqlite3.connect(session.path / "upstage.sqlite3") as db:
            db.execute("UPDATE ocr_response_bytes SET body=?", (b"forged original response",))
    elif mutation == "runtime":
        runtime["version"] = "changed"
    elif mutation == "lease":
        session.lease = ("hosted", 8)
    elif mutation == "tenant":
        tenant = str(uuid4())
    elif mutation == "run":
        run_id = str(uuid4())
    elif mutation == "policy":
        snapshot["analysis_profile_policy"]["spg_publication"] = {"profile": "forged"}
    else:
        (artifact.parent / "alias").symlink_to(original)
    assert session._key(claims, tenant, run_id) != key


def test_fingerprint_ignores_new_tags_but_not_changed_claim_head(pinned):
    session, claims, tenant, run_id, *_ = pinned
    before = session.fingerprint(claims, tenant, run_id)
    jobs = claims.store.jobs
    with jobs._transaction() as db:
        jobs._put(db, tenant, run_id, "tag_revision", "1", {"new": "checked separately"})
    assert session.fingerprint(claims, tenant, run_id) == before
    with jobs._transaction() as db:
        run = jobs._get(db, tenant, run_id, "run", "META")
        jobs._put(db, tenant, run_id, "run", "META", run | {"claim_snapshot_sha256": "f" * 64})
    assert session.fingerprint(claims, tenant, run_id) != before


def test_batch_projection_has_same_search_bytes_and_atomic_collision(pinned):
    from proofops.adapters.local.spg_search_projection import Projection
    from proofops.domain.documents import PageGeometry

    session, claims, tenant, run_id, snapshot, *_ = pinned
    graph = PageGeometry(100, 100, 0, (0, 0, 100, 100))
    projection = Projection(claims, tenant, run_id, graph, snapshot)
    for i in range(3):
        projection.put("element_evidence_search", str(i), {"proof": i})
    with claims.store.jobs._transaction() as db:
        assert jobs_count(db) == 0
        claims.store.jobs._put(
            db, tenant, run_id, "element_evidence_search", "2", {"proof": "tampered"}
        )
    with pytest.raises(ValueError, match="artifact mismatch"):
        projection.finish()
    with claims.store.jobs._transaction() as db:
        assert jobs_count(db) == 1  # All earlier pending writes rolled back.


def jobs_count(db):
    return db.execute(
        "SELECT count(*) FROM job_records WHERE kind='element_evidence_search'"
    ).fetchone()[0]


@pytest.mark.parametrize("tamper", ["redirect", "collection", "key"])
def test_c3_other_pdf_append_keeps_main_proof_but_tampering_does_not(tmp_path, tamper):
    ledger = tmp_path / "upstage.sqlite3"
    main_sha, c3_sha = "1" * 64, "2" * 64
    with sqlite3.connect(ledger) as db:
        db.execute(
            "CREATE TABLE ocr_calls(request_id TEXT,tenant TEXT,cache_key TEXT,"
            "committed TEXT,state TEXT,collection TEXT)"
        )
        db.execute("CREATE TABLE ocr_page_cache(tenant TEXT,cache_key TEXT,request_id TEXT)")
        db.execute("CREATE TABLE ocr_response_bytes(request_id TEXT,body BLOB,sha256 TEXT)")

        def add(request, source):
            record = dict(
                schema="upstage_ocr_collection_v1",
                request_id=request,
                tenant_id="tenant",
                manifest=dict(source_sha256=source),
                policy={"reader": "same"},
            )
            key = canonical_hash(dict(manifest=record["manifest"], policy=record["policy"]))
            record["artifact_sha256"] = canonical_hash(record)
            db.execute(
                "INSERT INTO ocr_calls VALUES (?, 'tenant', ?, '0.00165', 'collected', ?)",
                (request, key, json.dumps(record)),
            )
            db.execute("INSERT INTO ocr_page_cache VALUES ('tenant',?,?)", (key, request))
            db.execute(
                "INSERT INTO ocr_response_bytes VALUES (?,?,?)",
                (request, b"raw", sha256(b"raw").hexdigest()),
            )
            db.commit()
            return key

        main_key = add("main", main_sha)
        before = reuse._ocr(ledger, main_sha)
        add("c3", c3_sha)
        assert reuse._ocr(ledger, main_sha) == before
        if tamper == "redirect":
            db.execute("UPDATE ocr_page_cache SET request_id='c3' WHERE cache_key=?", (main_key,))
        elif tamper == "key":
            db.execute("UPDATE ocr_calls SET cache_key='forged' WHERE request_id='c3'")
        else:
            record = json.loads(
                db.execute("SELECT collection FROM ocr_calls WHERE request_id='c3'").fetchone()[0]
            )
            record["artifact_sha256"] = "forged"
            db.execute(
                "UPDATE ocr_calls SET collection=? WHERE request_id='c3'", (json.dumps(record),)
            )
        db.commit()
        with pytest.raises(ValueError, match="OCR_BINDING_CHANGED"):
            reuse._ocr(ledger, main_sha)
