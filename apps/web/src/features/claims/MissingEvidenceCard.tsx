import { getElementLabel } from "../labels";

// A display projection only. The server owns evidence admission and every cause.
export type CardSourceRef = { page_num: number; quote: string; verification_state?: string; source_id?: string; char_start?: number; char_end?: number };
export type CardSource = { ref: CardSourceRef; label: string; openable?: boolean };
export type MissingEvidenceCardProps = {
  facts?: string[];
  sources?: CardSource[];
  reasons?: string[];
  evidenceNote?: string;
  nextChecks?: string[];
  pageLabel?: (page: number) => string;
  onSourceOpen?: (ref: CardSourceRef) => void;
  unprovidedFields?: string[];
  element?: { element_id: string; state: string };
  missing?: { reason?: string; undetermined_reason?: string; search?: { absence_admissible?: boolean; scope_note?: string } };
};

export function MissingEvidenceCard({ facts = [], sources = [], reasons = [], evidenceNote, nextChecks = [], pageLabel, onSourceOpen, unprovidedFields = [], element, missing }: MissingEvidenceCardProps) {
  const causes = [...new Set([...reasons, missing?.reason, missing?.undetermined_reason].filter((text): text is string => !!text?.trim()))];
  const foundAbsent = element?.state === "absent" && missing?.search?.absence_admissible === true;
  const known = [...facts, ...(foundAbsent ? [`${getElementLabel(element.element_id)}: 원문에서 확인 안 됨 (검증된 검색 범위)`] : [])];
  const absentScope = foundAbsent && missing?.search?.scope_note;
  const sourceRows = sources.filter(source => Number.isInteger(source.ref.page_num) && source.ref.page_num > 0 && !!source.ref.quote);
  const checks = [...nextChecks, ...(element ? [`${getElementLabel(element.element_id)}의 원문 인용·귀속과 처리 상태를 확인해 주세요.`] : [])];
  const missingFields = [
    !known.length && "확인된 사실", !sourceRows.length && "쪽·인용",
    !causes.length && !foundAbsent && "보류 원인", !checks.length && "다음 확인 항목",
    foundAbsent && !absentScope && "검증된 검색 범위 설명", ...unprovidedFields,
  ].filter((field): field is string => typeof field === "string");
  return <section className="missing-evidence-card" aria-label={element ? `${element.element_id} 확인 카드` : "보류 확인 카드"}>
    <h4>확인된 사실</h4>
    {known.length ? <ul>{known.map((fact, index) => <li key={index}>{fact}</li>)}</ul> : <p>추가로 확인된 사실이 기록되지 않았습니다.</p>}
    {absentScope ? <p>검증한 검색 범위: {absentScope}</p> : null}
    <h4>정확한 원문 (쪽·인용)</h4>
    {sourceRows.length ? <ul className="hold-source-list">{sourceRows.map(({ ref, label, openable }, index) => <li key={`${ref.source_id}:${ref.char_start}:${index}`}>
      <p><strong>{label} · {pageLabel ? pageLabel(ref.page_num) : `${ref.page_num}쪽`}</strong> · {ref.verification_state === "verified" ? "원문 검증 완료 · 요소 귀속은 별도 확인" : "미검증 후보"}</p>
      <blockquote>{ref.quote}</blockquote>
      {onSourceOpen ? <button type="button" disabled={openable === false} onClick={() => onSourceOpen(ref)}>{openable === false ? "원문 이동 위치 미확인" : "이 인용의 원문 보기"}</button> : null}
    </li>)}</ul> : <p>쪽과 인용이 미제공되어 원문 위치를 확인할 수 없습니다.</p>}
    <h4>미해결 원인</h4>
    {causes.length ? <ul>{causes.map((reason, index) => <li key={index}>보류 이유: {reason}</li>)}</ul> : <p>{foundAbsent ? "검증한 검색 범위에서 해당 요소가 확인되지 않았습니다." : "상세 원인은 제공되지 않았습니다. 원문 부재로 판정하지 않습니다."}</p>}
    {evidenceNote ? <p className="hosted-note">{evidenceNote}</p> : null}
    <h4>다음 확인</h4>
    {checks.length ? <ul>{checks.map((check, index) => <li key={index}>{check}</li>)}</ul> : <p>구체적인 확인 항목이 제공되지 않았습니다. 원문과 보류 사유를 먼저 확인해 주세요.</p>}
    {missingFields.length ? <div className="hold-missing-fields"><strong>미제공 정보</strong><ul>{missingFields.map(field => <li key={field}>{field}</li>)}</ul></div> : null}
  </section>;
}
