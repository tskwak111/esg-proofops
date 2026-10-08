"""Claim-source policy dispatch shared by run creation, publication and load.

The base verifier (``claim_source_verification``) keeps its own known-version
dispatch untouched, including its vendored frozen predecessors. This module only
adds the explicitly opted-in render-resolution wrapper
(``claim_span_render_resolution``) as a SECOND admissible policy and gives every
caller -- run snapshot validation, the worker's single-shot and batch extract
publication, and the claim store's replay -- one shared decision instead of a
duplicated branch per call site.

Rollback is "do not pin the new policy on future runs": nothing here reinterprets
a stored receipt. A run that pinned the base policy still resolves to the base
verifier, a run that pinned a frozen predecessor still replays under that frozen
module, and both keep their original receipt schema and bytes.
"""

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path

RENDER_RESOLUTION_POLICY_SCHEMA = "claim_span_render_resolution_policy_v1"
# R19 bullet-alignment wrapper. It WRAPS the render-resolution wrapper rather
# than replacing it, so pinning it preserves render resolution instead of
# trading one recovery for the other.
BULLET_ALIGNMENT_POLICY_SCHEMA = "claim_span_bullet_alignment_policy_v1"
# R24 rendered-side-only typography wrapper. It WRAPS the bullet-alignment
# wrapper rather than replacing it, so pinning it preserves both inner
# recoveries. Its native gate is the base verifier's, unfolded.
TYPOGRAPHY_POLICY_SCHEMA = "claim_span_typography_policy_v1"
# Accepted in a run snapshot. The two base schemas are the base verifier's own;
# the others are each wrapper's distinct schema, so no receipt or policy of one
# kind can ever be read as the other.
CLAIM_SOURCE_POLICY_SCHEMAS = frozenset(
    {
        "claim_source_policy_v1",
        "claim_source_policy_v2",
        RENDER_RESOLUTION_POLICY_SCHEMA,
        BULLET_ALIGNMENT_POLICY_SCHEMA,
        TYPOGRAPHY_POLICY_SCHEMA,
    }
)


def _render_resolution():
    from proofops.adapters.local import claim_span_render_resolution

    return claim_span_render_resolution


def _bullet_alignment():
    from proofops.adapters.local import claim_span_bullet_alignment

    return claim_span_bullet_alignment


def _typography():
    from proofops.adapters.local import claim_span_typography

    return claim_span_typography


def _historical_typography():
    """Replay the byte-pinned R24 wrapper before its documentation path edit.

    The entire policy (including all dependency hashes) must still match the
    policy computed by these exact bytes. Never admit it for new publication.
    """
    path = Path(__file__).with_name("_frozen_verifiers") / "claim_span_typography_v1.py"
    digest = "58086038813acfca0e5d40108f7bf49863b11ecf5ceff56c91ca4989a82b98de"
    if not path.is_file() or sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
    from proofops.adapters.local._frozen_verifiers import claim_span_typography_v1

    return claim_span_typography_v1


def _glyph_alignment():
    from proofops.adapters.local import glyph_alignment_verification

    return glyph_alignment_verification


def _wrappers():
    """Every wrapper module, outermost first. Additive: the base verifier's own
    dispatch is untouched and each wrapper keeps its own distinct policy."""
    return (_glyph_alignment(), _typography(), _bullet_alignment(), _render_resolution())


