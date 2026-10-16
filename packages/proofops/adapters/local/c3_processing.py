"""DEC-68 bounded current-run C3 path. The caller owns transport authorization."""

import json
import os
from dataclasses import asdict
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import NAMESPACE_URL, uuid5

from proofops.adapters.local.c3_publication import LocalC3Publication
from proofops.adapters.local.c3_source import attest, replay
from proofops.adapters.local.evidence_search import LocalEvidenceSearch
from proofops.application.claims import Claim, ExtractionProfile, ExtractionReceipt
from proofops.application.evidence.binding import ClaimContext
from proofops.application.evidence.retrieval import (
    freeze_packet,
    freeze_track_packet,
    retrieve_evidence,
)
from proofops.application.evidence.span_citations import verify_source_ref
from proofops.application.tagging import fact_assembly_c3_v2 as c3
from proofops.application.tagging.c3_request_binding import (
    CF2_POLICY,
    current_request,
    request_binding,
    response_binding_policy,
)
from proofops.application.tagging.c3_request_binding import SYSTEM as SYSTEM
from proofops.application.tagging.tracks import TrackCandidate
from proofops.domain.provenance import canonical_hash


def prepare_case(graph, source, rulepack, *, run_id, diagnostics=None):
    def unresolved(code, records=()):
        if diagnostics is not None:
            diagnostics.update(
                code=code,
                source_records=[dict(status=r["status"], reason=r.get("reason")) for r in records],
            )
        return None

    approved = c3.REVIEWED_SOURCE_IDENTITY
    if (
        graph.tenant_id != approved["tenant_id"]
        or graph.source_sha256 != approved["original_sha256"]
        or rulepack.tenant_id != graph.tenant_id
        or rulepack.sha256 != approved["rulepack_sha256"]
    ):
        return unresolved("C3_SOURCE_IDENTITY_MISMATCH")
    statement = approved["statement_spans"][0]
    matches = []
    for block in graph.blocks:
        if block.kind != "paragraph" or block.page_num != 36 or block.winner is None:
            continue
        a, b = statement["char_start"], statement["char_end"]
        if block.raw_text[a:b] == approved["normalized_exact_claim"]:
            matches.append(block.source_ref(normalized_char_start=a, normalized_char_end=b))
    if len(matches) != 1:
        return unresolved("C3_STATEMENT_MATCH_UNRESOLVED")
    refs = matches
    headers = [
        block
        for block in graph.blocks
        if block.page_num == 36
        and block.kind == "paragraph"
        and block.winner is not None
        and "지속가능경영보고서 2025" in block.normalized_text
    ]
    if len(headers) != 1:
        return unresolved("C3_YEAR_HEADER_UNRESOLVED")
    start = headers[0].normalized_text.index("2025")
    refs.append(headers[0].source_ref(normalized_char_start=start, normalized_char_end=start + 4))
    source_receipt = attest(graph, source, refs, tenant_id=graph.tenant_id, run_id=run_id)
    if any(
        record["status"] != "verified"
        for record in source_receipt["claim_source_receipt"]["records"]
    ):
        return unresolved(
            "C3_SOURCE_ATTESTATION_UNRESOLVED", source_receipt["claim_source_receipt"]["records"]
        )
    graph = replay(source_receipt, graph, source, tenant_id=graph.tenant_id, run_id=run_id)
    refs = tuple(verify_source_ref(r, graph, tenant_id=graph.tenant_id) for r in refs)
    if any(ref.verification_state != "verified" for ref in refs):
        return unresolved("C3_SOURCE_REPLAY_UNRESOLVED")
    claim = Claim(
        str(uuid5(NAMESPACE_URL, run_id + ":" + c3.REVIEWED_SOURCE_FINGERPRINT_SHA256)),
        graph.tenant_id,
        graph.document_version_id,
        graph.parse_manifest_id,
        graph.source_sha256,
        refs[0].quote,
        (refs[0],),
        "verified",
        (),
        ExtractionReceipt(
            refs[0].source_id,
            canonical_hash(asdict(refs[0])),
            None,
            None,
            ExtractionProfile(c3.POLICY_HASH, c3.POLICY_HASH, rulepack.sha256, False),
            "current_run_reviewed_source_selection",
        ),
    )
    search = LocalEvidenceSearch(
        graph, tenant_id=graph.tenant_id, pages=[36], index_generation="C3-v2-current"
    )
    original = retrieve_evidence(
        claim,
        graph,
        search,
        tenant_id=graph.tenant_id,
        run_id=run_id,
        index_generation="C3-v2-current",
        rulepack=rulepack,
        document_context={},
        token_counter=lambda text: len(text) // 3,
    )
    packet = freeze_track_packet(
        original, track=TrackCandidate(claim, "management", None), rulepack=rulepack
    )
    packet = freeze_packet(
        {k: v for k, v in packet.to_dict().items() if k != "packet_sha256"}
        | dict(c2_sources=[asdict(r) for r in refs])
    )
    return dict(
        context=ClaimContext(claim, {}),
        graph=graph,
        rulepack=rulepack,
        packet=packet,
        original_packet=original,
        source_receipt=source_receipt,
    )


