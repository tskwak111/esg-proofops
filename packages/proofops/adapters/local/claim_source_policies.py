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

# One registry owns source replay, publication and parser-native binding. Reader
# modules remain byte-pinned; adding a shipped profile cannot omit a second gate.
PAGE_OCR_PROFILES = {
    "upstage-ocr-page-v1": "proofops.adapters.local.upstage_ocr_profile",
    **{
        f"upstage-ocr-page-v{version}": f"proofops.adapters.local.upstage_ocr_profile_v{version}"
        for version in range(2, 22)
    },
    "fxf_upstage-ocr-page-v21": "proofops.adapters.local.upstage_ocr_profile_fxf",
    "fxe_upstage-ocr-page-v21": "proofops.adapters.local.upstage_ocr_profile_fxe",
    "upstage-ocr-page-v17-rg1": "proofops.adapters.local.upstage_ocr_profile_rg1_v17",
    "upstage-ocr-page-v16-hx4": "proofops.adapters.local.upstage_ocr_profile_hx4_v16",
    "upstage-ocr-page-v16-hx5": "proofops.adapters.local.upstage_ocr_profile_hx5_v16",
    "fxg_claim_source_v1": "proofops.adapters.local.fxg_claim_source",
    "i24_claim_source_v1": "proofops.adapters.local.i24_claim_source",
    "fxh_claim_source_v1": "proofops.adapters.local.fxh_claim_source",
    "s5_claim_source_v1": "proofops.adapters.local.s5_claim_source",
    "rb3_claim_source_v1": "proofops.adapters.local.rb3_claim_source",
    "cf4_claim_source_v1": "proofops.adapters.local.cf4_claim_source",
    "spe_claim_source_v1": "proofops.adapters.local.spe_claim_source",
    "i31_claim_source_v1": "proofops.adapters.local.i31_claim_source",
    "tb1_claim_source_v1": "proofops.adapters.local.tb1_claim_source",
}

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
        "claim_source_render_conditioned_policy_v1",
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
    from proofops.adapters.local.historical_claim_replay import historical_typography_reader

    return historical_typography_reader()


def _glyph_alignment():
    from proofops.adapters.local import glyph_alignment_verification

    return glyph_alignment_verification


def _source_v3():
    from proofops.adapters.local import claim_source_verification_v3

    return claim_source_verification_v3


def _source_v4():
    from proofops.adapters.local import claim_source_verification_v4

    return claim_source_verification_v4


def _table_claims():
    from proofops.adapters.local import table_claim_source_verification

    return table_claim_source_verification


