import type { SourceRef } from "../reviews/ReviewWorkspace";
import { getElementLabel } from "../labels";

export type ElementEvidence = {
  element_id: string;
  evidence_status: "confirmed" | "not_found_in_report" | "undetermined";
  undetermined_reason?: "candidate_needs_review" | "no_text_candidate" | "linkage_unclear" | null;
  engine_state: string;
  reason: string;
  evidence_refs: SourceRef[];
  candidate_refs: SourceRef[];
  search: {
    profile: string;
    profile_sha256: string;
    document_search_sha256: string;
    terms: string[];
    claim_anchor_terms: string[];
    coverage: { page_count: number; searched_pages: number[]; readable_pages?: number[];
      unreadable_pages: number[]; missing_pages: number[]; image_pages?: number[];
      unreviewed_content_pages?: number[]; image_dominant_unreadable_pages?: number[] };
    hits: Array<{ page_num: number; term: string; quote: string; char_start: number; char_end: number }>;
    native_candidates?: Array<{ page_num: number; quote: string; char_start: number; char_end: number;
      linkage: "matched" | "rejected"; rejection_reason: string | null }>;
    candidate_count?: number;
    rejected_candidate_count?: number;
    unresolved_image_pages?: number[];
    scope_note?: string;
    outside_selected_pages?: number[];
    candidate_outside_selected_pages?: number[];
    truncated: boolean;
    absence_admissible: boolean;
  };
};
const statusText = {
  confirmed: "✅ 확인됨",
  not_found_in_report: "⚠️ 보고서에서 찾지 못함",
  undetermined: "❔ 판단 불가",
};
function pageRanges(pages: number[]): string {
  if (!pages.length) return "없음";
  const ranges: string[] = [];
  let start = pages[0], end = start;
  for (const page of pages.slice(1)) {
    if (page === end + 1) end = page;
    else { ranges.push(start === end ? String(start) : `${start}–${end}`); start = end = page; }
  }
  ranges.push(start === end ? String(start) : `${start}–${end}`);
  return ranges.join(", ");
}
export function MissingEvidenceCard({ elements, onSourceOpen }: {
  elements: ElementEvidence[];
  onSourceOpen: (source: SourceRef) => void;
}) {
  return <section aria-labelledby="missing-evidence-heading" data-testid="missing-evidence-card">
    <h3 id="missing-evidence-heading">부족 근거 카드</h3>
    <p>검색 후보는 원문·주장 연결 검토가 필요합니다. 판독이 끝나지 않은 쪽이 있으면 근거 부재를 확정할 수 없습니다.</p>
    {!elements.length ? <p>주장 유형과 요소별 검색 결과가 아직 확인되지 않았습니다.</p> :
      <ul>{elements.map(element => {
        const coverage = element.search.coverage;
        const refs = element.evidence_status === "confirmed" ? element.evidence_refs : element.candidate_refs;
        const native = element.search.native_candidates ?? [];
        const matched = native.filter(candidate => candidate.linkage === "matched");
        const rejected = native.filter(candidate => candidate.linkage === "rejected");
        const outsidePages = element.search.candidate_outside_selected_pages ?? element.search.outside_selected_pages;
        const imagePages = coverage.image_pages ?? element.search.unresolved_image_pages ?? coverage.image_dominant_unreadable_pages ?? [];
        const label = element.evidence_status !== "undetermined" ? statusText[element.evidence_status]
          : element.undetermined_reason === "candidate_needs_review" ? "🔎 후보 있음·확인 필요"
          : element.undetermined_reason === "no_text_candidate"
            ? `⚠️ 텍스트로는 못 찾음${imagePages.length ? `(이미지 쪽 ${imagePages.length}개 미확인)` : ""}`
          : element.undetermined_reason === "linkage_unclear" ? "❔ 연결 불명확" : statusText.undetermined;
        return <li data-undetermined-reason={element.undetermined_reason ?? undefined} key={element.element_id} data-evidence-status={element.evidence_status}>
          <strong>{getElementLabel(element.element_id)} · {label}</strong>
          {element.evidence_status === "not_found_in_report" ? <p>문서 전체 검색에서 찾지 못했습니다. 엔진 입력은 기존 상태를 유지합니다.</p> : null}
          {element.undetermined_reason === "candidate_needs_review" ? <>
            <p>주장과 같은 검색어가 함께 보이는 후보 {matched.length}개입니다. 지표·기간·범위 연결은 원문 확인이 필요합니다.</p>
            <ul>{matched.slice(0, 1).map(candidate => <li key={`${candidate.page_num}:${candidate.char_start}`}>
              <p>{candidate.page_num}쪽 · 미검증 인용 미리보기: {candidate.quote}</p>
            </li>)}</ul>
          </> : null}
          {element.undetermined_reason === "no_text_candidate" ? <p>읽을 수 있는 텍스트에서 이 주장과 연결되는 후보를 찾지 못했습니다.</p> : null}
          {element.undetermined_reason === "linkage_unclear" ? <p>연결 거절 사유: {rejected[0]?.rejection_reason ?? "기존 태깅·원문 연결을 확정할 수 없습니다."}</p> : null}
          {element.engine_state === "conflict" ? <p>근거가 상충하여 검토가 필요합니다.</p> : null}
          {element.engine_state === "not_applicable" ? <p>기존 태깅: 적용 제외</p> : null}
          {element.search.scope_note ? <p>{element.search.scope_note}</p> : null}
          {element.undetermined_reason !== "no_text_candidate" && outsidePages?.length ? <p>정밀 검증 필요(선택 범위 밖): {pageRanges(outsidePages)}쪽</p> : null}
          <p>검색한 쪽: {pageRanges(coverage.searched_pages)} / 전체 {coverage.page_count}쪽<br />
            텍스트 판독불가 쪽: {pageRanges(coverage.unreadable_pages)} · 이미지 내용 미확인 쪽: {pageRanges(imagePages)} ({imagePages.length}개)<br />
            {coverage.unreviewed_content_pages ? <>전체 내용 판독 미완결 쪽: {pageRanges(coverage.unreviewed_content_pages)} · </> : null}
            미검색 쪽: {pageRanges(coverage.missing_pages)}</p>
          <details><summary>검색어·동의어·추가 후보 (원문 근거 {refs.length}개)</summary>
            <p>검색어·동의어: {element.search.terms.join(", ")}</p>
            <p>주장 검색어: {element.search.claim_anchor_terms.join(", ")}</p>
            <p>전체 문서 일치 {element.search.hits.length}건 · 전체 검색 기록은 내보내기에 보존됩니다.</p>
            <p>native 검색 일치 쪽(정밀 검증 전): {pageRanges([...new Set(element.search.hits.map(hit => hit.page_num))])}</p>
            {matched.length > 1 ? <details><summary>다른 미검증 후보 ({matched.length - 1}개)</summary>
              <ul>{matched.slice(1, 4).map(candidate => <li key={`${candidate.page_num}:${candidate.char_start}`}>
                <p>{candidate.page_num}쪽: {candidate.quote}</p>
              </li>)}</ul>
              <p>전체 후보는 내보내기에 보존됩니다.</p>
            </details> : null}
            {rejected.length ? <details><summary>연결 거절 후보 ({rejected.length}개)</summary>
              <ul>{rejected.slice(0, 3).map(candidate => <li key={`${candidate.page_num}:${candidate.char_start}`}>
                <p>{candidate.page_num}쪽: {candidate.quote}</p><p>{candidate.rejection_reason}</p>
              </li>)}</ul>
            </details> : null}
            <ul>{refs.slice(0, 10).map((source, index) => <li key={`${source.source_id}:${index}`}>
              <p>{source.page_num}쪽: {source.quote}</p>
              <button type="button" onClick={() => onSourceOpen(source)}>
                {element.evidence_status === "confirmed" ? "확인된 근거" : "미확정 후보"} 원문 {source.page_num}쪽 보기
              </button>
            </li>)}</ul>
            {refs.length > 10 ? <p>화면에는 처음 10개 위치를 표시합니다. 전체 위치와 검색 기록은 내보내기에 보존됩니다.</p> : null}
          </details>
        </li>;
      })}</ul>}
  </section>;
}
