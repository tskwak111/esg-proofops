import { useState, type FormEvent } from "react";
import { getElementLabel } from "../labels";

type Decision = { evidence_grade: string | null; grade_range: { floor: string; ceiling: string } | null; decision_status: string };
type Claim = { quote: string; page: number; track: string | null; source_verified: boolean; blocked_reason: string | null; elements: { name: string; element_id: string; state: string; quote: string | null; source_verified: boolean }[]; decision: Decision | null };
type Result = { claims: Claim[]; pages: number[]; duration_ms: number; cost_usd: number; tagging_passes?: number; notice: string };
const tracks: Record<string, string> = { goal: "목표", performance: "성과", management: "관리체계" };
const errors: Record<string, string> = { ACCESS_DENIED: "접근 키를 확인해 주세요.", BODY_TOO_LARGE: "선택한 쪽의 PDF가 4MB를 넘습니다. 쪽수를 줄여 주세요.", INVALID_PDF: "선택한 PDF를 읽지 못했습니다.", INVALID_PAGES: "쪽 번호를 확인해 주세요.", UPSTAGE_UNAVAILABLE: "문서 파싱을 완료하지 못했습니다. 다시 시도해 주세요.", LUNA_UNAVAILABLE: "주장 분석을 완료하지 못했습니다. 다시 시도해 주세요.", REQUEST_COST_CAP: "요청 비용 한도를 넘습니다. 쪽수를 줄여 주세요." };

function parsePages(value: string, total: number): number[] {
  const pages: number[] = [];
  for (const token of value.split(",")) {
    const match = token.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!match) throw new Error("쪽 번호를 26,28,31 또는 26-28 형식으로 입력해 주세요.");
    const start = Number(match[1]); const end = Number(match[2] || match[1]);
    if (start < 1 || end > total || end < start || end - start > 9) throw new Error(`1–${total}쪽 중 최대 10쪽을 선택해 주세요.`);
    for (let page = start; page <= end; page++) if (!pages.includes(page)) pages.push(page);
  }
  if (!pages.length || pages.length > 10) throw new Error("1–10쪽을 선택해 주세요.");
  return pages;
}

export function LiveReport({ file }: { file: File }) {
  const [range, setRange] = useState("");
  const [code, setCode] = useState("");
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const busy = !!stage && stage !== "완료";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setStage("선택한 쪽 준비 중"); setError(""); setResult(null);
    try {
      const { PDFDocument } = await import("pdf-lib");
      const original = await PDFDocument.load(await file.arrayBuffer());
      const pages = parsePages(range, original.getPageCount());
      const selected = await PDFDocument.create();
      const copies = await selected.copyPages(original, pages.map(page => page - 1));
      copies.forEach(page => selected.addPage(page));
      const bytes = await selected.save({ useObjectStreams: true });
      if (bytes.length > 4_000_000) throw new Error("선택한 쪽의 PDF가 4MB를 넘습니다. 쪽수를 줄여 주세요.");
      setStage("문서 파싱 · 원문 대조 · 규칙 판정 중");
      const response = await fetch("/api/live-report", { method: "POST", body: new Blob([new Uint8Array(bytes)], { type: "application/pdf" }),
        headers: { "X-Demo-Access-Code": code, "X-Page-Numbers": JSON.stringify(pages) }, cache: "no-store" });
      const data = await response.json() as Result & { error?: string };
      if (!response.ok) throw new Error(errors[data.error || ""] || `분석을 완료하지 못했습니다 (${response.status}).`);
      if (!Array.isArray(data.claims)) throw new Error("분석 결과를 읽지 못했습니다.");
      setResult(data); setStage("완료");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "분석을 완료하지 못했습니다."); setStage("");
    }
  }

  return <section className="surface live-report" aria-label="실시간 보고서 분석">
    <p className="eyebrow">LIVE REPORT</p><h2>실시간 분석</h2>
    <p>선택한 쪽만 분석 서비스로 전송합니다. 원본 PDF는 이 브라우저에 남습니다.</p>
    <form onSubmit={submit} className="live-report-form">
      <label>분석할 쪽 <small>최대 10쪽 · 예: 26,28,31 또는 26-28</small><input value={range} onChange={event => setRange(event.target.value)} required placeholder="26,28,31" /></label>
      <label>접근 키<input type="password" autoComplete="off" value={code} onChange={event => setCode(event.target.value)} required placeholder="접근 키" /></label>
      <button type="submit" disabled={busy}>{busy ? stage : "실시간 분석 시작 ↗"}</button>
    </form>
    {error && <p className="live-report-error" role="alert">{error}</p>}
    {stage && <p className="live-report-stage" role="status">{stage}</p>}
    {result && <div className="live-report-results"><h3>선택한 쪽의 분석 결과</h3><p>{result.pages.join(", ")}쪽 · {result.claims.length}건 · {(result.duration_ms / 1000).toFixed(1)}초 · 처리 비용 ${result.cost_usd.toFixed(4)} · 사용자 최종 검토 전</p>
      {result.claims.length === 0 && <p>확인 가능한 환경 주장을 찾지 못했습니다. 다른 쪽을 선택해 주세요.</p>}
      <ol>{result.claims.map((claim, index) => <li key={`${claim.page}-${index}`}>
        <div className="live-report-claim-head"><strong>{claim.page}쪽 · {claim.track ? tracks[claim.track] || claim.track : "분류 검토 필요"}</strong><span>{claim.source_verified ? "원문 확인" : "원문 대조 필요"}</span></div>
        <blockquote>{claim.quote}</blockquote>
        {claim.decision?.evidence_grade ? <p>규칙 판정 {claim.decision.evidence_grade}</p> : claim.decision?.grade_range ? <p>가능 범위 {claim.decision.grade_range.floor}–{claim.decision.grade_range.ceiling} · 검토 필요</p> : <p>{claim.blocked_reason || "판정 검토 필요"}</p>}
        {claim.elements.length > 0 && <details><summary>요소와 근거</summary><ul>{claim.elements.map(element => <li key={element.name}><strong>{getElementLabel(element.element_id)}</strong> · {element.state === "present" ? "근거 확인" : "미확인"}{element.quote && <q>{element.quote}</q>}</li>)}</ul></details>}
      </li>)}</ol>
    </div>}
  </section>;
}
