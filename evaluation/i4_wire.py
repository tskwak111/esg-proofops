"""Render full authenticated retained requests without a provider dispatch."""

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from proofops.adapters.local.glyph_display_text import GlyphDisplayCatalog
from proofops.adapters.local.openai import OpenAIProbe
from proofops.adapters.local.tag_store import tagging_settings
from proofops.application.preflight import Check, Preflight
from proofops.application.tagging.finals_i4 import K4_ELEMENTS, K4_PRELIMINARY
from proofops.application.tagging.k4_contract import RESPONSE_POLICY
from proofops.domain.provenance import canonical_hash
from proofops_agent.upstage_preliminary import UpstagePreliminaryTransport
from proofops_agent.upstage_tagging import UpstageTaggingTransport

from evaluation.k2_replay import historical_graph
from evaluation.pa9_source_gate import fixture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(exist_ok=True, parents=True)
    base = args.root / "outputs/agent-results/R108-redesign/lab/perf/I3/stage-B-complete"
    rows = []
    probe = OpenAIProbe("offline-wire-not-a-key", args.output / "unused.sqlite3")
    for company in ("naver", "kia"):
        state = base / company
        graph, source, _, snapshot, parse = fixture(state)
        graph = historical_graph(
            graph, parse, json.loads((state / "extract-checkpoint.json").read_text())
        )
        catalog = GlyphDisplayCatalog(graph, source)
        for path in sorted((state / "tagging-receipts").rglob("request.json")):
            record = json.loads(path.read_text())
            role = path.parents[1].name
            if role not in ("preliminary", "elements"):
                continue
            request = record["request"]
            preliminary = role == "preliminary"
            settings = replace(
                tagging_settings(snapshot, preliminary=preliminary),
                system_prompt=K4_PRELIMINARY if preliminary else K4_ELEMENTS,
            )
            transport = object.__new__(
                UpstagePreliminaryTransport if preliminary else UpstageTaggingTransport
            )
            transport._settings, transport._tenant = settings, graph.tenant_id
            transport._display_catalog = catalog
            auth = record["authorization"]
            approval = Preflight(
                auth["ready"],
                tuple(Check(**c) for c in auth["checks"]),
                auth["binding_sha256"],
                auth["checked_at"],
            )
            transport._authorize = lambda *a: approval
            request["binding"] = asdict(settings.binding)
            user = json.loads(request["user_json"])
            if preliminary:
                user["preliminary_response_policy"] = RESPONSE_POLICY
                user["prompt_sha256"] = canonical_hash(K4_PRELIMINARY)
                request["packet_sha256"] = canonical_hash(user)
                request["system_prompt"] = settings.rendered_system
            else:
                data = user["untrusted_document_data"]
                data["tagging_response_policy"] = RESPONSE_POLICY
                classification = json.loads(
                    request["system_prompt"].split(
                        "Validated classification; tag only its elements: ", 1
                    )[1]
                )
                request["system_prompt"] = settings.system_for_track(
                    classification["track"], classification["safe_harbor_category"]
                )
            request["user_json"] = json.dumps(user)
            system, wire, _, _, raw_schema = transport._wire_request(request)
            schema = json.loads(raw_schema)
            assert not {"claim_id", "packet_sha256", "replicate_id"} & set(schema["properties"])
            assert "exactly claim_id" not in system
            assert "preliminary_response_policy" not in json.loads(wire)
            assert "tagging_response_policy" not in json.loads(wire)["untrusted_document_data"]
            body = probe.request_body(
                system,
                wire,
                request_id=request["request_id"],
                max_tokens=request["max_tokens"],
                json_mode=True,
            )
            rows.append(
                dict(
                    company=company,
                    role=role,
                    original=str(path),
                    body_bytes=len(
                        json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
                    ),
                    system_sha256=canonical_hash(system),
                    schema_sha256=canonical_hash(schema),
                )
            )
    result = dict(records=rows, max_body_bytes=max(r["body_bytes"] for r in rows), provider_calls=0)
    (args.output / "wire.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(dict(requests=len(rows), max_body_bytes=result["max_body_bytes"])))


if __name__ == "__main__":
    main()