def process_case(case, source, *, output, transport, analysis_policy):
    """Three current receipts → source fingerprint → Python → immutable publication.

    Saved replies retain their origin and can only produce candidates. Public
    confirmation requires the trusted transport's authenticated fresh receipt.
    """
    claim, graph, packet = case["context"].claim, case["graph"], case["packet"]
    identity = dict(
        tenant_id=claim.tenant_id,
        document_version_id=claim.document_version_id,
        original_sha256=graph.source_sha256,
        parse_manifest_id=graph.parse_manifest_id,
        graph_sha256=canonical_hash(asdict(graph)),
        claim_id=claim.claim_id,
        claim_sha256=canonical_hash(asdict(claim)),
        claim_revision=claim.revision,
        packet_sha256=packet.packet_sha256,
        rulepack_sha256=case["rulepack"].sha256,
    )
    votes = []
    for replica in (1, 2, 3):
        request = current_request(
            identity, claim.quote, packet.to_dict()["c2_sources"], analysis_policy, replica
        )
        response = transport(request)
        if not response.get("schema_valid") or type(response.get("simulated")) is not bool:
            raise ValueError("C3_CURRENT_RESPONSE_INVALID")
        provider_response = {
            k: v
            for k, v in response.items()
            if k
            not in (
                "transport_receipt",
                "simulated",
            )
        }
        vote = dict(
            identity=identity,
            replicate_id=replica,
            request_id=request["id"],
            request_sha256=canonical_hash(request),
            provider_request_id=response["provider_request_id"],
            cache_identity=response.get("response_request"),
            response_sha256=canonical_hash(provider_response),
            provider_response=provider_response,
            transport_receipt=response.get("transport_receipt"),
            provider=response["provider"],
            simulated=response["simulated"],
            model_sha256=response["model_binding_sha256"],
            prompt_sha256=request_binding(request)["prompt_sha256"],
            raw=json.loads(response["content"]),
        )
        if "saved_response_origin" in response:
            vote["saved_response_origin"] = response["saved_response_origin"]
        vote["raw_sha256"] = canonical_hash(vote["raw"])
        vote["vote_sha256"] = canonical_hash(vote)
        votes.append(vote)
    receipt = c3.assemble(
        votes,
        analysis_policy=analysis_policy,
        **{k: case[k] for k in ("context", "graph", "packet", "rulepack")},
    )
    result = dict(receipt=receipt.to_dict(), published=False)
    if response_binding_policy(analysis_policy) == CF2_POLICY:
        # A diagnostic receipt is not a published revision. Save both accepted
        # and rejected assemblies before either the review return or DB writes.
        output = Path(output)
        directory = output / "cf2-receipts"
        target = directory / (receipt.receipt_sha256 + ".json")
        if output.is_symlink() or directory.is_symlink() or target.is_symlink():
            raise ValueError("C3_UNSAFE_ARTIFACT_PATH")
        directory.mkdir(parents=True, exist_ok=True)
        content = json.dumps(result["receipt"], ensure_ascii=False, sort_keys=True)
        with NamedTemporaryFile(mode="w", dir=directory, encoding="utf-8") as staged:
            staged.write(content)
            staged.flush()
            os.fsync(staged.fileno())
            try:
                os.link(staged.name, target)  # Atomic create-only; no partial receipt on retry.
            except FileExistsError:
                if target.read_text() != content:
                    raise ValueError("CF2_RECEIPT_CONFLICT") from None
        result["cf2_receipt_path"] = str(target.relative_to(output))
    if not receipt.to_dict()["public_auto_confirmed"]:
        return result
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    publication = LocalC3Publication(output)
    publication.initialize(
        case,
        receipt,
        source=source,
        parser_artifact=dict(
            candidates=[asdict(c) for c in graph.candidates],
            issues=[asdict(i) for i in graph.issues],
        ),
    )
    manifest = dict(
        tenant_id=claim.tenant_id,
        run_id=packet.to_dict()["run_id"],
        claim_id=claim.claim_id,
        publication_profile=c3.PROFILE,
        selected_pages=[36],
    )
    target = output / "pilot.json"
    content = json.dumps(manifest, sort_keys=True)
    if target.exists() and target.read_text() != content:
        raise ValueError("C3_CURRENT_MANIFEST_CONFLICT")
    target.write_text(content)
    result.update(
        published=True,
        result=publication.result(claim.tenant_id, packet.to_dict()["run_id"], claim.claim_id),
    )
    return result
