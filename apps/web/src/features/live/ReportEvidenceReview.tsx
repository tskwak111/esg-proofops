import { factNames } from "./evidenceLabels";
import { useState } from "react";
import type { LiveResultClaim } from "./LiveReport";

export function ReportEvidenceReview({ claim }: { claim: LiveResultClaim }) {
  const [names, setNames] = useState<string[]>([]);
  const [reviewer, setReviewer] = useState("");
  const [note, setNote] = useState("");
  const [coverage, setCoverage] = useState(false);
  const [absent, setAbsent] = useState<string[]>([]);
  const [searchedPages, setSearchedPages] = useState("");
  const [absenceConfirmed, setAbsenceConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  if (!claim.review_handle) return null;
  const candidates = claim.elements.filter(e => e.candidate_state === "present" && e.source_verified && e.state !== "present");
  const missing = claim.elements.filter(e => e.candidate_state !== "present" && e.state === "unknown");
  if (!candidates.length && !missing.length) return null;
  async function submit() {
    setBusy(true); setMessage("");
    try {
      const runtime = await fetch("/api/local-runtime").then(r => r.json());
      const response = await fetch("/api/local-review", { method: "POST", headers: {
        "Content-Type": "application/json", "X-Demo-Access-Code": runtime.access_code,
      }, body: JSON.stringify({ ...claim.review_handle, reviewer, note, confirmed_names: names, coverage_confirmed: coverage,
        absent_names: absent, absence_confirmed: absenceConfirmed, searched_pages: searchedPages.split(",").map(v => Number(v.trim())).filter(v => v > 0) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error === "REVIEW_ASSURANCE_COVERAGE_REQUIRED" ? "보증의 지표·기간·범위 확인이 필요합니다." : `검토 반영 보류: ${data.error || response.status}`);
      window.dispatchEvent(new CustomEvent("report-evidence-reviewed", { detail: data }));
      setMessage("새 검토 리비전으로 재계산했습니다."); setNames([]); setAbsent([]);
    } catch (e) { setMessage(e instanceof Error ? e.message : "검토 저장 실패"); }
    finally { setBusy(false); }
  }
  return <details className="detail-block"><summary>근거 연결 검토 · 재계산</summary>
    <p>원문과 해당 주장의 기업·지표·연도·범위를 확인한 요소만 선택하세요. 등급은 규칙엔진이 계산합니다.</p>
    <fieldset disabled={busy}>{candidates.map(e => <label key={e.name} style={{ display: "block" }}><input type="checkbox" checked={names.includes(e.name)} onChange={event => setNames(event.target.checked ? [...names, e.name] : names.filter(n => n !== e.name))} /> {e.element_id} · {factNames[e.name] || e.name}: {e.quote}</label>)}
      <label>검토자<input value={reviewer} onChange={e => setReviewer(e.target.value)} /></label>
      <label>확인 근거·범위<textarea value={note} onChange={e => setNote(e.target.value)} /></label>
      <label><input type="checkbox" checked={coverage} onChange={e => setCoverage(e.target.checked)} /> 보증서 원문에서 해당 지표·기간·사업장 범위와 제외사항을 확인했습니다.</label>
      {!!missing.length && <details><summary>검색 완료 후 근거 부재 확인</summary><p>미확인은 부재가 아닙니다. 전체 {claim.review_handle.document_pages}쪽을 직접 검토한 경우만 사용하세요.</p>
        {missing.map(e => <label key={e.name} style={{display:"block"}}><input type="checkbox" checked={absent.includes(e.name)} onChange={event => setAbsent(event.target.checked ? [...absent,e.name] : absent.filter(n => n !== e.name))} /> {e.element_id} · {factNames[e.name] || e.name}: 근거 부재 확인</label>)}
        <label>직접 확인한 모든 쪽 번호 (쉼표 구분)<input value={searchedPages} onChange={e => setSearchedPages(e.target.value)} /></label>
        <label><input type="checkbox" checked={absenceConfirmed} onChange={e => setAbsenceConfirmed(e.target.checked)} /> 해당 요소의 근거를 전체 PDF에서 검색·검토했고 찾지 못했습니다.</label>
      </details>}
      <button type="button" disabled={(!names.length && !absent.length) || !reviewer.trim() || !note.trim() || (!!absent.length && !absenceConfirmed)} onClick={submit}>선택 근거 확인 후 재계산</button>
    </fieldset>{message && <p role="status">{message}</p>}
  </details>;
}
