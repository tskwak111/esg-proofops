"""RC1: copy a sealed publication, never import another tenant's live stores.

The existing control transaction serializes admission and publication. Reused
runs have their own immutable snapshot and uploaded PDF; the private audit is
the only place that retains the originating run ID. No provider or spend row is
created. Unpinned legacy runs cannot seed reuse.
"""

import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from proofops.domain.provenance import canonical_hash

from proofops_api.hosted_store import HostedError, day, digest, file_sha256

PROFILE = "rc1_published_result_v1"
POLICY = dict(
    profile=PROFILE,
    publication_revision=1,
    minimum_claims=1,
    identity="pdf+assigned_policy+effective_scope+reporting_period",
    tenant_copy="immutable_result_and_display_coordinates",
    cost_usd=0,
)
POLICY_SHA256 = canonical_hash(POLICY)


def migrate(db):
    db.execute("CREATE INDEX IF NOT EXISTS rc1_document_sha ON documents(sha256)")
    db.execute("""CREATE TABLE IF NOT EXISTS rc1_reuse_audit (
        run_id TEXT PRIMARY KEY, source_run_id TEXT NOT NULL, analyzed_at TEXT NOT NULL,
        source_policy_sha256 TEXT NOT NULL, cache_key TEXT NOT NULL,
        source_snapshot_sha256 TEXT NOT NULL, created REAL NOT NULL)""")
    db.execute("""CREATE TRIGGER IF NOT EXISTS rc1_reuse_audit_update
        BEFORE UPDATE ON rc1_reuse_audit
        BEGIN SELECT RAISE(ABORT,'immutable reuse provenance'); END""")


def cache_key(sha, options, period=None):
    """Ignore account-bound proposal hashes, retain every effective scope field.

    proposal/selection/detection hashes embed upload UUIDs. They are validated
    by the existing scope reader before this function. Their effective output,
    scope policy and period form the portable selection hash instead.
    """
    from evaluation.reporting_period import validate_period

    if not options or not re.fullmatch(r"[0-9a-f]{64}", options.get("analysis_profile_sha256", "")):
        return None
    try:
        reporting = validate_period(period or options.get("reporting_scope"))
    except ValueError:
        return None
    scope = {
        k: v
        for k, v in options.items()
        if k
        not in {
            "sha256",
            "source_sha256",
            "selection_sha256",
            "proposal_sha256",
            "reporting_scope",
            "analysis_profile",
            "analysis_profile_sha256",
            "provider_execution",
            "provider_execution_sha256",
        }
    }
    return canonical_hash(
        dict(
            profile=POLICY_SHA256,
            pdf_sha256=sha,
            policy_sha256=options["analysis_profile_sha256"],
            selection_sha256=canonical_hash(scope),
            reporting_period=reporting,
        )
    )


def _snapshot(store, db, row):
    anchor = db.execute(
        "SELECT sha256 FROM result_snapshots WHERE run_id=? AND revision=1", (row["run_id"],)
    ).fetchone()
    if anchor is None:
        raise ValueError("unpublished")
    path = store.document_dir(row["tenant_id"], row["document_id"]) / "analysis" / row["run_id"]
    target = path / "result-1.json"
    if path.is_symlink() or target.is_symlink():
        raise ValueError("unsafe snapshot")
    content = target.read_bytes()
    if digest(content) != anchor[0]:
        raise ValueError("snapshot integrity")
    snapshot = json.loads(content)
    if snapshot["tenant_id"] != row["tenant_id"] or snapshot["page_map"] != json.loads(
        row["pages"]
    ):
        raise ValueError("snapshot binding")
    for relative, expected in snapshot["source_hashes"].items():
        part = Path(relative)
        if part.is_absolute() or ".." in part.parts:
            raise ValueError("unsafe source")
        source = path / part
        if (
            any((path / parent).is_symlink() for parent in (part, *part.parents))
            or file_sha256(source) != expected
        ):
            raise ValueError("source integrity")
    analyzed_at = datetime.fromtimestamp(target.stat().st_mtime, UTC).isoformat()
    return snapshot["result"], anchor[0], analyzed_at


