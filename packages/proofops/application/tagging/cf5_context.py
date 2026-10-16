"""Opt-in complete local interpretation and unanimous preliminary headers.

No source promotion, new dimension source, track assignment, or grade rule.
Historical K5 packets and V3 prompts remain byte-identical.
"""

from copy import deepcopy
from dataclasses import asdict

from proofops.application.ingest.k5_context import _check
from proofops.application.tagging.v3_dec92 import PRELIMINARY as V3_PRELIMINARY
from proofops.domain.provenance import canonical_hash

PROFILE = "cf5_complete_local_context_v1"
GUIDANCE = """
CF5 local context: source 0 remains the focal atomic assertion. Read the complete
containing paragraph/table in context_blocks to distinguish an existing activity
from a future promise. Context is interpretation-only, never an additional
dimension/element citation. Its verification state is not upgraded by inclusion.
For a table, interpret only the focal row and its own column headers; other rows
are not this claim. Preserve target, forecast, capacity, unit and period markers.
A named activity explicitly underway (including an ongoing review of a named
project) can be management without claiming the project is finished. A company's
future intention to start that activity stays goal. A purpose describing an
already operating system is not by itself a new future commitment. A label alone
does not prove operation; a number or capacity does not prove achieved output.
An aspirational policy list or slogan (support, improve, pursue) without a literal
assertion of implementation does not prove current activity. A future-dated
reduction or transition commitment remains a target even when described as being
pursued. Do not use a present-tense pursuit verb to erase its future deadline.
If that explicit future commitment and a current activity cannot be separated
within the focal quote, keep track null for splitting/review.
Read the entire governing predicate: a trailing future plan can govern an earlier
connective fragment. Do not discard that future clause to recover a current track.
If independent present/future assertions remain mixed in the focal quote, keep
track null for splitting/review. Never force a track to avoid a hold. Retain the
DEC-92/93 category rules: a selected future company goal requires forward_looking;
no legal/grade mapping follows. Keep uncertainty and all literal-source guards.
""".strip()
PRELIMINARY = V3_PRELIMINARY + "\n" + GUIDANCE
POLICY = dict(
    profile=PROFILE,
    context=(
        "whole-own-paragraph-or-table; retain-existing-context-including-captions-and-footnotes"
    ),
    bounds="existing-prose-and-table-context-bounds; fail-closed-if-required-context-does-not-fit",
    authority="interpretation-only; exact-raw-spans; candidate-stays-candidate",
    transport="no-partial-context-trimming; packet-and-context-hash-pinned",
    consensus="three-independent-valid-matching-track-category-votes; no-majority",
    preliminary_sha256=canonical_hash(PRELIMINARY),
)


def enabled(configured):
    policy = configured.get("cf5_context_policy")
    if policy is None:
        return False
    if policy != POLICY or configured.get("cf5_context_policy_sha256") != canonical_hash(POLICY):
        raise ValueError("CF5_CONTEXT_POLICY_MISMATCH")
    return True


def header_agreed(headers):
    return (
        len(headers) == 3
        and headers[0][0] is not None
        and all(item == headers[0] for item in headers)
    )


def preserve_context(packet, claim, graph):
    """Widen only interpretation of the focal block; never numbered sources.

    The full table retains literal row/header/footnote text without fabricating an
    axis association. Larger blocks stay held rather than losing a future clause.
    """
    from proofops.application.tagging.preliminary import _sources

    _sources(claim, graph, graph.tenant_id, allow_unverified=True)
    result = deepcopy(packet)
    data = result["untrusted_document_data"]
    by_id = {b.source_id: b for b in graph.blocks}
    own_ids = {r.source_id for r in claim.source_refs}
    entries = []
    for source_id in dict.fromkeys(r.source_id for r in claim.source_refs):
        block = by_id[source_id]
        checked = _check(block.source_ref(), graph)
        if checked.verification_state == "rejected":
            raise ValueError("CF5_CONTEXT_SOURCE_REJECTED")
        entries.append(
            dict(
                context_index=len(entries),
                role="parent_paragraph",
                source_id=source_id,
                page_num=checked.page_num,
                quality="verified" if checked.verification_state == "verified" else "unverified",
                text=checked.quote,
                source_ref={k: v for k, v in asdict(checked).items() if k != "quote"},
            )
        )
    # Keep already selected captions, footnotes, origin headers and continuations.
    # A future-plan caption can govern the focal row even outside its own block.
    # Widening a focal block must not silently discard that existing qualifier.
    entries.extend(entry for entry in data["context_blocks"] if entry["source_id"] not in own_ids)
    limits = result["context_policy"]
    # Table-axis entries already have their own table_policy bound. They are
    # retained unchanged and do not consume the ordinary prose block allowance.
    ordinary = [e for e in entries if not e["role"].startswith("table_")]
    if (
        len(ordinary) > limits["max_context_blocks"]
        or sum(len(e["text"]) for e in ordinary) > limits["max_context_chars"]
    ):
        raise ValueError("CF5_CONTEXT_TOO_LARGE")
    data["context_blocks"] = [e | dict(context_index=i) for i, e in enumerate(entries)]
    kept = {e["source_id"] for e in entries}
    data["omitted_source_ids"] = list(
        dict.fromkeys(
            [s for s in data["omitted_source_ids"] if s not in kept]
            + [
                e["source_id"]
                for e in packet["untrusted_document_data"]["context_blocks"]
                if e["source_id"] not in kept
            ]
        )
    )
    limits["whole_blocks_only"] = False  # preserved K5 continuations can be spans
    result["cf5_context_policy"] = POLICY
    result["cf5_context_sha256"] = canonical_hash(data["context_blocks"])
    result["prompt_sha256"] = canonical_hash(PRELIMINARY)
    return result


def validate_packet(packet):
    if (
        packet.get("cf5_context_policy") != POLICY
        or packet.get("prompt_sha256") != canonical_hash(PRELIMINARY)
        or packet.get("cf5_context_sha256")
        != canonical_hash(packet["untrusted_document_data"]["context_blocks"])
    ):
        raise ValueError("CF5_CONTEXT_PACKET_MISMATCH")


def preliminary(schema, *, quote=None):
    from proofops.application.tagging.finals_i4 import _require_k4_schema
    from proofops.domain.rulepacks import canonical_json

    _require_k4_schema(schema)
    return PRELIMINARY.replace("{{OUTPUT_SCHEMA_JSON}}", canonical_json(schema))
