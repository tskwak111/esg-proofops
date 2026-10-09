"""Budgeted direct OpenAI chat transport; shares the existing USD3 Decisions ledger."""

from __future__ import annotations

import http.client
import json
import os
import sqlite3
import time
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, ValidationError

# Ledger policy remains byte-identical to existing Decisions policy: never reset spend.
from proofops.adapters.local.decisions import OPENAI_POLICY as POLICY
from proofops.adapters.local.openrouter import OpenRouterProbe
from proofops.domain.provenance import canonical_hash

MODEL = "gpt-6-luna"
ENDPOINT = "https://api.openai.com/v1/chat/completions"
PRICE_RECHECK_AT = datetime(2026, 10, 21, tzinfo=UTC)
PRICE = {"input": "0.10", "cached_input": "0.01", "cache_write": "0.125", "output": "0.50"}
WIRE_POLICY = {
    "provider": "openai",
    "endpoint": ENDPOINT,
    "model": MODEL,
    "reasoning_effort": "none",
    "temperature": 0,
    "store": False,
    "service_tier": "default",
    "price_per_million": PRICE,
    "pricing_source": "https://developers.openai.com/api/docs/models/gpt-6-luna",
    "captured_at": "2026-10-09",
    "price_recheck_at": "2026-10-21T00:00:00Z",
    "max_request_bytes": 16384,
    "max_response_bytes": 1048576,
    "max_attempts": 2,
    "vat_reserve": "1.10",
}
CAPACITY_POLICY = {
    "schema": "openai-luna-input-reservation-v1",
    "model_id": MODEL,
    "reservation_input_tokens": 32768,
    "request_bytes": 16384,
    "model_binding_sha256": canonical_hash(WIRE_POLICY),
}


def now():
    return datetime.now(UTC)


def validate_capacity_policy(policy, *, model_id):
    if model_id != MODEL or policy != CAPACITY_POLICY:
        raise ValueError("OPENAI_CAPACITY_POLICY_MISMATCH")
    if now() >= PRICE_RECHECK_AT:
        raise ValueError("PRICE_RECHECK_REQUIRED")
    return CAPACITY_POLICY["reservation_input_tokens"]


