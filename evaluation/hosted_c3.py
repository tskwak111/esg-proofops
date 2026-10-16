"""Current hosted C3 side publication; no stored replies are loaded in production."""

import json
import os
from dataclasses import asdict
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

from proofops.adapters.local.c3_processing import prepare_case, process_case
from proofops.adapters.local.c3_transport import authenticate_response
from proofops.adapters.local.run_store import LocalSQLiteRunStore
from proofops.adapters.parsing.opendataloader import OpenDataLoaderParser
from proofops.application.ingest.graph_fusion import ParserProfile, SourceArtifact
from proofops.application.tagging import fact_assembly_c3_v2 as c3
from proofops.domain.rulepacks import RulePackSnapshot


def publish_current(store, job, state, policy, factory, *, simulated=False):
    """Try only the approved tenant/original/rulepack after the regular pipeline.

    The original is parsed again with current run IDs. Exact source fingerprint,
    source attestation and three brokered receipts remain mandatory. Other
    reports and any mismatch return without a model dispatch or promotion.
    """
    if policy.get("direct_certification_policy") != c3.POLICY:
        return dict(status="disabled", published=False)
    selected = json.loads(job["pages"])
    if 36 not in selected or job["tenant_id"] != c3.REVIEWED_SOURCE_IDENTITY["tenant_id"]:
        return dict(status="outside_approved_source", published=False)
    manifest = json.loads((state / "pilot.json").read_text())
    snapshot = LocalSQLiteRunStore(state / "state.sqlite3").snapshot(
        job["tenant_id"], manifest["run_id"]
    )
    pack = RulePackSnapshot(**snapshot["rulepack"])
    if pack.sha256 != c3.REVIEWED_SOURCE_IDENTITY["rulepack_sha256"]:
        return dict(status="rulepack_mismatch", published=False)
    with store.transaction(readonly=True) as db:
        document = dict(store._document(db, job["tenant_id"], job["document_id"]))
    directory = store.document_dir(job["tenant_id"], job["document_id"])
    original = store.analysis_source(directory, document).read_bytes()
    digest = sha256(original).hexdigest()
    if digest != c3.REVIEWED_SOURCE_IDENTITY["original_sha256"]:
        return dict(status="outside_approved_source", published=False)

    def sid(value):
        return str(uuid5(NAMESPACE_URL, job["run_id"] + ":C3-v2:" + value))

    source = SourceArtifact(
        job["tenant_id"], job["document_id"], sid("version"), digest, "current-original", original
    )
    parser = OpenDataLoaderParser(state / "bounded-c3-parser")
    graph = parser.parse(
        source,
        ParserProfile(
            sid("manifest"),
            physical_pages=(36,),
            java_executable=os.environ.get("PROOFOPS_TEST_JAVA", "java"),
            timeout_seconds=90,
            local_resource_policy="selected-pdf-h1-v1",
        ),
        tenant_id=job["tenant_id"],
    )
    from proofops.application.fxh_policy import enabled as fxh_enabled

    diagnostics = {} if fxh_enabled(policy) else None
    case = prepare_case(graph, original, pack, run_id=manifest["run_id"], diagnostics=diagnostics)
    if case is None:
        result = dict(status="current_source_unresolved", published=False)
        if diagnostics is not None:
            result["fxh_source_diagnostics"] = diagnostics
        return result
    probe = factory("", state / "luna.sqlite3", wire_policy_version=2)

    def transport(request):
        probe.configure_response_policy(request["snapshot"], role="elements")
        with probe.response_context(role="elements", replica=request["replica"]):
            response = probe.complete(
                request["system"],
                request["user_json"],
                request_id=request["id"],
                max_tokens=request["max_tokens"],
                json_mode=True,
                schema_json=request["schema_json"],
            )
        if policy.get("s5_c3_response_binding") and response.get("schema_valid") is not True:
            raise ValueError("C3_CURRENT_RESPONSE_INVALID")
        if not simulated:
            response = authenticate_response(request, response, probe)
        return response | dict(simulated=simulated)

    result = process_case(
        case, original, output=state / "bounded-c3", transport=transport, analysis_policy=policy
    )
    # Durable provenance is retained in the immutable C3 tag revision, not a
    # precomputed grade imported into the regular claim store.
    outcome = dict(
        status="published" if result["published"] else "needs_review",
        published=result["published"],
        receipt_sha256=result["receipt"]["receipt_sha256"],
        current_claim_id=case["context"].claim.claim_id,
        parser_sha256=sha256(json.dumps(asdict(graph), sort_keys=True).encode()).hexdigest(),
    )
    if "cf2_receipt_path" in result:
        outcome.update(
            cf2_receipt_path=result["cf2_receipt_path"],
            cf2_unresolved=result["receipt"]["unresolved"],
        )
    return outcome
