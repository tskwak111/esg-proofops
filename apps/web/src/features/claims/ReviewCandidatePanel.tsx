import type { SourceRef } from "../reviews/ReviewWorkspace";

// This is a projection of existing server fields, never an approval operation.
export function ReviewCandidatePanel({ sources, candidateCount, replicaCount, decisionStatus }: {
  sources: SourceRef[];
  candidateCount: number;
  replicaCount: number;
  decisionStatus: string | null;
}) {
  const verified = sources.filter(source => source.verification_state === "verified").length;
  return <section aria-labelledby="review-stages-heading">
    <h2 id="review-stages-heading">원문부터 판정까지</h2>
    <ol>
      <li>추가 검색 후보 (candidate): {candidateCount}건 · 채택 전</li>
      <li>원문 인용 검증 (verified): 연결 원문 {sources.length}건 중 {verified}건</li>
      <li>주장 귀속 (bound): 별도 상태 미제공 · 인용 검증만으로 귀속을 확정하지 않습니다.</li>
      <li>등급 확정 (confirmed): {decisionStatus === "decided" ? "서버 판정 있음 · 아래 등급과 검토 상태 확인" : "미확정 또는 적용 제외 · 아래 판정 상태 확인"}</li>
    </ol>
    <p>미상(unknown), 상충(conflict), 판독 불가(unreadable)는 근거 부재(absent)와 다릅니다.</p>
    <p>기록된 태깅 응답 식별자: {replicaCount}개. 개수만으로 동일 packet의 독립 3회 태깅이나 실행 모드를 확인할 수 없습니다.</p>
    <p>원문 위치와 연도·단위·주장 귀속을 확인한 뒤 기존 검토 화면에서 태그를 수정하세요. 후보 열람은 태그나 판정을 변경하지 않습니다.</p>
  </section>;
}