def _private_copy(result, row, auth, document, run):
    """Rebind identifiers consistently, and exclude human/account metadata.

    Only revision 1 is eligible, so later tenant-specific human decisions never
    enter the shared cache. Review summaries remain visible but are read-only.
    """
    identities = {
        row["tenant_id"]: auth.tenant_id,
        row["document_id"]: document,
        row["run_id"]: run,
    }
    private_keys = {
        "user_id",
        "user_sub",
        "user_hash",
        "session_id",
        "reviewer_id",
        "reviewer",
        "resolved_by",
        "created_by",
        "updated_by",
        "actor",
        "workspace",
        "path",
        "source_path",
        "object_key",
        "url",
        "reuse",
    }
    identity_keys = {
        "claim_id",
        "source_id",
        "document_version_id",
        "parse_manifest_id",
        "object_version_id",
        "review_id",
        "job_id",
        "tag_id",
        "decision_id",
        "request_id",
    }

    def identity(value):
        if value not in identities:
            identities[value] = str(uuid5(UUID(run), value))
        return identities[value]

    def copy(value, key=""):
        if isinstance(value, dict):
            return {k: copy(v, k) for k, v in value.items() if k not in private_keys}
        if isinstance(value, list):
            return [copy(v, key.removesuffix("s")) for v in value]
        if isinstance(value, str):
            if key == "tenant_id":
                return auth.tenant_id
            if key == "run_id":
                return run
            if key == "document_id":
                return document
            if key in identity_keys:
                return identity(value)
            # Preserve source text exactly; it is PDF content, not account metadata.
            if key in {"quote", "raw_text", "text", "canonical_quote"}:
                return value
            for original, replacement in identities.items():
                value = value.replace(original, replacement)
        return value

    # Operational pipeline internals are not part of a transferable report.
    public = {
        k: v
        for k, v in result.items()
        if k
        in {
            "schema",
            "claims",
            "reviews",
            "hold_reasons",
            "hold_reason_details",
            "page_map",
            "possible_grade_range",
            "confirmed_grade",
            "w16_source_document",
        }
    }
    public["pipeline"] = {
        k: v
        for k, v in result.get("pipeline", {}).items()
        if k
        in {
            "status",
            "reason",
            "reporting_scope",
            "scope",
            "extraction_outcome",
            "stage_seconds",
            "pipeline_profile",
            "pipeline_failure_projection",
            "provider_failure_projection_sha256",
        }
    }
    return copy(public)


