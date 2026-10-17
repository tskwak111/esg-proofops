"""Exact provider-response reuse; separate replicas and immutable origin receipts.

The pending marker fences concurrent processes and survives uncertain dispatch.
It is never a model result. Only complete, schema-valid settled responses are
published. Cache files belong to the document payload and are purged with it.
"""

import json
import os
import sqlite3
import time
from pathlib import Path

from proofops.adapters.local.sqlite_busy import connection
from proofops.domain.provenance import canonical_hash


class ModelResponseCache:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with connection(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS model_responses_v1 ("
                "key TEXT PRIMARY KEY, ledger TEXT NOT NULL, request_id TEXT NOT NULL, "
                "payload TEXT, sha256 TEXT)"
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS immutable_model_response_v1 "
                "BEFORE UPDATE ON model_responses_v1 WHEN OLD.payload IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT,'MODEL_RESPONSE_IMMUTABLE'); END"
            )
            db.execute(
                "CREATE TRIGGER IF NOT EXISTS immutable_model_response_delete_v1 "
                "BEFORE DELETE ON model_responses_v1 WHEN OLD.payload IS NOT NULL "
                "BEGIN SELECT RAISE(ABORT,'MODEL_RESPONSE_IMMUTABLE'); END"
            )
        self.path.chmod(0o600)

    def claim(self, key, ledger, request_id):
        deadline = time.monotonic() + 30
        while True:
            with connection(self.path) as db:
                row = db.execute(
                    "SELECT ledger,request_id,payload,sha256 FROM model_responses_v1 WHERE key=?",
                    (key,),
                ).fetchone()
                if row is None:
                    db.execute(
                        "INSERT INTO model_responses_v1 VALUES (?,?,?,NULL,NULL)",
                        (key, str(Path(ledger).resolve()), request_id),
                    )
                    return None
            if row[2] is not None:
                return self._verified(key, row)
            if time.monotonic() >= deadline:
                raise ValueError("PROCESSING_UNCERTAIN")
            time.sleep(0.05)

    @staticmethod
    def _verified(key, row):
        try:
            ledger, request_id, raw, digest = row
            result = json.loads(raw)
            if canonical_hash(result) != digest or result["schema_valid"] is not True:
                raise ValueError
            if Path(ledger).suffix == ".json":
                origin = json.loads(Path(ledger).read_text())
                receipt = origin["receipt"]
                original = (
                    receipt["cost_with_vat_reserve_usd"],
                    json.dumps(receipt),
                    origin["wire_sha256"],
                )
                data = origin["provider_response"]
                if canonical_hash(receipt) != origin["receipt_sha256"]:
                    raise ValueError
            else:
                # Retained local experiment rows created before origin-copy
                # publication remain verifiable against their original ledgers.
                with connection(Path(ledger).as_uri() + "?mode=ro", uri=True, readonly=True) as db:
                    original = db.execute(
                        "SELECT committed,receipt,signature FROM probe_calls WHERE request_id=?",
                        (request_id,),
                    ).fetchone()
                receipt = json.loads(original[1])
                last = len(receipt["attempts"]) - 1
                path = Path(ledger + ".responses") / (
                    canonical_hash(f"{request_id}:{last}") + ".json"
                )
                data = json.loads(path.read_text())["provider_response"]
            if (
                canonical_hash(receipt["response_request"]) != key
                or original[2] != receipt["response_request"]["wire_sha256"]
            ):
                raise ValueError
            if (
                receipt != {k: v for k, v in result.items() if k != "content"}
                or original[0] != receipt["cost_with_vat_reserve_usd"]
            ):
                raise ValueError
            if (
                canonical_hash(data) != receipt["response_sha256"]
                or data["choices"][0]["message"]["content"] != result["content"]
            ):
                raise ValueError
            return result, canonical_hash(receipt)
        except (ValueError, TypeError, KeyError, IndexError, OSError, sqlite3.Error):
            raise ValueError("MODEL_RESPONSE_CACHE_INVALID") from None

    def publish(self, key, result):
        with connection(self.path, readonly=True) as db:
            row = db.execute(
                "SELECT ledger,request_id FROM model_responses_v1 WHERE key=? AND payload IS NULL",
                (key,),
            ).fetchone()
        if row is None:
            raise ValueError("MODEL_RESPONSE_CACHE_INVALID")
        # Preserve an immutable origin before temporary worker state disappears.
        # This is a receipt artifact, never a new or reset provider budget ledger.
        ledger, request_id = row
        self._verified(key, (ledger, request_id, json.dumps(result), canonical_hash(result)))
        receipt = {k: v for k, v in result.items() if k != "content"}
        last = len(receipt["attempts"]) - 1
        raw_path = Path(ledger + ".responses") / (canonical_hash(f"{request_id}:{last}") + ".json")
        origin = dict(
            schema="model-response-origin-v1",
            receipt=receipt,
            receipt_sha256=canonical_hash(receipt),
            wire_sha256=receipt["response_request"]["wire_sha256"],
            provider_response=json.loads(raw_path.read_text())["provider_response"],
        )
        origin_dir = self.path.with_suffix(".origins")
        origin_dir.mkdir(mode=0o700, exist_ok=True)
        origin_path = origin_dir / (key + ".json")
        with os.fdopen(
            os.open(origin_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
        ) as stream:
            json.dump(origin, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        with connection(self.path) as db:
            changed = db.execute(
                "UPDATE model_responses_v1 SET ledger=?,payload=?,sha256=? "
                "WHERE key=? AND payload IS NULL",
                (
                    str(origin_path.resolve()),
                    json.dumps(result, sort_keys=True),
                    canonical_hash(result),
                    key,
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("MODEL_RESPONSE_CACHE_INVALID")

    def release_unsent_or_invalid(self, key, ledger, request_id):
        with connection(ledger, readonly=True) as db:
            row = db.execute(
                "SELECT receipt FROM probe_calls WHERE request_id=?", (request_id,)
            ).fetchone()
        # No provider reservation, or a known settled schema failure: no reusable
        # result. An unfinished reservation keeps its dispatch fence indefinitely.
        if row is None or (row[0] is not None and json.loads(row[0]).get("schema_valid") is False):
            with connection(self.path) as db:
                db.execute("DELETE FROM model_responses_v1 WHERE key=? AND payload IS NULL", (key,))
