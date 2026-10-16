"""Additive display metadata, stored with the original and deleted with its document.

No effect on PDF bytes, analysis profiles, replay hashes or grading.
"""

import json
import sqlite3
from urllib.parse import unquote

from proofops_api.hosted_store import HostedError

UX1_POLICY_SHA256 = "bf9c32d96dde26ab8575bedc8cbbce157e74c1a1dd9c0b57634f4cdd9fcf50b3"


def enabled_for(options):
    """Use the run's frozen policy; older runs keep their original projection."""
    from proofops.application.analysis_profile import policy_for

    pin = options.get("analysis_profile_sha256")
    if pin is None:
        return False
    try:
        policy = policy_for(options.get("analysis_profile"), pinned_hash=pin)
    except ValueError:
        return False
    return policy.get("ux1_data_policy_sha256") == UX1_POLICY_SHA256


def parse_metadata(header: str | None) -> dict | None:
    if header is None:
        return None
    if len(header) > 6000:
        raise HostedError("UX1_METADATA_INVALID", 422)
    try:
        value = json.loads(unquote(header, errors="strict"))
    except (ValueError, UnicodeError):
        raise HostedError("UX1_METADATA_INVALID", 422) from None
    if not isinstance(value, dict) or value.get("policy_sha256") != UX1_POLICY_SHA256:
        raise HostedError("UX1_METADATA_INVALID", 422)
    if set(value) - {"policy_sha256", "original_filename", "title"}:
        raise HostedError("UX1_METADATA_INVALID", 422)
    clean = {"policy_sha256": UX1_POLICY_SHA256}
    for field in ("original_filename", "title"):
        if field not in value:
            continue
        text = value[field]
        if not isinstance(text, str) or len(text) > 200 or any(ord(c) < 32 for c in text):
            raise HostedError("UX1_METADATA_INVALID", 422)
        if field == "original_filename":
            text = text.replace("\\", "/").rsplit("/", 1)[-1]
        if text.strip():
            clean[field] = text.strip()
    return clean


def project_data(reads, row, result):
    """Add measured table blocks from the pinned parser graph; never rewrite a snapshot."""
    from hashlib import sha256

    from proofops.adapters.parsing.parser_artifacts import read_parser_json

    table_count = None
    if not result.get("reuse", {}).get("reused") and result.get("page_map"):
        root = (
            reads.store.document_dir(row["tenant_id"], row["document_id"])
            / "analysis"
            / row["run_id"]
        )
        try:
            # Existing reader verifies tenant, source, job checkpoint and manifest binding.
            version, manifest_id, manifest_sha, _ = reads._anchor(root, row, 1)
            directory = root / "parser-prepared" / row["tenant_id"] / version / manifest_id
            raw = (directory / "manifest.json").read_bytes()
            if sha256(raw).hexdigest() != manifest_sha:
                raise ValueError("manifest changed")
            manifest = json.loads(raw)
            if manifest["tenant_id"] != row["tenant_id"]:
                raise ValueError("manifest tenant")
            graph = read_parser_json(directory / "graph.json", manifest=manifest)
            if (
                graph["document_version_id"],
                graph["parse_manifest_id"],
                graph["source_sha256"],
            ) != (version, manifest_id, row["prepared_sha256"]):
                raise ValueError("graph binding")
            table_count = sum(block["kind"] == "table" for block in graph["blocks"])
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            IndexError,
            StopIteration,
            HostedError,
            sqlite3.DatabaseError,
        ):
            pass  # Missing/unverifiable historical artifacts are not zero tables.
    pipeline = result.get("pipeline") or {}
    return result | {
        "pipeline": pipeline
        | {
            "ux1_data": {
                "table_count": table_count,
                "table_count_basis": "selected_parser_table_blocks",
                "policy_sha256": UX1_POLICY_SHA256,
            }
        }
    }
