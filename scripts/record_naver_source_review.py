"""Explicit supervised review record for the already inspected NAVER source pages.

Run once after visual inspection. Does not import the evaluation answer set.
Scope: source interpretation and local project rules, not expert/legal approval.
"""

import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from proofops.adapters.local.rulepack_store import RulePackSqliteStore
from proofops.application.rulepacks import RulePackRecord
from proofops.domain.reconciliation.common import validate_policy
from proofops.domain.rulepacks import snapshot_from_validated
from proofops.domain.values import SourceRef

from evaluation.local_analysis_pipeline import (
    MANIFEST_HASH,
    SOURCE_HASH,
    catalog,
    snapshot,
)
from evaluation.local_review import candidate, digest
from evaluation.reconciliation_policy_draft import build_policy_draft
from scripts.review_rulepack import promote_and_review_pack

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / ".local/final-review"
    target = directory / "review.json"
    if target.exists():
        raise ValueError("review revision exists; create a new revision instead of overwriting")
    original = json.loads(
        (ROOT / ".local/copy-pipeline-verified/response.json").read_text("utf-8")
    )["body"]
    pdf = next(ROOT.glob("*/NAVER_2024_KOR.pdf")).read_bytes()
    # Recheck exact source and all retained parser artifact hashes.
    result = snapshot(pdf)
    if result is None:
        raise ValueError("unreviewed source")
    now = datetime.now(UTC).isoformat()
    authority = (
        "User request 2026-10-10: perform remaining table/scope reviews "
        "and rule/reconciliation policy approval"
    )
    reviewer = "codex-source-review-20261010"
    draft = json.loads((ROOT / "api/rulepack.json").read_text("utf-8"))
    draft["tenant_id"] = result[0]["tenant_id"]
    files = {path: json.loads(raw) for path, raw in draft.pop("content")}
    store = RulePackSqliteStore(str(directory / "rulepack-state.sqlite3"))
    active_id = promote_and_review_pack(
        store,
        tenant_id=draft["tenant_id"],
        draft_pack=RulePackRecord.from_dict(draft),
        files=files,
        reviewer=reviewer,
        reviewed_at=now,
        source_authority=authority,
        note=(
            "Approve explicit disclosure ladders as local project interpretation. "
            "Retain all legal, safe-harbor and unresolved explicit-link gates. "
            "No expert-gold claim."
        ),
        now=time.time(),
    )
    record, files = store.get_pack_with_files(draft["tenant_id"], active_id)
    pack = snapshot_from_validated(record.to_dict(), files)
    policy = build_policy_draft(
        ROOT / "config/accounting/reconciliation_rules.yaml",
        version="parser-lab-reviewed-20261010-1",
        coverage_policy_id="source-bound-exact-scope-1",
    )
    policy.update(
        approved=True, approved_by=f"ai-delegated-review:{reviewer}", approved_on=now[:10]
    )
    validate_policy(policy)
    # Numeric C3 threshold and CAPEX mapping remain null/false. Their guard remains
    # active only for an actually applicable currency-investment claim.
    batches = result[1]["candidates.json"]
    blocks = {b["key"]: b for b in catalog(batches, [100, 105])}
    identity = dict(
        document_version_id="daa33e7b-a259-5e94-9eeb-30763cb11a1c",
        parse_manifest_id="3eb2b79c-4240-4797-bdb0-e842a4b334a1",
    )
    entries = {}
    for i, claim in enumerate(original["claims"]):
        names = (
            ["target_year", "target_metric"]
            if claim["track"] == "goal"
            else ["quantitative_or_qualified_ordinal", "unit_or_qualified_ordinal"]
        )
        # The original LNG unit is indeed m², not m³: retain a source anomaly.
        if i == 7:
            names = ["quantitative_or_qualified_ordinal"]
        sources = {}
        for name in names:
            element = next(e for e in claim["elements"] if e["name"] == name)
            key = (element.get("citation") or {}).get("source_key", claim["parser_source"]["key"])
            b = blocks[key]
            text = b["raw_text"]
            ref = SourceRef(
                source_id=str(uuid5(NAMESPACE_URL, key)),
                **identity,
                page_num=b["page"],
                printed_page_label=str(b["page"]),
                bbox=tuple(b["bbox"]),
                raw_text_sha256=sha256(text.encode()).hexdigest(),
                quote=text,
                char_start=0,
                char_end=len(text),
                location_quality="located",
                verification_state="verified",
            )
            sources[name] = dict(
                ref=asdict(ref), scope="same_table" if b["table"] else "local_claim"
            )
        notes = [
            "원문 100·105쪽의 인용, 시설 제목, 연도 열과 단위를 직접 검토함.",
            "설비 활동을 산정 방법론으로, 동일 문장 재인용을 수치 검산으로 승인하지 않음.",
            "P2/G3 등 미확인 요소는 unknown 유지; 부재로 바꿔 등급을 확정하지 않음.",
        ]
        changes = {}
        if i == 7:
            notes.append(
                "원문 자체가 LNG 단위를 m²로 표기. m³로 임의 교정하지 않으며 단위 적합성 보류."
            )
        if i == 17:
            changes["denominator"] = "심야전력 등 포함 전력"
            notes.append("65%는 심야전력 등을 포함한 분모; 78%의 일반전기 분모와 분리.")
        if i == 23:
            changes["unit"] = "무차원(PUE)"
            notes.append(
                "PUE는 보고서가 명시한 에너지효율 지표의 비율. "
                "물리 단위가 없는 것을 단위 누락으로 처리하지 않음."
            )
        if i == 25:
            changes["value"] = "30000"
            notes.append("원문 3만톤의 수량을 30000으로 정규화. 이상 한정어 유지.")
        if i in [9, 10, 11]:
            notes.append(
                "PPA 사용처는 각주에 따라 다른 사업장으로 변경 가능; "
                "확정 사업장 약정으로 보지 않음."
            )
        if i == 20:
            notes.append(
                "100쪽 51.6과 201쪽 51은 엄밀히 같은 값이 아님. "
                "반올림 규칙 미명시로 동일 판정 보류."
            )
        entries[digest(candidate(claim))] = dict(
            index=i,
            page=claim["page"],
            quote=claim["quote"],
            accepted_facts=names,
            fact_sources=sources,
            notes=notes,
            normalized_changes=changes,
        )
    review = dict(
        version=1,
        reviewer=reviewer,
        reviewed_at=now,
        source_authority=authority,
        review_origin="ai_project_interpretation",
        expert_gold=False,
        source_sha256=SOURCE_HASH,
        manifest_sha256=MANIFEST_HASH,
        identity=identity,
        rulepack=asdict(pack),
        reconciliation_policy=policy,
        claims=entries,
        vision_sha256=digest(original["vision"]),
        table_review=[
            dict(
                page=201,
                row="지열 도입 / 데이터센터 각 세종",
                year=2024,
                value="610",
                unit="tCO2e",
                disposition="enhanced 분류 기각; 원문 행 채택",
            ),
            dict(
                page=201,
                row="재생에너지 전력 구매 / 그린팩토리",
                year=2024,
                value="927",
                unit="tCO2e",
                disposition="enhanced 분류 기각; 원문 행 채택",
            ),
        ],
        scope_review=[
            "2쪽: ESG 개별기업 기준. 시설별 주장을 전체 연결집단으로 확장하지 않음.",
            "209쪽: Scope1·2 배출량 보증은 감축량 전체의 보증이 아님.",
            "201쪽: 감축량 별도 검증 각주는 유지하되 개별 주장 보증범위까지 자동 승인하지 않음.",
            "2쪽은 보고 종료일을 명시하나 모든 개별 주장에 시작일을 제공하지 않음.",
        ],
        limitations=[
            "전체 127개 표 검토 아님; 선택 주장과 관련 표 행만 검토",
            "C3 정량 임계값·계정 매핑은 실제 금액 투자 케이스가 있을 때 별도 검토",
            "DART 원문 추가 수집: 공급자 점검 오류 800; 기간 시작일 확정 불가",
        ],
    )
    target.write_text(json.dumps(review, ensure_ascii=False, indent=2), encoding="utf-8")
    print("review_sha256", sha256(target.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