def _wrappers():
    """Every wrapper module, outermost first. Additive: the base verifier's own
    dispatch is untouched and each wrapper keeps its own distinct policy."""
    return (
        _source_v4(),
        _source_v3(),
        _table_claims(),
        _glyph_alignment(),
        _typography(),
        _bullet_alignment(),
        _render_resolution(),
    )


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
        if policy.get("profile") == "claim-source-v4":
            wrapper = _source_v4()
            if policy != wrapper.claim_source_policy():
                from proofops.adapters.local.historical_prose_replay import historical_prose_reader

                wrapper = historical_prose_reader()
                if policy != wrapper.claim_source_policy():
                    raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
            return wrapper
        if policy.get("profile") == "claim-source-v3":
            wrapper = _source_v3()
            if policy != wrapper.claim_source_policy():
                raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
            return wrapper
        if policy.get("profile") in PAGE_OCR_PROFILES:
            return page_ocr_profile(policy["profile"], policy=policy)
        if policy.get("profile") == _table_claims().PROFILE:
            wrapper = _table_claims()
            if policy != wrapper.claim_source_policy():
                raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
            return wrapper
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

    if isinstance(policy, Mapping) and policy.get("profile") in PAGE_OCR_PROFILES:
        if policy.get("profile") == "upstage-ocr-page-v21":
            module = page_ocr_profile(policy["profile"])
            if page_ocr_profile(policy["profile"], policy=policy) is not module:
                raise ValueError("CLAIM_SOURCE_POLICY_MISMATCH")
            return module
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
    if getattr(reader, "PROFILE", None) in PAGE_OCR_PROFILES:
        refs = tuple(refs)
        from proofops.adapters.local.verified_read_cache import _execution_policy
        from proofops.adapters.local.worker_resources import enabled as resources_enabled
        from proofops.application.analysis_profile import (
            S3_VERIFIED_READ_V13_POLICY,
            VERIFIED_READ_V4_POLICY,
            VERIFIED_READ_V5_POLICY,
            VERIFIED_READ_V6_POLICY,
            VERIFIED_READ_V7_POLICY,
            VERIFIED_READ_V8_POLICY,
            VERIFIED_READ_V11_POLICY,
            VERIFIED_READ_V12_POLICY,
        )

        if _execution_policy() in (
            VERIFIED_READ_V12_POLICY,
            S3_VERIFIED_READ_V13_POLICY,
        ) and reader.PROFILE in {
            "upstage-ocr-page-v19",
            "upstage-ocr-page-v20",
            "upstage-ocr-page-v21",
        }:
            from proofops.adapters.local.i21_reader_execution import reader_scope

            with reader_scope(reader, run_id=run_id, tenant_id=tenant_id) as instance:
                receipt = instance.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        elif (
            reader.PROFILE == "upstage-ocr-page-v19"
            and _execution_policy() == VERIFIED_READ_V11_POLICY
        ):
            from proofops.adapters.local.s2_reader_execution import reader_scope

            with reader_scope(reader, run_id=run_id, tenant_id=tenant_id) as instance:
                receipt = instance.attest_claim_spans(graph, source, refs, tenant_id=tenant_id)
        elif (
            (resources_enabled() and reader.PROFILE == "upstage-ocr-page-v13")
            or (
                reader.PROFILE == "upstage-ocr-page-v9"
                and _execution_policy() == VERIFIED_READ_V4_POLICY
            )
            or (
                reader.PROFILE in VERIFIED_READ_V5_POLICY["raw_ocr_profiles"]
                and _execution_policy() == VERIFIED_READ_V5_POLICY
            )
            or (
                reader.PROFILE in VERIFIED_READ_V6_POLICY["raw_ocr_profiles"]
                and _execution_policy() == VERIFIED_READ_V6_POLICY
            )
            or (
                reader.PROFILE in VERIFIED_READ_V7_POLICY["raw_ocr_profiles"]
                and _execution_policy() == VERIFIED_READ_V7_POLICY
            )
            or (
                reader.PROFILE in VERIFIED_READ_V8_POLICY["raw_ocr_profiles"]
                and _execution_policy() == VERIFIED_READ_V8_POLICY
            )
        ):
            from proofops.adapters.local.pa7_raster_cache import attest

            receipt = attest(reader, graph, source, refs, tenant_id=tenant_id, run_id=run_id)
        else:
            receipt = reader.attest_claim_spans(
                graph, source, tuple(refs), tenant_id=tenant_id, run_id=run_id
            )
        from proofops.adapters.local.verified_read_cache import remember_fresh_attestation

        remember_fresh_attestation(
            reader=reader,
            policy=reader.claim_source_policy(),
            receipt=receipt,
            graph=graph,
            source=source,
            refs=refs,
            tenant_id=tenant_id,
        )
        return receipt
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


def page_ocr_profile(profile, *, policy=None, native=False):
    """Resolve only shipped registry entries; never import an untrusted module name."""
    from importlib import import_module

    if not isinstance(profile, str) or profile not in PAGE_OCR_PROFILES:
        raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
    module = import_module(PAGE_OCR_PROFILES[profile])
    if policy is None:
        return module
    candidates = [module]
    if profile == "upstage-ocr-page-v16":
        candidates.extend(
            import_module(PAGE_OCR_PROFILES[name])
            for name in ("upstage-ocr-page-v16-hx4", "upstage-ocr-page-v16-hx5")
        )
    if profile == "upstage-ocr-page-v17":
        candidates.append(import_module(PAGE_OCR_PROFILES["upstage-ocr-page-v17-rg1"]))
    for candidate in candidates:
        expected = candidate.native_policy() if native else candidate.claim_source_policy()
        if policy == expected:
            return candidate
    if profile == "upstage-ocr-page-v21":
        from proofops.adapters.local import upstage_ocr_profile_d2_v21
        from proofops.adapters.local.historical_claim_replay import (
            historical_upstage_ocr_v21_reader,
        )
        from proofops.adapters.local.historical_prose_replay import historical_pre_d2_reader

        for historical in (
            upstage_ocr_profile_d2_v21,
            historical_upstage_ocr_v21_reader(),
            historical_pre_d2_reader(),
        ):
            expected = historical.native_policy() if native else historical.claim_source_policy()
            if policy == expected:
                return historical
    if profile == "upstage-ocr-page-v21" and not native:
        from proofops.adapters.local.historical_prose_replay import historical_prose_reader

        historical = historical_prose_reader(page_ocr=True)
        if policy == historical.claim_source_policy():
            return historical
    raise ValueError("CLAIM_SOURCE_POLICY_UNKNOWN")