def claim_source_reader(policy):
    """Replay dispatch for a policy already pinned in a run snapshot.

    A wrapper policy resolves only when it matches its shipped current or
    byte-pinned historical module's complete policy: an altered wrapper hash is
    refused rather than replayed under different code. Every other policy is
    handed to the base verifier's own dispatch unchanged, so legacy and frozen
    runs keep replaying under the verifier that produced them.
    """
    from proofops.adapters.local import claim_source_verification as base

    if isinstance(policy, Mapping):
        if policy.get("profile") in {"upstage-ocr-page-v1", "upstage-ocr-page-v2"}:
            upstage_ocr_profile = page_ocr_profile(policy["profile"])

            if policy != upstage_ocr_profile.claim_source_policy():
                raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
            return upstage_ocr_profile
        if policy.get("profile") == _glyph_alignment().PROFILE:
            wrapper = _glyph_alignment()
            if policy != wrapper.claim_source_policy():
                raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
            return wrapper
        for schema, module in (
            (TYPOGRAPHY_POLICY_SCHEMA, _typography),
            (BULLET_ALIGNMENT_POLICY_SCHEMA, _bullet_alignment),
            (RENDER_RESOLUTION_POLICY_SCHEMA, _render_resolution),
        ):
            if policy.get("schema") != schema:
                continue
            wrapper = module()
            if policy != wrapper.claim_source_policy():
                if schema != TYPOGRAPHY_POLICY_SCHEMA:
                    raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
                wrapper = _historical_typography()
                if policy != wrapper.claim_source_policy():
                    raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
            return wrapper
    return base.claim_source_reader(policy)


def publication_reader(policy):
    """Reader admissible for a NEW publication: the current base verifier or the
    current opt-in wrapper, nothing else.

    Frozen predecessors stay replay-only exactly as before this module existed:
    a run pinned to an older base policy is still rejected with
    ``CLAIM_SOURCE_POLICY_MISMATCH`` instead of publishing a fresh attestation
    under code it was not created with.
    """
    from proofops.adapters.local import claim_source_verification as base

    if isinstance(policy, Mapping) and policy.get("profile") in {
        "upstage-ocr-page-v1",
        "upstage-ocr-page-v2",
    }:
        return claim_source_reader(policy)
    for module in (base, *_wrappers()):
        if policy == module.claim_source_policy():
            return module
    raise ValueError("CLAIM_SOURCE_POLICY_MISMATCH")


def attest_claims(*, reader, graph, source, refs, tenant_id, cache, run_id=None):
    """Publish an attestation under ``reader``'s own semantics.

    ``cache`` keeps each existing call site's behaviour: the batch path reuses
    the base reader's incremental per-ref attestation cache, the single-shot
    path does not. No wrapper is ever routed through that cache regardless:
    a wrapper receipt carries whole-receipt fields (``base_records``,
    ``render_retries``, ``bullet_alignments``, ``typography_reads``) that a
    per-record cache composition would leave inconsistent with a fresh
    recompute, and every
    wrapper's replay recomputes the receipt in full, so a composed receipt
    would be refused at load time. The separate replay cache in
    ``native_replay_cache`` is keyed on the whole receipt and stays usable for
    both readers.

    A wrapper receipt is therefore recomputed in full here and then remembered
    whole, not composed: ``remember_wrapper_attestation`` stores these exact
    canonical bytes so the strict replay that immediately follows the batch
    publication can match them instead of repeating the same whole-ref read.
    The published bytes are unchanged either way.
    """
    if getattr(reader, "PROFILE", None) in {"upstage-ocr-page-v1", "upstage-ocr-page-v2"}:
        return reader.attest_claim_spans(
            graph, source, tuple(refs), tenant_id=tenant_id, run_id=run_id
        )
    if cache and reader not in _wrappers():
        from proofops.adapters.local.native_replay_cache import attest_claims_cached

        return attest_claims_cached(
            reader=reader, graph=graph, source=source, refs=refs, tenant_id=tenant_id
        )
    receipt = reader.attest_claim_spans(graph, source, tuple(refs), tenant_id=tenant_id)
    if cache:
        from proofops.adapters.local.native_replay_cache import remember_wrapper_attestation

        remember_wrapper_attestation(
            reader=reader,
            policy=reader.claim_source_policy(),
            graph=graph,
            source=source,
            tenant_id=tenant_id,
            receipt=receipt,
        )
    return receipt


def page_ocr_profile(profile):
    """Resolve the explicitly versioned mapping; never reinterpret old receipts."""
    if profile == "upstage-ocr-page-v1":
        from proofops.adapters.local import upstage_ocr_profile

        return upstage_ocr_profile
    if profile == "upstage-ocr-page-v2":
        from proofops.adapters.local import upstage_ocr_profile_v2

        return upstage_ocr_profile_v2
    raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
