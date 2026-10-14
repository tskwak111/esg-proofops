"""Offline gate transport fixtures; never imported by a production entrypoint.

Only run-scoped identities in the provider wire are renamed. Document text,
coordinates, offsets, policy/schema hashes and replica identity remain exact.
These substitutions grant no source approval: the image's readers still verify
the freshly uploaded PDF and build all attestations and publication packets.
"""

import hashlib
import itertools
import json
import re
from pathlib import Path

UUID = re.compile(r"^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
# These hashes include freshly allocated document/run/source identities.
IDENTITY_HASHES = {
    "claim_sha256",
    "display_map_sha256",
    "graph_sha256",
    "packet_sha256",
    "retrieval_packet_sha256",
    "sources_sha256",
    "source_sha256",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def normalized_wire(body, replica):
    """Match complete wire, allowing a bijection of fresh identity fields only."""
    identities = {}

    def normalize(value, key=""):
        if isinstance(value, dict):
            return {k: normalize(v, k) for k, v in sorted(value.items())}
        if isinstance(value, list):
            return [normalize(v, key) for v in value]
        if isinstance(value, str):
            if UUID.fullmatch(value) or key == "span_id":
                if value not in identities:
                    identities[value] = f"identity-{len(identities)}"
                return identities[value]
            if key in IDENTITY_HASHES:
                return "fresh-identity-hash"
        return value

    wire = json.loads(json.dumps(body))
    # Decode the actual user wire before renaming: escaping is not semantics.
    wire["messages"][1]["content"] = json.loads(wire["messages"][1]["content"])
    return digest(dict(wire=normalize(wire), replica=replica)), identities


def remap_response(content, old_ids, new_ids):
    reverse = {v: k for k, v in new_ids.items()}

    def remap(value):
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, str) and value in old_ids:
            return reverse[old_ids[value]]
        return value

    # Invalid raw model JSON must reach the real schema guard unchanged.
    try:
        return json.dumps(remap(json.loads(content)), ensure_ascii=False)
    except json.JSONDecodeError:
        return content


def lookup_reply(body, replica, records):
    key, identities = normalized_wire(body, replica)
    if key in records:
        return key, identities, False
    user = json.loads(body["messages"][1]["content"])
    data = user.get("untrusted_document_data", {})
    contexts = data.get("context_blocks", [])
    # UUID tie-breaking can reverse the same nearby extraction contexts after
    # a fresh upload. Sentence-ID replies never select a context_index. Match
    # only permutations of the entire unchanged context set, never subsets,
    # edited quotes, changed quality/geometry, or a different system prompt.
    if replica == 0 and "source_sentences" in data and 1 < len(contexts) <= 4:
        for permutation in itertools.permutations(contexts):
            candidate = json.loads(json.dumps(body))
            modified = json.loads(candidate["messages"][1]["content"])
            modified["untrusted_document_data"]["context_blocks"] = [
                context | dict(context_index=i) for i, context in enumerate(permutation)
            ]
            candidate["messages"][1]["content"] = json.dumps(modified)
            key, identities = normalized_wire(candidate, replica)
            if key in records:
                return key, identities, True
    return None


def compile_replies(states):
    """Read retained request/response pairs, without modifying their artifacts."""
    records = {}
    ocr = {}
    parse = {}
    origins = []
    import sqlite3

    for state in states:
        state = Path(state)
        if state.is_file():
            bundle = json.loads(state.read_text())
            if bundle["schema"] != "predeploy-recorded-transports-v1":
                raise ValueError("Unknown recorded transport bundle")
            for key, values in bundle["llm"].items():
                records.setdefault(key, []).extend(values)
            for key, value in bundle["ocr"].items():
                ocr.setdefault(key, value)
            for key, value in bundle["parse"].items():
                parse.setdefault(key, value)
            origins.extend(bundle["origins"])
            continue
        requests = sorted((state / "extraction-receipts").glob("*/request.json"))
        requests += sorted((state / "tagging-receipts").glob("*/*/*/request.json"))
        for path in requests:
            request = json.loads(path.read_text())
            request = request.get("request", request)
            response_path = path.with_name(
                "raw_response.json"
                if path.parent.parent.name == "extraction-receipts"
                else "response.json"
            )
            if not response_path.exists():
                continue
            response = json.loads(response_path.read_text())
            if "provider_response_json" in response:
                response = json.loads(response["provider_response_json"])
            elif "raw_response_json" in response:
                response = json.loads(response["raw_response_json"])
            if not isinstance(response.get("content"), str):
                continue
            body = dict(
                model="gpt-6-luna",
                messages=[
                    dict(role="system", content=request["system_prompt"]),
                    dict(role="user", content=request["user_json"]),
                ],
                max_completion_tokens=request.get("max_tokens", 1024),
                temperature=0,
                stream=False,
                reasoning_effort="none",
                store=False,
                service_tier="default",
                response_format=dict(type="json_object"),
                top_p=1,
            )
            replica = request.get("replicate_id", 0)
            key, identities = normalized_wire(body, replica)
            records.setdefault(key, []).append(
                dict(
                    identities=identities,
                    content=response["content"],
                    input_tokens=response.get("input_tokens", 1),
                    output_tokens=response.get("output_tokens", 1),
                    cached_tokens=response.get("cached_tokens", 0),
                    response_sha256=hashlib.sha256(response_path.read_bytes()).hexdigest(),
                )
            )
            origins.append(
                dict(path=str(response_path), sha256=records[key][-1]["response_sha256"])
            )
        ledger = state / "upstage.sqlite3"
        if ledger.exists():
            with sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True) as db:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master")}
                if "ocr_calls" in tables:
                    for (encoded,) in db.execute(
                        "SELECT collection FROM ocr_calls WHERE state='collected'"
                    ):
                        collection = json.loads(encoded)
                        raw = bytes.fromhex(collection["response_hex"])
                        ocr.setdefault(
                            collection["manifest"]["png_sha256"],
                            dict(
                                response_hex=raw.hex(),
                                response_sha256=hashlib.sha256(raw).hexdigest(),
                            ),
                        )
        for path in sorted((state / "parse-responses").glob("*-async.json")):
            # Production saves these under the exact submitted PDF SHA.
            parse.setdefault(path.name.removesuffix("-async.json"), json.loads(path.read_text()))
    return dict(
        schema="predeploy-recorded-transports-v1",
        llm=records,
        ocr=ocr,
        parse=parse,
        origins=origins,
    )
