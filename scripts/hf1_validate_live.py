"""One coordinator-authorized diagnostic: five calls maximum, USD 0.05 ceiling.

Dry-run by default. No retries, redirects, tools, production writes or key output.
The companion bundle contains synthetic inputs from the actual v29 renderers.
"""

import argparse
import hashlib
import http.client
import json
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

CASES_SHA256 = "ea4dbbc6ba9057333b65c7b36a66039e8d671a3f6b6f8730abe65a2ab481a680"
ROLES = ("sc1", "preliminary_pb2", "elements_management", "relation", "c3")
CAP = Decimal("0.05")
# Official Luna prices verified 2026-10-16. Use the higher cache-write price
# for every input token, no caching discount, plus the existing 10% reserve.
INPUT_PRICE = Decimal("0.125")
OUTPUT_PRICE = Decimal("0.50")
RESERVE = Decimal("1.10")
PRICE_EXPIRES = datetime(2026, 10, 21, tzinfo=UTC)
MAX_RESPONSE_BYTES = 1048576


def encoded(body):
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()


def plan(cases):
    if tuple(case["role"] for case in cases) != ROLES:
        raise ValueError("ROLE_SET_INVALID")
    reservations = []
    for case in cases:
        body = case["body"]
        if (
            body["model"] != "gpt-6-luna"
            or body["response_format"] != {"type": "json_object"}
            or body["max_completion_tokens"] != 1800
            or body.get("stream") is not False
            or body.get("store") is not False
            or body.get("reasoning_effort") != "none"
            or body.get("service_tier") != "default"
            or set(body)
            - {
                "model",
                "messages",
                "response_format",
                "max_completion_tokens",
                "temperature",
                "top_p",
                "stream",
                "store",
                "reasoning_effort",
                "service_tier",
            }
        ):
            raise ValueError("WIRE_POLICY_INVALID")
        raw = encoded(body)
        if len(raw) > 16384:
            raise ValueError("REQUEST_TOO_LARGE")
        if not any(
            m["role"] == "system" and "json" in m["content"].lower() for m in body["messages"]
        ):
            raise ValueError("JSON_INSTRUCTION_MISSING")
        Draft202012Validator.check_schema(case["local_schema"])
        # Text-only byte bound (at most one token per UTF-8 byte), with 1024
        # additional tokens for chat framing. No hidden reasoning or tool use.
        bound = (
            (Decimal(len(raw) + 1024) * INPUT_PRICE + Decimal(1800) * OUTPUT_PRICE)
            / 1000000
            * RESERVE
        )
        reservations.append(bound)
    if sum(reservations) > CAP:
        raise ValueError("BUDGET_EXCEEDED")
    return reservations


def read_key(path):
    if path:
        raw = Path(path).read_text().strip()
        if raw.startswith("sk-") and "\n" not in raw:
            return raw
        for line in raw.splitlines():
            if line.startswith("OPENAI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("\"'")
                if key:
                    return key
        raise ValueError("KEY_FILE_INVALID")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError("KEY_REQUIRED")
    return key


def send(body, key):
    # http.client has no automatic retry or redirect handling.
    connection = http.client.HTTPSConnection("api.openai.com", timeout=60)
    try:
        connection.request(
            "POST",
            "/v1/chat/completions",
            body=encoded(body),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        )
        response = connection.getresponse()
        raw = response.read(MAX_RESPONSE_BYTES + 1)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("RESPONSE_TOO_LARGE")
        return response.status, raw
    finally:
        connection.close()


