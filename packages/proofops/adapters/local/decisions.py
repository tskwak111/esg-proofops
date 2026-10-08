"""Budgeted Decisions HTTP and immutable replay, without automatic retries.

OpenAI owns a new USD3 ledger; JEV shares the existing OpenRouter probe ledger.
Every new call also reserves against the existing R108 USD10 cumulative record.
Uncertain calls retain reservations. Credentials are loaded only at dispatch.
"""

from __future__ import annotations

import fcntl
import http.client
import json
import os
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path

from proofops.adapters.local.openrouter import POLICY as OR_POLICY
from proofops.adapters.local.openrouter import OpenRouterProbe
from proofops.application.tagging.decisions import MODELS, POLICY, validate_answers
from proofops.domain.provenance import canonical_hash

OPENAI_POLICY = dict(
    provider="openai",
    model="gpt-6-luna",
    limit_usd="3.00",
    reservation_usd="0.02",
    max_request_bytes=65536,
    price_input_per_million="0.10",
    price_output_per_million="0",
    pricing_source="https://developers.openai.com/api/docs/guides/decisions",
    captured_at="2026-10-08",
    vat_reserve="1.10",
)


def _write_private(path, data):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
        json.dump(data, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


def load_key(provider, project):
    name = "OPENAI_API_KEY" if provider == "openai" else "OPENROUTER_API_KEY"
    try:
        lines = (Path(project) / f".env.{provider}.local").read_text().splitlines()
        for line in lines:
            if line.strip().startswith(name + "="):
                value = line.split("=", 1)[1].strip().strip('"').strip("'")
                if value and not any(c.isspace() for c in value):
                    return value
    except OSError:
        pass
    raise ValueError("DECISION_KEY_UNAVAILABLE")


class DecisionProbe:
    def __init__(self, provider, ledger, *, r108_spend, key_loader, historical_ledgers=()):
        if provider not in MODELS or not callable(key_loader):
            raise ValueError("DECISION_PROVIDER_INVALID")
        self.provider, self.model = provider, MODELS[provider]["model"]
        self.ledger, self.spend = Path(ledger), Path(r108_spend)
        self.key_loader, self.historical_ledgers = key_loader, tuple(historical_ledgers)
        self.ledger.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.policy = OPENAI_POLICY if provider == "openai" else OR_POLICY
        if provider == "openrouter":
            # Constructor checks the existing immutable policy. No new JEV cap/reset.
            self._openrouter = OpenRouterProbe("decision-ledger-validation", self.ledger)
        else:
            with sqlite3.connect(self.ledger) as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS probe_policy (id INTEGER PRIMARY KEY, body TEXT)"
                )
                db.execute(
                    "CREATE TABLE IF NOT EXISTS probe_calls (request_id TEXT PRIMARY KEY, "
                    "signature TEXT NOT NULL, committed TEXT NOT NULL, receipt TEXT)"
                )
                db.execute(
                    "INSERT OR IGNORE INTO probe_policy VALUES (1,?)",
                    (json.dumps(self.policy, sort_keys=True),),
                )
                self._total(db)
        self.ledger.chmod(0o600)
        self.responses = self.ledger.with_name(self.ledger.name + ".decisions")
        self.responses.mkdir(mode=0o700, exist_ok=True)
        self.responses.chmod(0o700)

    def _total(self, db):
        if self.provider == "openrouter":
            return self._openrouter._total(db)
        if db.execute("SELECT body FROM probe_policy WHERE id=1").fetchone() != (
            json.dumps(self.policy, sort_keys=True),
        ):
            raise ValueError("BUDGET_POLICY_MISMATCH")
        total = Decimal(0)
        for committed, raw in db.execute("SELECT committed,receipt FROM probe_calls"):
            amount = Decimal(committed)
            if (
                not amount.is_finite()
                or not 0 <= amount <= Decimal("0.02")
                or (raw is None and amount != Decimal("0.02"))
                or (
                    raw is not None
                    and Decimal(json.loads(raw)["cost_with_vat_reserve_usd"]) != amount
                )
            ):
                raise ValueError("BUDGET_LEDGER_INVALID")
            total += amount
        return total

    def _shared(self, request_id, signature, amount, *, settle=False):
        # Crash ordering is conservative: shared reservation first, provider second;
        # provider settlement first, shared release second. Orphans retain money.
        self.spend.parent.mkdir(parents=True, exist_ok=True)
        with self.spend.with_suffix(".decisions.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                data = json.loads(self.spend.read_text())
                limit, total = Decimal(data["limit_usd"]), Decimal(data["cumulative_usd"])
                if (
                    not limit.is_finite()
                    or not total.is_finite()
                    or not 0 < limit <= 10
                    or total < 0
                ):
                    raise ValueError("R108_BUDGET_INVALID")
                entries = data.setdefault("decision_reservations", {})
                key = self.provider + ":" + request_id
                prior = entries.get(key)
                if prior is not None and prior["signature"] != signature:
                    raise ValueError("DECISION_REQUEST_MISMATCH")
                if not settle and prior is not None:
                    raise ValueError("DECISION_PENDING_CALL")
                if settle and (prior is None or prior["state"] != "reserved"):
                    raise ValueError("DECISION_PENDING_CALL")
                delta = amount - Decimal(prior["committed_usd"]) if settle else amount
                pending = Decimal(0)
                for path in self.historical_ledgers:
                    if not Path(path).is_file():
                        raise ValueError("R108_BUDGET_HISTORY_UNAVAILABLE")
                    with sqlite3.connect(
                        Path(path).resolve().as_uri() + "?mode=ro", uri=True
                    ) as db:
                        for rid, raw in db.execute(
                            "SELECT request_id,committed FROM probe_calls WHERE receipt IS NULL"
                        ):
                            if not any(
                                k.endswith(":" + rid)
                                and Path(entry["ledger"]).resolve() == Path(path).resolve()
                                for k, entry in entries.items()
                            ):
                                value = Decimal(raw)
                                if not value.is_finite() or value < 0:
                                    raise ValueError("R108_BUDGET_INVALID")
                                pending += value
                if not settle and total + delta + pending > limit:
                    raise ValueError("R108_BUDGET_EXHAUSTED")
                entries[key] = dict(
                    signature=signature,
                    committed_usd=str(amount),
                    state="settled" if settle else "reserved",
                    ledger=str(self.ledger),
                )
                data["cumulative_usd"] = str(total + delta)
                tmp = self.spend.with_suffix(".decisions.tmp")
                with tmp.open("w") as stream:
                    json.dump(data, stream, sort_keys=True, indent=2)
                    stream.flush()
                    os.fsync(stream.fileno())
                tmp.replace(self.spend)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def request_body(self, state, questions):
        if not isinstance(state, dict) or not isinstance(questions, dict) or not questions:
            raise ValueError("DECISION_REQUEST_INVALID")
        if self.provider == "openai":
            body = dict(
                model=self.model,
                input=json.dumps(state, ensure_ascii=False, sort_keys=True),
                questions=[
                    dict(
                        name=k,
                        type="choice",
                        instructions=q["instructions"],
                        choices=[dict(value=v, description=d) for v, d in q["criteria"].items()],
                    )
                    for k, q in questions.items()
                ],
            )
        else:
            body = dict(model=self.model, state=state, questions=questions)
        size = len(
            json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
        )
        if size > 65536:
            raise ValueError("PROBE_REQUEST_TOO_LARGE")
        return body

    def _post(self, body):
        host, path = (
            ("api.openai.com", "/v1/decisions")
            if self.provider == "openai"
            else ("openrouter.ai", "/api/alpha/decisions")
        )
        secret = self.key_loader()
        connection = http.client.HTTPSConnection(host, timeout=60)
        try:
            connection.request(
                "POST",
                path,
                body=json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode(),
                headers={"Authorization": "Bearer " + secret, "Content-Type": "application/json"},
            )
            response = connection.getresponse()
            if response.status != 200:
                raise ValueError("DECISION_HTTP_" + str(response.status))
            raw = response.read(1_048_577)
            if len(raw) > 1_048_576:
                raise ValueError("DECISION_RESPONSE_TOO_LARGE")
            return json.loads(raw.decode().replace(secret, "[REDACTED]"))
        finally:
            connection.close()

    def decide(
        self, state, questions, *, request_id, pins=None, authorize=None, before_dispatch=None
    ):
        body = self.request_body(state, questions)
        if not isinstance(request_id, str) or not 1 <= len(request_id) <= 128:
            raise ValueError("DECISION_REQUEST_INVALID")
        signature = canonical_hash(dict(body=body, policy=POLICY, pins=pins))
        with sqlite3.connect(self.ledger, timeout=30) as db:
            db.execute("BEGIN IMMEDIATE")
            self._total(db)
            prior = db.execute(
                "SELECT signature,receipt FROM probe_calls WHERE request_id=?", (request_id,)
            ).fetchone()
            if prior:
                if prior[0] != signature:
                    raise ValueError("DECISION_REQUEST_MISMATCH")
                if prior[1] is None:
                    raise ValueError("DECISION_PENDING_CALL")
                receipt = json.loads(prior[1])
                if receipt.get("response_file") != canonical_hash(request_id) + ".json":
                    raise ValueError("DECISION_RECEIPT_MISMATCH")
                saved_request = json.loads(
                    (self.responses / (canonical_hash(request_id) + ".request.json")).read_text()
                )
                if saved_request != dict(body=body, policy=POLICY, pins=pins):
                    raise ValueError("DECISION_RECEIPT_MISMATCH")
                response = json.loads((self.responses / receipt["response_file"]).read_text())
                if (
                    receipt.get("model") != self.model
                    or receipt.get("provider") != self.provider
                    or receipt.get("pins") != pins
                    or receipt.get("threshold") != POLICY["threshold"]
                    or receipt.get("questions") != questions
                    or receipt.get("response_sha256") != canonical_hash(response)
                    or receipt.get("policy_sha256") != canonical_hash(POLICY)
                    or receipt.get("request_sha256") != signature
                    or receipt.get("questions_sha256") != canonical_hash(questions)
                ):
                    raise ValueError("DECISION_RECEIPT_MISMATCH")
                return dict(answers=validate_answers(response, questions), receipt=receipt)
            if authorize is not None:
                authorize()
            if self._total(db) + Decimal("0.02") > Decimal(self.policy["limit_usd"]):
                raise ValueError("BUDGET_EXHAUSTED")
            self._shared(request_id, signature, Decimal("0.02"))
            db.execute(
                "INSERT INTO probe_calls VALUES (?,?,?,NULL)", (request_id, signature, "0.02")
            )
        _write_private(
            self.responses / (canonical_hash(request_id) + ".request.json"),
            dict(body=body, policy=POLICY, pins=pins),
        )
        if before_dispatch is not None:
            before_dispatch()
        try:
            started = time.monotonic()
            response = self._post(body)
        except Exception:
            raise ValueError("DECISION_REQUEST_FAILED") from None
        filename = canonical_hash(request_id) + ".json"
        _write_private(self.responses / filename, response)
        try:
            usage = response["usage"]
            incoming, outgoing = usage["input_tokens"], usage["output_tokens"]
            if (
                type(incoming) is not int
                or not 0 <= incoming <= 66560
                or type(outgoing) is not int
                or not 0 <= outgoing <= 4096
                or response["model"]
                not in (
                    (self.model, "typesafe/jev-1.13-20260917")
                    if self.provider == "openrouter"
                    else (self.model,)
                )
            ):
                raise ValueError
            cost = (
                Decimal(incoming) * Decimal("0.10") / 1_000_000
                if self.provider == "openai"
                else Decimal(str(usage["cost"]))
            )
            cost *= Decimal("1.10")
            if not cost.is_finite() or not 0 <= cost <= Decimal("0.02"):
                raise ValueError
        except (KeyError, ValueError, TypeError, InvalidOperation):
            raise ValueError("DECISION_USAGE_INVALID_RESERVATION_RETAINED") from None
        receipt = dict(
            provider=self.provider,
            model=self.model,
            provider_model=response["model"],
            provider_request_id=response.get("id") or signature,
            input_tokens=incoming,
            output_tokens=outgoing,
            latency_ms=round((time.monotonic() - started) * 1000),
            cost_with_vat_reserve_usd=str(cost),
            request_sha256=signature,
            response_sha256=canonical_hash(response),
            response_file=filename,
            policy_sha256=canonical_hash(POLICY),
            questions_sha256=canonical_hash(questions),
            questions=questions,
            pins=pins,
            threshold=POLICY["threshold"],
            endpoint=MODELS[self.provider]["endpoint"],
            cost_source="usage_tokens_official_price_estimate"
            if self.provider == "openai"
            else "usage.cost",
        )
        with sqlite3.connect(self.ledger) as db:
            changed = db.execute(
                "UPDATE probe_calls SET committed=?,receipt=? WHERE request_id=? "
                "AND receipt IS NULL",
                (str(cost), json.dumps(receipt, sort_keys=True), request_id),
            ).rowcount
            if changed != 1:
                raise ValueError("DECISION_PENDING_CALL")
        self._shared(request_id, signature, cost, settle=True)
        return dict(answers=validate_answers(response, questions), receipt=receipt)
