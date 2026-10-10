"""Explicit Azure Layout requests with durable resume and bounded page reservations.

POST timeouts remain uncertain: never resubmit them automatically. GET is safe
to retry. No provider prices are invented; reservations count submitted pages.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

import httpx

API_VERSION = "2024-11-30"
MODEL = "prebuilt-layout"


class AzureFailure(ValueError):
    pass


class AzureLayoutClient:
    def __init__(
        self,
        endpoint,
        key,
        database: Path,
        *,
        max_pages=50,
        transport=None,
        timeout=180,
        poll_interval=1,
    ):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise AzureFailure("AZURE_ENDPOINT_INVALID")
        if not key or key != key.strip():
            raise AzureFailure("AZURE_CREDENTIALS_REQUIRED")
        if type(max_pages) is not int or max_pages < 1:
            raise AzureFailure("AZURE_PAGE_BUDGET_INVALID")
        self.endpoint, self.key = endpoint.rstrip("/"), key
        self.database, self.max_pages = Path(database), max_pages
        self.transport, self.timeout, self.poll_interval = transport, timeout, poll_interval
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY, pages INTEGER NOT NULL, state TEXT NOT NULL,
                operation TEXT, response TEXT, response_hash TEXT)""")

    @classmethod
    def from_environment(cls, database):
        endpoint = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "")
        key = os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_KEY", "")
        if not endpoint or not key:
            raise AzureFailure("AZURE_CREDENTIALS_REQUIRED")
        try:
            max_pages = int(os.environ.get("AZURE_DOCUMENT_INTELLIGENCE_MAX_PAGES", "50"))
        except ValueError:
            raise AzureFailure("AZURE_PAGE_BUDGET_INVALID") from None
        return cls(
            endpoint,
            key,
            database,
            max_pages=max_pages,
        )

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _state(self, identifier, state, **values):
        with self._db() as db:
            assignments = ["state=?"] + [f"{key}=?" for key in values]
            db.execute(
                f"UPDATE requests SET {','.join(assignments)} WHERE id=?",
                (state, *values.values(), identifier),
            )

    def analyze(self, content: bytes, pages: tuple[int, ...], *, scope: str):
        if (
            not pages
            or tuple(sorted(set(pages))) != pages
            or any(type(page) is not int or page < 1 for page in pages)
        ):
            raise AzureFailure("AZURE_PAGES_INVALID")
        identity = json.dumps(
            [scope, self.endpoint, API_VERSION, MODEL, sha256(content).hexdigest(), pages],
            separators=(",", ":"),
        )
        identifier = sha256(identity.encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM requests WHERE id=?", (identifier,)).fetchone()
            if row is None:
                used = db.execute("SELECT COALESCE(SUM(pages),0) FROM requests").fetchone()[0]
                if used + len(pages) > self.max_pages:
                    raise AzureFailure("AZURE_PAGE_BUDGET_EXCEEDED")
                db.execute(
                    "INSERT INTO requests(id,pages,state) VALUES(?,?,?)",
                    (identifier, len(pages), "submitting"),
                )
        if row and row["state"] == "succeeded":
            if sha256(row["response"].encode()).hexdigest() != row["response_hash"]:
                raise AzureFailure("AZURE_CACHE_INTEGRITY_MISMATCH")
            return json.loads(row["response"]), {
                "request_id": identifier,
                "cache_hit": True,
                "submitted_pages": 0,
                "cost_usd": None,
            }
        if row and row["state"] not in ("running",):
            raise AzureFailure("AZURE_SUBMISSION_REQUIRES_REVIEW")
        operation = row["operation"] if row else None
        with httpx.Client(
            transport=self.transport, timeout=min(60, self.timeout), follow_redirects=False
        ) as client:
            if operation is None:
                try:
                    response = client.post(
                        self.endpoint + f"/documentintelligence/documentModels/{MODEL}:analyze",
                        params={
                            "api-version": API_VERSION,
                            "pages": ",".join(map(str, pages)),
                            "stringIndexType": "unicodeCodePoint",
                        },
                        headers={
                            "Ocp-Apim-Subscription-Key": self.key,
                            "Content-Type": "application/pdf",
                        },
                        content=content,
                    )
                except httpx.HTTPError:
                    self._state(identifier, "uncertain")
                    raise AzureFailure("AZURE_SUBMISSION_UNCERTAIN") from None
                if response.status_code != 202:
                    self._state(
                        identifier, "rejected" if response.status_code < 500 else "uncertain"
                    )
                    raise AzureFailure(f"AZURE_SUBMIT_HTTP_{response.status_code}")
                operation = response.headers.get("operation-location", "")
                if not self._safe_operation(operation):
                    self._state(identifier, "uncertain")
                    raise AzureFailure("AZURE_OPERATION_URL_INVALID")
                self._state(identifier, "running", operation=operation)
            if not self._safe_operation(operation):
                raise AzureFailure("AZURE_OPERATION_URL_INVALID")
            deadline = time.monotonic() + self.timeout
            while time.monotonic() < deadline:
                try:
                    response = client.get(
                        operation, headers={"Ocp-Apim-Subscription-Key": self.key}
                    )
                except httpx.HTTPError:
                    raise AzureFailure("AZURE_POLL_INTERRUPTED_RESUMABLE") from None
                if response.status_code == 429 or response.status_code >= 500:
                    try:
                        delay = float(response.headers.get("retry-after", "5"))
                    except ValueError:
                        delay = 5
                    if not 0 <= delay <= max(0, deadline - time.monotonic()):
                        raise AzureFailure("AZURE_RETRY_LATER_RESUMABLE")
                    time.sleep(max(delay, 0.01))
                    continue
                if response.status_code != 200:
                    raise AzureFailure(f"AZURE_POLL_HTTP_{response.status_code}")
                if len(response.content) > 20_000_000:
                    raise AzureFailure("AZURE_RESPONSE_LIMIT")
                try:
                    result = response.json()
                    state = result["status"]
                except (ValueError, KeyError, TypeError):
                    raise AzureFailure("AZURE_RESPONSE_INVALID") from None
                if state == "succeeded":
                    try:
                        if not isinstance(result["analyzeResult"], dict):
                            raise ValueError("result object required")
                        data = json.dumps(
                            result["analyzeResult"], ensure_ascii=False, allow_nan=False
                        )
                    except (ValueError, KeyError, TypeError):
                        raise AzureFailure("AZURE_RESPONSE_INVALID") from None
                    self._state(
                        identifier,
                        "succeeded",
                        response=data,
                        response_hash=sha256(data.encode()).hexdigest(),
                    )
                    return result["analyzeResult"], {
                        "request_id": identifier,
                        "cache_hit": False,
                        "resumed": row is not None,
                        "submitted_pages": 0 if row else len(pages),
                        "cost_usd": None,
                    }
                if state in ("failed", "canceled"):
                    self._state(identifier, state)
                    raise AzureFailure("AZURE_ANALYSIS_FAILED")
                if state not in ("running", "notStarted"):
                    raise AzureFailure("AZURE_STATUS_INVALID")
                time.sleep(self.poll_interval)
        raise AzureFailure("AZURE_POLL_TIMEOUT_RESUMABLE")

    def _safe_operation(self, value):
        parsed, base = urlparse(value), urlparse(self.endpoint)
        return (
            parsed.scheme == "https"
            and parsed.netloc == base.netloc
            and not parsed.username
            and not parsed.password
            and not parsed.fragment
            and parsed.path.startswith(
                f"/documentintelligence/documentModels/{MODEL}/analyzeResults/"
            )
        )

    def summary(self):
        with self._db() as db:
            rows = db.execute(
                "SELECT state, COUNT(*) n, SUM(pages) pages FROM requests GROUP BY state"
            )
            return {row["state"]: {"requests": row["n"], "pages": row["pages"]} for row in rows}
