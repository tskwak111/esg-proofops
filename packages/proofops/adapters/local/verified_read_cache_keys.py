"""Execution eligibility and exact source fingerprints for verified-read reuse.

Resolve shared policies and hooks through the original cache module at call time.
Keeping that import inside functions also allows this module to be imported first.
Reader byte pins always use the reader's own __file__, never this module's path.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import ModuleType
    from typing import Any

    from proofops.application.ingest.graph_fusion import CanonicalDocumentGraph
    from proofops.domain.values import SourceRef


def fresh_execution_enabled() -> bool:
    from proofops.adapters.local import verified_read_cache as cache

    return cache.os.environ.get("PROOFOPS_VERIFIED_READ_CACHE") in (
        cache.VERIFIED_READ_V2_POLICY["profile"],
        cache.VERIFIED_READ_V3_POLICY["profile"],
        cache.VERIFIED_READ_V4_POLICY["profile"],
        cache.VERIFIED_READ_V5_POLICY["profile"],
        cache.VERIFIED_READ_V6_POLICY["profile"],
        cache.VERIFIED_READ_V7_POLICY["profile"],
        cache.VERIFIED_READ_V8_POLICY["profile"],
        cache.VERIFIED_READ_V9_POLICY["profile"],
        cache.VERIFIED_READ_V10_POLICY["profile"],
        cache.VERIFIED_READ_V11_POLICY["profile"],
        cache.VERIFIED_READ_V12_POLICY["profile"],
        cache.S3_VERIFIED_READ_V13_POLICY["profile"],
    )


def _execution_policy() -> Mapping[str, Any] | None:
    from proofops.adapters.local import verified_read_cache as cache

    for policy in (
        cache.POLICY,
        cache.VERIFIED_READ_V2_POLICY,
        cache.VERIFIED_READ_V3_POLICY,
        cache.VERIFIED_READ_V4_POLICY,
        cache.VERIFIED_READ_V5_POLICY,
        cache.VERIFIED_READ_V6_POLICY,
        cache.VERIFIED_READ_V7_POLICY,
        cache.VERIFIED_READ_V8_POLICY,
        cache.VERIFIED_READ_V9_POLICY,
        cache.VERIFIED_READ_V10_POLICY,
        cache.VERIFIED_READ_V11_POLICY,
        cache.VERIFIED_READ_V12_POLICY,
        cache.S3_VERIFIED_READ_V13_POLICY,
    ):
        if cache.os.environ.get("PROOFOPS_VERIFIED_READ_CACHE") == policy["profile"]:
            return policy
    return None


def _parse_enabled() -> bool:
    from proofops.adapters.local import verified_read_cache as cache

    return cache._execution_policy() in (
        cache.VERIFIED_READ_V3_POLICY,
        cache.VERIFIED_READ_V4_POLICY,
        cache.VERIFIED_READ_V5_POLICY,
        cache.VERIFIED_READ_V6_POLICY,
        cache.VERIFIED_READ_V7_POLICY,
        cache.VERIFIED_READ_V8_POLICY,
        cache.VERIFIED_READ_V9_POLICY,
        cache.VERIFIED_READ_V10_POLICY,
        cache.VERIFIED_READ_V11_POLICY,
        cache.VERIFIED_READ_V12_POLICY,
        cache.S3_VERIFIED_READ_V13_POLICY,
    )


def _parse_projection_pinned(reader_name: str, policy: dict[str, Any]) -> bool:
    from pathlib import Path

    from proofops.adapters.local import evidence_source_ocr_v1 as ev1
    from proofops.adapters.local import evidence_source_verification_v1 as base
    from proofops.adapters.local import upstage_ocr_profile
    from proofops.adapters.local import verified_read_cache as cache
    from proofops.adapters.local.claim_source_policies import page_ocr_profile as _page_ocr_profile

    page_ocr_profile: Callable[..., ModuleType] = _page_ocr_profile

    if not cache._parse_enabled():
        return False
    if cache._execution_policy() in (
        cache.VERIFIED_READ_V10_POLICY,
        cache.VERIFIED_READ_V11_POLICY,
        cache.VERIFIED_READ_V12_POLICY,
        cache.S3_VERIFIED_READ_V13_POLICY,
    ):
        try:
            if reader_name.startswith("native:"):
                page_ocr_profile(policy["mode"], policy=policy, native=True)
                return True
            from proofops.adapters.local.evidence_source_policies import (
                evidence_source_reader as _evidence_source_reader,
            )

            evidence_source_reader: Callable[..., ModuleType] = _evidence_source_reader

            return evidence_source_reader(policy).__name__ == reader_name
        except (ValueError, KeyError, TypeError):
            return False
    if cache._execution_policy() == cache.VERIFIED_READ_V9_POLICY:
        if reader_name == "native:upstage-ocr-page-v17":
            reader = page_ocr_profile("upstage-ocr-page-v17", policy=policy, native=True)
            return (
                policy == reader.native_policy()
                and cache.sha256(Path(cast("str", reader.__file__)).read_bytes()).hexdigest()
                == cache.VERIFIED_READ_V9_POLICY["v17_replay_sha256"]
            )
        from proofops.adapters.local import evidence_source_hx3

        if reader_name == evidence_source_hx3.__name__:
            return (
                policy == evidence_source_hx3.policy()
                and cache.sha256(Path(base.__file__).read_bytes()).hexdigest()
                == "d006dd1f3534080ad947b28fbfbedd57e97580b67ea3bb397dbb403ce01b01f6"
            )
    if reader_name == "native:upstage-ocr-page-v6":
        return (
            policy == page_ocr_profile("upstage-ocr-page-v6").native_policy()
            and cache.sha256(Path(upstage_ocr_profile.__file__).read_bytes()).hexdigest()
            == cache._OCR_REPLAY_TAIL_SHA256
        )
    return (
        reader_name == ev1.__name__
        and policy == ev1.policy()
        and cache.sha256(Path(base.__file__).read_bytes()).hexdigest()
        == "d006dd1f3534080ad947b28fbfbedd57e97580b67ea3bb397dbb403ce01b01f6"
        and cache.sha256(Path(ev1.__file__).read_bytes()).hexdigest()
        == "542c02413931bea2cb20e697664b5dcd504bc411b4dbcfcc1b9b4210695ade56"
    )


def _parse_key(
    *,
    reader_name: str,
    policy: dict[str, Any],
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    tenant_id: str,
) -> str | None:
    from proofops.adapters.local import verified_read_cache as cache
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile as _read_profile

    read_profile: Callable[..., str] = _read_profile

    if cache._execution_policy() == cache.S3_VERIFIED_READ_V13_POLICY and receipt.get(
        "table_acquisition_holds"
    ):
        return None
    if not cache._parse_projection_pinned(reader_name, policy) or cache._transient(receipt):
        return None
    if receipt.get("reader_policy" if reader_name.startswith("native:") else "policy") != policy:
        return None
    return "parse:" + cache.canonical_hash(
        dict(
            reader=reader_name,
            policy=policy,
            receipt=receipt,
            graph=cache.asdict(graph),
            source_sha256=cache.sha256(source).hexdigest(),
            tenant_id=tenant_id,
            runtime=runtime_policy(),
            read_profile=read_profile(),
            platform=cache.sys.platform,
            toolchain=cache.os.environ.get("DEVELOPER_DIR"),
            execution=cache._execution_policy(),
        )
    )


def _fresh_key(
    reader: ModuleType,
    policy: dict[str, Any],
    receipt: dict[str, Any],
    graph: CanonicalDocumentGraph,
    source: bytes,
    refs: tuple[SourceRef, ...],
    tenant_id: str,
) -> str | None:
    from pathlib import Path

    from proofops.adapters.local import upstage_ocr_profile
    from proofops.adapters.local import verified_read_cache as cache
    from proofops.adapters.local.claim_source_policies import page_ocr_profile as _page_ocr_profile

    page_ocr_profile: Callable[..., ModuleType] = _page_ocr_profile
    from proofops.adapters.local.local_raster_reader import runtime_policy
    from proofops.adapters.local.receipt_environment_compat import read_profile as _read_profile

    read_profile: Callable[..., str] = _read_profile

    profile = policy.get("profile")
    registered = False
    if cache._execution_policy() in (
        cache.VERIFIED_READ_V10_POLICY,
        cache.VERIFIED_READ_V11_POLICY,
        cache.VERIFIED_READ_V12_POLICY,
        cache.S3_VERIFIED_READ_V13_POLICY,
    ):
        try:
            registered = reader is page_ocr_profile(profile, policy=policy)
        except ValueError:
            pass

    pinned_v9 = (
        cache._execution_policy()
        in (
            cache.VERIFIED_READ_V4_POLICY,
            cache.VERIFIED_READ_V5_POLICY,
            cache.VERIFIED_READ_V6_POLICY,
            cache.VERIFIED_READ_V7_POLICY,
            cache.VERIFIED_READ_V8_POLICY,
            cache.VERIFIED_READ_V9_POLICY,
            cache.VERIFIED_READ_V10_POLICY,
        )
        and profile == "upstage-ocr-page-v9"
        and reader is page_ocr_profile(profile)
        and cache.sha256(Path(cast("str", reader.__file__)).read_bytes()).hexdigest()
        == cache.VERIFIED_READ_V4_POLICY["v9_replay_sha256"]
        and receipt.get("schema") == "claim_source_pb4_extension_v1"
    )
    pinned_v6 = (
        profile == "upstage-ocr-page-v6"
        and reader is page_ocr_profile(profile)
        and cache.sha256(Path(upstage_ocr_profile.__file__).read_bytes()).hexdigest()
        == cache._OCR_REPLAY_TAIL_SHA256
    )
    pinned_v10 = (
        cache._execution_policy()
        in (
            cache.VERIFIED_READ_V5_POLICY,
            cache.VERIFIED_READ_V6_POLICY,
            cache.VERIFIED_READ_V7_POLICY,
            cache.VERIFIED_READ_V8_POLICY,
            cache.VERIFIED_READ_V9_POLICY,
            cache.VERIFIED_READ_V10_POLICY,
        )
        and profile == "upstage-ocr-page-v10"
        and reader is page_ocr_profile(profile)
        and cache.sha256(Path(cast("str", reader.__file__)).read_bytes()).hexdigest()
        == cache.VERIFIED_READ_V5_POLICY["v10_replay_sha256"]
        and receipt.get("schema") == "claim_source_pa9_extension_v1"
    )
    pinned_v11 = (
        cache._execution_policy()
        in (
            cache.VERIFIED_READ_V6_POLICY,
            cache.VERIFIED_READ_V7_POLICY,
            cache.VERIFIED_READ_V8_POLICY,
        )
        and profile == "upstage-ocr-page-v11"
        and reader is page_ocr_profile(profile)
        and cache.sha256(Path(cast("str", reader.__file__)).read_bytes()).hexdigest()
        == cache.VERIFIED_READ_V6_POLICY["v11_replay_sha256"]
        and receipt.get("schema") == "claim_source_k3_extension_v1"
    )
    pinned_v12 = (
        cache._execution_policy()
        in (
            cache.VERIFIED_READ_V7_POLICY,
            cache.VERIFIED_READ_V8_POLICY,
            cache.VERIFIED_READ_V9_POLICY,
        )
        and profile == "upstage-ocr-page-v12"
        and reader is page_ocr_profile(profile)
        and cache.sha256(Path(cast("str", reader.__file__)).read_bytes()).hexdigest()
        == cache.VERIFIED_READ_V7_POLICY["v12_replay_sha256"]
        and receipt.get("schema") == "claim_source_h1_extension_v1"
    )
    pinned_v13 = (
        cache._execution_policy() == cache.VERIFIED_READ_V8_POLICY
        and profile == "upstage-ocr-page-v13"
        and reader is page_ocr_profile(profile)
        and cache.sha256(Path(cast("str", reader.__file__)).read_bytes()).hexdigest()
        == cache.VERIFIED_READ_V8_POLICY["v13_replay_sha256"]
        and receipt.get("schema") == "claim_source_k7_extension_v1"
    )
    pinned_v17 = (
        cache._execution_policy() == cache.VERIFIED_READ_V9_POLICY
        and profile == "upstage-ocr-page-v17"
        and reader is page_ocr_profile(profile, policy=policy)
        and cache.sha256(Path(cast("str", reader.__file__)).read_bytes()).hexdigest()
        == cache.VERIFIED_READ_V9_POLICY["v17_replay_sha256"]
        and receipt.get("schema") == "claim_source_k7_extension_v1"
    )
    if (registered or pinned_v13 or pinned_v17) and (
        receipt.get("tenant_id") != tenant_id
        or graph.tenant_id != tenant_id
        or receipt.get("document_version_id") != graph.document_version_id
        or receipt.get("parse_manifest_id") != graph.parse_manifest_id
        or receipt.get("source_sha256") != cache.sha256(source).hexdigest()
        or graph.source_sha256 != cache.sha256(source).hexdigest()
        or receipt.get("graph_sha256") != cache.canonical_hash(cache.asdict(graph))
        or receipt.get("artifact_sha256")
        != cache.canonical_hash({k: v for k, v in receipt.items() if k != "artifact_sha256"})
    ):
        return None
    if (
        not cache.fresh_execution_enabled()
        or not (
            registered
            or pinned_v6
            or pinned_v9
            or pinned_v10
            or pinned_v11
            or pinned_v12
            or pinned_v13
            or pinned_v17
        )
        or reader.claim_source_policy() != policy
        or receipt.get("policy") != policy
        or not receipt.get("run_id")
        or cache._transient(receipt)
        or cache.canonical_hash([r["ref"] for r in receipt.get("records", [])])
        != cache.canonical_hash([cache.asdict(r) for r in refs])
    ):
        return None
    return "fresh:" + cache.canonical_hash(
        dict(
            reader=reader.__name__,
            tenant_id=tenant_id,
            source_sha256=cache.sha256(source).hexdigest(),
            graph=cache.asdict(graph),
            receipt=receipt,
            refs=[cache.asdict(r) for r in refs],
            policy=policy,
            runtime=runtime_policy(),
            read_profile=read_profile(),
            platform=cache.sys.platform,
            toolchain=cache.os.environ.get("DEVELOPER_DIR"),
            execution=cache._execution_policy(),
        )
    )