def token_cost(usage):
    incoming, outgoing = usage["prompt_tokens"], usage["completion_tokens"]
    details = usage.get("prompt_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    written = details.get("cache_write_tokens", 0)
    if any(type(n) is not int or n < 0 for n in (incoming, outgoing, cached, written)):
        raise ValueError("INVALID_USAGE")
    if incoming > 32768 or cached + written > incoming:
        raise ValueError("INVALID_USAGE")
    return (
        (
            (incoming - cached - written) * Decimal(PRICE["input"])
            + cached * Decimal(PRICE["cached_input"])
            + written * Decimal(PRICE["cache_write"])
            + outgoing * Decimal(PRICE["output"])
        )
        / Decimal(1000000)
        * Decimal("1.10")
    )


class OpenAIProbe(OpenRouterProbe):
    def __init__(self, api_key: str, ledger: Path, *, model: str = MODEL, wire_policy_version=2):
        if model != MODEL:
            raise ValueError("UNSUPPORTED_MODEL")
        if not api_key or any(c.isspace() for c in api_key):
            raise ValueError("OPENAI_API_KEY_MISSING_OR_INVALID")
        if wire_policy_version != 2:
            raise ValueError("OPENAI_WIRE_POLICY_INVALID")
        self.model, self._key, self.ledger = model, api_key, Path(ledger)
        self.wire_policy_version = wire_policy_version
        self.ledger.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sqlite3.connect(self.ledger) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS probe_policy (id INTEGER PRIMARY KEY, body TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS probe_calls (request_id TEXT PRIMARY KEY, "
                "signature TEXT NOT NULL, committed TEXT NOT NULL, receipt TEXT)"
            )
            policy = json.dumps(POLICY, sort_keys=True)
            db.execute("INSERT OR IGNORE INTO probe_policy VALUES (1, ?)", (policy,))
            stored = db.execute("SELECT body FROM probe_policy WHERE id=1").fetchone()[0]
            if stored != policy:
                raise ValueError("BUDGET_POLICY_MISMATCH")
        self.ledger.chmod(0o600)
        self._responses = self.ledger.with_name(self.ledger.name + ".responses")
        self._responses.mkdir(mode=0o700, exist_ok=True)
        self._responses.chmod(0o700)

    def _total(self, db):
        if db.execute("SELECT body FROM probe_policy WHERE id=1").fetchone() != (
            json.dumps(POLICY, sort_keys=True),
        ):
            raise ValueError("BUDGET_POLICY_MISMATCH")
        total = Decimal(0)
        for raw, receipt in db.execute("SELECT committed, receipt FROM probe_calls"):
            try:
                amount = Decimal(raw)
                if (
                    not amount.is_finite()
                    or amount < 0
                    or amount > Decimal(POLICY["reservation_usd"])
                ):
                    raise ValueError
                if receipt is None and amount != Decimal(POLICY["reservation_usd"]):
                    raise ValueError
                if (
                    receipt is not None
                    and Decimal(json.loads(receipt)["cost_with_vat_reserve_usd"]) != amount
                ):
                    raise ValueError
            except (InvalidOperation, KeyError, TypeError, ValueError):
                raise ValueError("BUDGET_LEDGER_INVALID") from None
            total += amount
        return total

    def summary(self):
        with sqlite3.connect(self.ledger) as db:
            total = self._total(db)
            calls, unsettled = db.execute(
                "SELECT count(*), sum(receipt IS NULL) FROM probe_calls"
            ).fetchone()
        return {
            "limit_usd": POLICY["limit_usd"],
            "calls": calls,
            "unsettled_calls": unsettled or 0,
            "committed_usd": str(total),
        }

    def request_body(self, system, user_json, *, request_id, max_tokens=1024, json_mode=False):
        if (
            not isinstance(system, str)
            or not isinstance(user_json, str)
            or not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 128
            or type(max_tokens) is not int
            or not 1 <= max_tokens <= 4096
            or type(json_mode) is not bool
        ):
            raise ValueError("INVALID_PROBE_REQUEST")
        body = {
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_json},
            ],
            "max_completion_tokens": max_tokens,
            "temperature": 0,
            "stream": False,
            "reasoning_effort": "none",
            "store": False,
            "service_tier": "default",
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if (
            len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
            > WIRE_POLICY["max_request_bytes"]
        ):
            raise ValueError("PROBE_REQUEST_TOO_LARGE")
        return body

    def _post(self, body):
        connection = http.client.HTTPSConnection("api.openai.com", timeout=90)
        try:
            connection.request(
                "POST",
                "/v1/chat/completions",
                body=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(),
                headers={
                    "Authorization": "Bearer " + self._key,
                    "Content-Type": "application/json",
                },
            )
            response = connection.getresponse()
            if response.status != 200:
                raw = response.read(1_048_577)
                if len(raw) <= 1_048_576:
                    try:
                        error = json.loads(raw).get("error", {})
                    except (AttributeError, json.JSONDecodeError, TypeError):
                        error = {}
                    if isinstance(error, dict) and error.get("code") == "insufficient_quota":
                        raise ValueError("OPENAI_INSUFFICIENT_QUOTA")
                raise ValueError(f"OPENAI_HTTP_{response.status}")
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("OPENAI_RESPONSE_TOO_LARGE")
            data = json.loads(raw)
            data["openai_request_id"] = response.getheader("x-request-id")
            return data
        finally:
            connection.close()

    def complete(
        self, system, user_json, *, request_id, max_tokens=1024, json_mode=False, schema_json=None
    ):
        if now() >= PRICE_RECHECK_AT:
            raise ValueError("PRICE_RECHECK_REQUIRED")
        body = self.request_body(
            system, user_json, request_id=request_id, max_tokens=max_tokens, json_mode=json_mode
        )
        validator = (
            Draft202012Validator(json.loads(schema_json), format_checker=FormatChecker())
            if schema_json is not None
            else None
        )
        with sqlite3.connect(self.ledger, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM probe_calls WHERE request_id=?", (request_id,)).fetchone():
                raise ValueError("DUPLICATE_PROBE_REQUEST")
            if self._total(db) + Decimal(POLICY["reservation_usd"]) > Decimal(POLICY["limit_usd"]):
                raise ValueError("BUDGET_EXHAUSTED")
            db.execute(
                "INSERT INTO probe_calls VALUES (?,?,?,NULL)",
                (request_id, canonical_hash(body), POLICY["reservation_usd"]),
            )
        attempts, total_cost, input_tokens, output_tokens = [], Decimal(0), 0, 0
        for attempt in range(2):
            if now() >= PRICE_RECHECK_AT:
                raise ValueError("PRICE_RECHECK_REQUIRED")
            try:
                started = time.monotonic()
                data = self._post(body)
                latency_ms = round((time.monotonic() - started) * 1000, 2)
                path = self._responses / (canonical_hash(f"{request_id}:{attempt}") + ".json")
                with os.fdopen(
                    os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
                ) as stream:
                    json.dump(
                        {"request_id": request_id, "attempt": attempt, "provider_response": data},
                        stream,
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
            except Exception as error:
                from proofops.application.budget import BudgetExceeded

                if isinstance(error, BudgetExceeded):
                    raise
                code = str(error)
                if code not in {
                    f"OPENAI_HTTP_{n}" for n in (400, 401, 403, 404, 429, 500, 502, 503)
                } | {"OPENAI_INSUFFICIENT_QUOTA"}:
                    code = "OPENAI_REQUEST_FAILED"
                raise ValueError(code) from None
            try:
                usage = data["usage"]
                cost = token_cost(usage)
                incoming, outgoing = usage["prompt_tokens"], usage["completion_tokens"]
                choice = data["choices"][0]
                content = choice["message"]["content"]
                if (
                    data["model"] != MODEL
                    or type(incoming) is not int
                    or type(outgoing) is not int
                    or incoming < 0
                    or not 0 <= outgoing <= max_tokens
                    or not cost.is_finite()
                    or cost < 0
                    or not isinstance(content, str)
                    or not isinstance(data["id"], str)
                ):
                    raise ValueError
                if (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0) != 0:
                    raise ValueError
            except (KeyError, TypeError, ValueError, IndexError, InvalidOperation, AttributeError):
                raise ValueError("OPENAI_RECEIPT_INVALID_RESERVATION_RETAINED") from None
            total_cost += cost
            input_tokens += incoming
            output_tokens += outgoing
            attempts.append(
                {
                    "provider_request_id": data["id"],
                    "cost_usd": str(cost),
                    "response_sha256": canonical_hash(data),
                    "latency_ms": latency_ms,
                }
            )
            try:
                parsed = json.loads(content)
                if validator is not None:
                    validator.validate(parsed)
                valid = isinstance(parsed, dict) and choice["finish_reason"] == "stop"
            except (ValueError, TypeError, KeyError):
                valid = False
            except ValidationError:
                valid = False
            if valid or attempt == 1:
                break
        if total_cost > Decimal(POLICY["reservation_usd"]):
            raise ValueError("BUDGET_SETTLEMENT_INVALID")
        receipt = {
            "provider": "openai",
            "request_id": request_id,
            "endpoint": ENDPOINT,
            "model_binding_sha256": canonical_hash(WIRE_POLICY),
            "price_snapshot": WIRE_POLICY,
            "http_request_id": data.get("openai_request_id"),
            "model": MODEL,
            "provider_model": data["model"],
            "provider_request_id": data["id"],
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cost_with_vat_reserve_usd": str(total_cost),
            "cost_source": "official_token_prices_with_vat_reserve",
            "response_sha256": canonical_hash(data),
            "attempts": attempts,
            "schema_valid": valid,
            "response_format": {"type": "json_object"},
        }
        if self.wire_policy_version == 2:
            receipt["wire_policy"] = WIRE_POLICY
            details = usage.get("prompt_tokens_details") or {}
            receipt["cached_tokens"] = details.get("cached_tokens")
            receipt["cache_write_tokens"] = details.get("cache_write_tokens")
        with sqlite3.connect(self.ledger) as db:
            changed = db.execute(
                "UPDATE probe_calls SET committed=?, receipt=? WHERE request_id=? "
                "AND receipt IS NULL AND committed=?",
                (
                    str(total_cost),
                    json.dumps(receipt, sort_keys=True),
                    request_id,
                    POLICY["reservation_usd"],
                ),
            ).rowcount
            if changed != 1:
                raise ValueError("BUDGET_SETTLEMENT_INVALID")
        return {**receipt, "content": content}
