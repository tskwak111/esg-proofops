"""Append the inspected p213 assurance and official DART cover to review v3."""

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import pypdfium2 as pdfium
from proofops.domain.values import SourceRef

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / ".local/final-review"
    target = directory / "review-v3.json"
    if target.exists():
        raise ValueError("immutable review already exists")
    prior = directory / "review-v2.json"
    r = json.loads(prior.read_text("utf-8"))
    pdf_path = next(ROOT.glob("*/NAVER_2024_KOR.pdf"))
    assert sha256(pdf_path.read_bytes()).hexdigest() == r["source_sha256"]
    doc = pdfium.PdfDocument(pdf_path)
    page = doc[212]
    raw = page.get_textpage().get_text_range()
    period = "2024년 1월 1일 ~ 2024년 12월 31일"
    assert period in raw
    fragments = {
        "assurance_covered": raw[raw.index("한국표준협회는") : raw.index("• 적용방법론")],
        "method": raw[raw.index("• 적용방법론") : raw.index("• 근거자료")],
        "calculation_boundary": raw[raw.index("• 현장검증") : raw.index("• 검증방법")],
        "numerical_check": raw[raw.index("부록. 온실가스 감축량") :],
    }
    for entry in r["claims"].values():
        if entry["index"] not in (0, 2, 21):
            continue
        for name, quote in fragments.items():
            ref = SourceRef(
                source_id=str(uuid5(NAMESPACE_URL, r["source_sha256"] + "p213/" + name)),
                **r["identity"],
                page_num=213,
                printed_page_label="213",
                bbox=(0, 0, page.get_width(), page.get_height()),
                raw_text_sha256=sha256(raw.encode()).hexdigest(),
                quote=quote,
                char_start=raw.index(quote),
                char_end=raw.index(quote) + len(quote),
                location_quality="located",
                verification_state="verified",
            )
            entry["accepted_facts"].append(name)
            entry["fact_sources"][name] = dict(
                ref=asdict(ref),
                scope="computed_check" if name == "numerical_check" else "global_bound",
                normalized_value="covered" if name == "assurance_covered" else None,
            )
        entry["notes"].append(
            "추가 검토: 213쪽의 해당 사업·기간·방법론·제한적 보증을 명시 연결. "
            "시설별 합계 및 전체 14개 행 합계 30,925를 계산 확인. 209쪽 배출량 보증과 구분."
        )
    assert 610 + 106 + 51 + 10388 == 11155
    assert 181 + 11161 + 91 == 11433
    assert sum([1931, 78, 5348, 2, 927, 0, 51, 181, 11161, 91, 610, 106, 51, 10388]) == 30925
    cover = directory / "dart-cover.html"
    r["period_review"] = dict(
        claim_indices=[0, 2, 21],
        start="2024-01-01",
        end="2024-12-31",
        sr_page=213,
        sr_quote="감축기간 : " + period,
        financial_artifact=".local/final-review/dart-cover.html",
        financial_sha256=sha256(cover.read_bytes()).hexdigest(),
        financial_quote="사업연도 2024년 01월 01일 부터 2024년 12월 31일 까지",
        financial_url="https://dart.fss.or.kr/report/viewer.do?rcpNo=20250318000645&dcmNo=10419950&eleId=1&offset=955&length=4528&dtd=dart3.xsd",
    )
    r["version"] = 3
    r["previous_review_sha256"] = sha256(prior.read_bytes()).hexdigest()
    r["limitations"].append(
        "DART API 점검 중 공식 공시 뷰어 표지로 재무 기간 확인. 감축사업 3개만 기간 연결 승인."
    )
    target.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
    print(sha256(target.read_bytes()).hexdigest())


if __name__ == "__main__":
    main()
