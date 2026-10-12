"""R7 reviewed statement boundaries, discovery only; historical E02 stays intact.

The two original hashes pin this narrow review. Unknown PDFs keep conservative
E02 discovery; an empty trailing page is never automatically a back cover.
Offsets address the immutable native-discovery text, not graph character spans.
"""

from proofops.application.evidence.assurance_catalog import discover_bundles
from proofops.domain.provenance import canonical_hash

VERSION = "assurance-segments-c2-v1"
POLICY = dict(
    profile=VERSION,
    authority="discovery_only",
    review="R7/case-review.json; original physical pages",
    shared_page="disjoint native char intervals; no scope union",
)
POLICY_HASH = canonical_hash(POLICY)
KAKAO = "43804a2d5eccfc6aa9c5b5480ec6714c7d07bea13ed68729c0af7a3b622ce76d"
LG = "c6395dd2be7948d85fa2b52c6edb61367fa6610c6f389c2478b44cb4cfcb5bde"


def discover_segments(page_texts, *, page_count, source_sha256):
    baseline = discover_bundles(page_texts, page_count=page_count, source_sha256=source_sha256)
    exclusions = []
    if source_sha256 == KAKAO:
        starts = [
            (130, "(주)카카오 및 연결법인의 2025년 온실가스 배출량"),
            (132, "(주)카카오의 2025년 온실가스 배출량"),
            (133, "(주) 카카오의 목표관리제 대상 사업장에 대한 2025년"),
            (134, "온실가스 검증의견서"),
            (136, "제3자 검증의견서"),
        ]
        ends = [131, 132, 133, 135, 138]
        if page_count != 139 or page_texts.get(139, "").strip():
            raise ValueError("C2_REVIEWED_BOUNDARY_DRIFT")
        exclusions = [
            dict(
                physical_page=139,
                classification="reviewed_back_cover",
                source_sha256=source_sha256,
                review="R7/C09-unreadable",
            )
        ]
    elif source_sha256 == LG:
        starts = [
            (117, "로이드인증원 검증 의견서"),
            (118, "LG화학의 2025년도 온실가스 인벤토리 관련"),
        ]
        ends = [118, 119]
        if page_count != 119:
            raise ValueError("C2_REVIEWED_BOUNDARY_DRIFT")
    else:
        return _seal(
            dict(
                schema=VERSION,
                policy_sha256=POLICY_HASH,
                source_sha256=source_sha256,
                page_count=page_count,
                discovery_only=True,
                reviewed_exclusions=[],
                bundles=[
                    dict(b, statement_id=b["bundle_id"], segments=[]) for b in baseline["bundles"]
                ],
            )
        )
    offsets = []
    for page, marker in starts:
        text = page_texts.get(page, "")
        if marker not in text:
            raise ValueError("C2_REVIEWED_BOUNDARY_MARKER_MISSING")
        offsets.append(text.index(marker))
    bundles = []
    for index, ((page, marker), end) in enumerate(zip(starts, ends, strict=True)):
        segments = []
        for p in range(page, end + 1):
            text = page_texts.get(p, "")
            start = offsets[index] if p == page else 0
            stop = (
                offsets[index + 1]
                if index + 1 < len(starts) and starts[index + 1][0] == p
                else len(text)
            )
            if not text[start:stop].strip():
                raise ValueError("C2_REVIEWED_BOUNDARY_UNREADABLE")
            segments.append(
                dict(
                    physical_page=p,
                    char_start=start,
                    char_end=stop,
                    native_text_sha256=canonical_hash(text),
                    segment_sha256=canonical_hash(text[start:stop]),
                )
            )
        identity = dict(source_sha256=source_sha256, segments=segments, policy_sha256=POLICY_HASH)
        sid = canonical_hash(identity)
        bundles.append(
            dict(
                bundle_id=sid,
                statement_id=sid,
                title=marker,
                pages=list(range(page, end + 1)),
                segments=segments,
                boundary_state="reviewed_candidate",
                source_quality="unverified",
                reasons=[],
                authority="discovery_only",
            )
        )
    return _seal(
        dict(
            schema=VERSION,
            policy_sha256=POLICY_HASH,
            source_sha256=source_sha256,
            page_count=page_count,
            discovery_only=True,
            reviewed_exclusions=exclusions,
            bundles=bundles,
        )
    )


def _seal(value):
    return value | dict(discovery_sha256=canonical_hash(value))
