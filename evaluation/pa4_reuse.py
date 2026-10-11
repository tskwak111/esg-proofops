"""No-network reuse of every eligible captured PA4 request through OpenAIProbe."""

import argparse
import json
import sqlite3
from pathlib import Path


def wire_schema(system, expected, candidates=()):
    from proofops.domain.provenance import canonical_hash
    from proofops.domain.rulepacks import canonical_json

    if expected == canonical_hash(None):
        return None
    for candidate in candidates:
        if canonical_hash(candidate) == expected:
            return candidate
    # The extraction adapter supplies this schema separately from the prompt.
    # These are its two declared contracts; the captured exact hash must match.
    for field in ("sentence_ids", "claims"):
        candidate = json.dumps(
            dict(
                type="object",
                properties={field: dict(type="array", items=dict(type="string"))},
                required=[field],
                additionalProperties=False,
            )
        )
        if canonical_hash(candidate) == expected:
            return candidate
    # The actual canonical schema is embedded verbatim in the captured prompt.
    # Require the original receipt's schema byte hash; never infer a substitute.
    decoder = json.JSONDecoder()
    for start, char in enumerate(system):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(system[start:])
        except ValueError:
            continue
        for candidate in (system[start : start + end], canonical_json(value)):
            if canonical_hash(candidate) == expected:
                return candidate
    raise ValueError("PA4_ORIGINAL_SCHEMA_NOT_FOUND")


def main():
    from proofops.adapters.local.openai import OpenAIProbe
    from proofops.adapters.local.tag_store import tagging_settings
    from proofops.domain.provenance import canonical_hash

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.source.resolve(), args.output.resolve()
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    with sqlite3.connect((source / "state.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        snapshot = json.loads(db.execute("SELECT payload FROM run_snapshots").fetchone()[0])
    with sqlite3.connect((source / "live-luna.sqlite3").as_uri() + "?mode=ro", uri=True) as db:
        receipts = [json.loads(v) for (v,) in db.execute("SELECT receipt FROM probe_calls")]
    requests = {
        p.parent.name: json.loads(p.read_text())
        for root in ("extraction-receipts", "tagging-receipts")
        for p in (source / root).rglob("request.json")
    }
    probe = OpenAIProbe("offline-fixture", output / "reuse.sqlite3")
    probe.response_cache_path = source / "model-responses.sqlite3"
    probe.configure_response_policy(snapshot, role="extract")
    schemas = [
        tagging_settings(snapshot, **kw).schema_json
        for kw in ({}, dict(preliminary=True), dict(relation=True))
    ]
    probe._post = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("PA4_REUSE_NETWORK_FORBIDDEN")
    )
    compared, excluded = [], []
    for receipt in receipts:
        if receipt["schema_valid"] is not True:
            excluded.append(
                dict(request_id=receipt["request_id"], reason="schema_invalid_not_reused")
            )
            continue
        request = requests[receipt["request_id"]]
        system = request.get("wire_system", request.get("system_prompt"))
        user = request.get("wire_user_json", request.get("user_json"))
        original = json.loads(
            (
                source
                / "live-luna.sqlite3.responses"
                / (
                    canonical_hash(f"{receipt['request_id']}:{len(receipt['attempts'])-1}")
                    + ".json"
                )
            ).read_text()
        )["provider_response"]
        scope = receipt["response_request"]
        with probe.response_context(role=scope["role"], replica=scope["replica"]):
            result = probe.complete(
                system,
                user,
                request_id="reuse-" + receipt["request_id"],
                max_tokens=request.get("request", request)["max_tokens"],
                json_mode=True,
                schema_json=wire_schema(system, scope["schema_sha256"], schemas),
            )
        assert result["content"] == original["choices"][0]["message"]["content"]
        assert result["response_sha256"] == receipt["response_sha256"]
        assert result["provider_request_id"] == receipt["provider_request_id"]
        assert result["cost_with_vat_reserve_usd"] == "0" and result["response_reuse"]
        compared.append(
            dict(
                request_id=receipt["request_id"],
                role=scope["role"],
                replica=scope["replica"],
                content_sha256=canonical_hash(result["content"]),
                response_reuse=result["response_reuse"],
            )
        )
    result = dict(
        reused=len(compared),
        excluded=excluded,
        requests=compared,
        bytes_identical=True,
        provider_dispatches=0,
        provider=probe.summary(),
        grades_recomputed=False,
    )
    (output / "measurement.json").write_text(json.dumps(result, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k != "requests"}), flush=True)


if __name__ == "__main__":
    main()