def check_response(status, raw, schema):
    result = dict(
        http_status=status, response_sha256=hashlib.sha256(raw).hexdigest(), schema_valid=False
    )
    if status != 200:
        return result | dict(error="HTTP_FAILURE")
    try:
        data = json.loads(raw)
        choice = data["choices"][0]
        if choice["finish_reason"] != "stop" or choice["message"].get("refusal"):
            return result | dict(error="INCOMPLETE_OR_REFUSAL")
        payload = json.loads(choice["message"]["content"])
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
        usage = data["usage"]
        tokens = (usage["prompt_tokens"], usage["completion_tokens"])
        if any(type(n) is not int or n < 0 for n in tokens):
            raise ValueError("USAGE_INVALID")
        estimate = (tokens[0] * INPUT_PRICE + tokens[1] * OUTPUT_PRICE) / 1000000 * RESERVE
        return result | dict(
            schema_valid=True,
            prompt_tokens=tokens[0],
            completion_tokens=tokens[1],
            cost_upper_estimate_usd=str(estimate),
        )
    except Exception:
        # Provider bodies, exception text, and authorization headers are private.
        return result | dict(error="RESPONSE_SCHEMA_OR_USAGE_INVALID")


def run(cases, key, receipt_dir):
    reservations = plan(cases)
    if datetime.now(UTC) >= PRICE_EXPIRES:
        raise ValueError("PRICE_RECHECK_REQUIRED")
    receipt_dir = Path(receipt_dir)
    receipt_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Reserve ALL five worst-case amounts before the first network operation.
    # O_EXCL prevents concurrent/restarted invocations from repeating this run.
    marker = receipt_dir / "HF1-LIVE-ATTEMPT.json"
    fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(
            dict(
                cases_sha256=CASES_SHA256,
                cap_usd=str(CAP),
                reserved_usd=str(sum(reservations)),
                started_at=datetime.now(UTC).isoformat(),
                roles=ROLES,
            ),
            stream,
        )
        stream.flush()
        os.fsync(stream.fileno())
    results = []
    for case, bound in zip(cases, reservations, strict=True):
        try:
            status, raw = send(case["body"], key)
            result = check_response(status, raw, case["local_schema"])
            if result["schema_valid"] and Decimal(result["cost_upper_estimate_usd"]) > bound:
                result.update(schema_valid=False, error="USAGE_EXCEEDS_RESERVATION")
        except Exception:
            result = dict(http_status=None, schema_valid=False, error="TRANSPORT_UNCERTAIN")
        result.update(role=case["role"], reserved_usd=str(bound))
        results.append(result)
        path = receipt_dir / (case["role"] + ".json")
        with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as stream:
            json.dump(result, stream)
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps(result), flush=True)
        if not result["schema_valid"]:
            return 1
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cases", type=Path, default=Path(__file__).with_name("validate_live_cases.json")
    )
    parser.add_argument("--live", action="store_true", help="coordinator only: permits five calls")
    parser.add_argument("--key-file", type=Path, help="read inside container; never printed")
    parser.add_argument("--receipt-dir", type=Path, help="durable one-shot marker directory")
    args = parser.parse_args(argv)
    try:
        raw = args.cases.read_bytes()
        if hashlib.sha256(raw).hexdigest() != CASES_SHA256:
            raise ValueError("CASE_BUNDLE_MISMATCH")
        cases = json.loads(raw)
        reservations = plan(cases)
        if not args.live:
            print(
                json.dumps(
                    dict(
                        status="dry_run",
                        calls=0,
                        planned_calls=len(cases),
                        roles=ROLES,
                        cap_usd=str(CAP),
                        reserved_usd=str(sum(reservations)),
                        cases_sha256=CASES_SHA256,
                    )
                )
            )
            return 0
        if args.receipt_dir is None or not args.receipt_dir.is_absolute():
            raise ValueError("ABSOLUTE_DURABLE_RECEIPT_DIR_REQUIRED")
        return run(cases, read_key(args.key_file), args.receipt_dir)
    except FileExistsError:
        print('{"error":"ALREADY_ATTEMPTED_DO_NOT_RETRY"}')
        return 2
    except Exception:
        print('{"error":"PREFLIGHT_OR_RECEIPT_FAILURE_NO_RETRY"}')
        return 2


if __name__ == "__main__":
    sys.exit(main())