def try_reuse(store, db, auth, doc, options, *, key, body_hash, now):
    wanted = cache_key(doc["sha256"], options)
    if wanted is None:
        return None
    candidates = db.execute(
        "SELECT r.* FROM documents d JOIN runs r USING(tenant_id,document_id) "
        "JOIN run_progress p USING(run_id) WHERE d.sha256=? AND d.expires>? "
        "AND r.status IN ('completed','partial_blocked') AND p.result_ready=1 "
        "AND NOT EXISTS(SELECT 1 FROM deletion.tombstones t WHERE "
        "t.tenant_id=d.tenant_id AND t.document_id=d.document_id) "
        "ORDER BY r.created DESC,r.run_id",
        (doc["sha256"], now),
    ).fetchall()
    for source in candidates:
        try:
            source_options = store.run_options(source)
            # Avoid reading unrelated publications, especially large receipts.
            if source_options.get("analysis_profile_sha256") != options["analysis_profile_sha256"]:
                continue
            result, source_hash, analyzed_at = _snapshot(store, db, source)
            period = result.get("pipeline", {}).get("reporting_scope")
            published_options = result.get("pipeline", {}).get("scope", {})
            if (
                not result.get("claims")
                or cache_key(doc["sha256"], source_options, period) != wanted
                or cache_key(doc["sha256"], published_options, period) != wanted
            ):
                continue
            source_doc = dict(store._document(db, source["tenant_id"], source["document_id"]))
            store.analysis_source(
                store.document_dir(source["tenant_id"], source["document_id"]), source_doc
            )
            from proofops_api.hosted_reads import HostedReads
            from proofops_api.hosted_source_view import project_source_view

            view = project_source_view(HostedReads(store), source, source_doc, result, w18=True)
            origin = db.execute(
                "SELECT * FROM rc1_reuse_audit WHERE run_id=?", (source["run_id"],)
            ).fetchone()
        except (HostedError, OSError, ValueError, KeyError, TypeError, sqlite3.DatabaseError):
            continue  # Invalid/unavailable sources are misses, never successful empty results.
        # Do not permanently freeze a temporary W18 reader/lock failure into a
        # detached copy, or start a paid analysis just because coordinates are busy.
        if any(
            ref.get("w18_reason")
            in {"coordinate_busy", "coordinate_timeout", "original_integrity_or_reader_unavailable"}
            for claim in view.get("claims", [])
            for ref in claim.get("w16_source_view", {}).get("refs", [])
        ):
            raise HostedError("REUSE_COORDINATES_BUSY", 429, retry_after=2)
        run = str(uuid4())
        copied = _private_copy(view, source, auth, doc["document_id"], run)
        copied["pipeline"]["scope"] = options
        analyzed_at = origin["analyzed_at"] if origin else analyzed_at
        copied["reuse"] = dict(
            reused=True,
            analyzed_at=analyzed_at,
            source_policy_sha256=options["analysis_profile_sha256"],
            policy_sha256=POLICY_SHA256,
            cost_usd="0.000000",
            provider_calls=0,
            review_supported=False,
        )
        copied["w16_source_document"] = source_document(doc)
        directory = store.document_dir(auth.tenant_id, doc["document_id"])
        target = directory / "analysis" / run
        target.mkdir(parents=True, mode=0o700)
        stored_options = options | {"sha256": canonical_hash(options)}
        store._write(directory / f"{run}.options.json", json.dumps(stored_options).encode())
        db.execute(
            "INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,0,0,0,?,NULL)",
            (
                auth.tenant_id,
                run,
                doc["document_id"],
                store.user_hash(auth.user_sub),
                json.dumps(options["pages"]),
                source["status"],
                now,
                day(now),
                store.settings.event_id,
                source["error_code"],
            ),
        )
        content = json.dumps(
            dict(
                tenant_id=auth.tenant_id, page_map=options["pages"], source_hashes={}, result=copied
            ),
            ensure_ascii=False,
        ).encode()
        store._publish_snapshot(db, run, target, content)
        db.execute("INSERT INTO run_progress VALUES (?,'result',100,1)", (run,))
        counts = db.execute(
            "SELECT extracted,processed FROM run_claim_progress WHERE run_id=?", (source["run_id"],)
        ).fetchone()
        db.execute(
            "INSERT INTO run_claim_progress VALUES (?,?,?)",
            (run, counts[0] if counts else len(copied["claims"]), counts[1] if counts else 0),
        )
        db.execute(
            "INSERT INTO deletion.source_retention VALUES (?,?,?,?,?)",
            (auth.tenant_id, run, doc["document_id"], doc["expires"], now),
        )
        db.execute(
            "INSERT INTO rc1_reuse_audit VALUES (?,?,?,?,?,?,?)",
            (
                run,
                origin["source_run_id"] if origin else source["run_id"],
                analyzed_at,
                options["analysis_profile_sha256"],
                wanted,
                origin["source_snapshot_sha256"] if origin else source_hash,
                now,
            ),
        )
        store._remember(db, auth, "run", key, body_hash, run, doc["document_id"], now)
        return store._project_run(store._run(db, auth.tenant_id, run), db)
    return None


def source_document(doc):
    return dict(
        document_id=doc["document_id"],
        sha256=doc["sha256"],
        page_count=doc["page_count"],
        url=f'/v1/documents/{doc["document_id"]}/original?sha256={doc["sha256"]}',
    )


def verify_copy(store, row, result):
    """A new result remains usable without its originating tenant or workspace."""
    document = result["w16_source_document"]
    if document["document_id"] != row["document_id"]:
        raise ValueError("reused document binding")
    original = store.document_dir(row["tenant_id"], row["document_id"]) / "original.pdf"
    if original.is_symlink() or file_sha256(original) != document["sha256"]:
        raise ValueError("reused original integrity")
