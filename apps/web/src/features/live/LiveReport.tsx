import { pickPages } from "./sectionHeuristics";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { getElementLabel } from "../labels";
import { LiveExport } from "./LiveExport";
import { localAnalysisErrors } from "./liveErrors";
import type { PageInfo, Section } from "./sectionPicker";

type Decision = { evidence_grade: string | null; label?: string | null; missing_elements?: string[]; unresolved_elements?: string[]; gate_reasons?: string[]; grade_range: { floor: string; ceiling: string; open_elements?: string[] } | null; decision_status: string };
export type LiveResultClaim = Claim;
type Claim = { quote: string; page: number; track: string | null; source_verified: boolean; blocked_reason: string | null; elements: { name: string; element_id: string; state: string; candidate_state?: string; binding_status?: string; page?: number; quote: string | null; source_verified: boolean }[]; decision: Decision | null;
  review?: { status: string; notes: string[]; scope: string; record_sha256: string };
  review_handle?: { run_id: string; claim_index: number; result_sha256: string; document_pages: number };
  normalized?: Record<string, { value: string | null; raw_value?: string; status: string; citation?: { page: number; quote: string } }>;
  crosscheck?: { status: string; original_audit: string };
  dart?: { status: string; checks: { item: string; status: string; reason: string; claim_year?: string | null; financial_year?: string }[] };
};
type Result = { claims: Claim[]; pages: number[]; duration_ms: number; cost_usd: number; tagging_passes?: number; notice: string;
  coverage?: { complete: boolean; unprocessed_blocks: number[]; saturated_blocks: number[] };
  stages?: { name: string; status: string; detail: string }[];
  dart?: { notice: string; url?: string; statement_rows?: number; revenue_candidates?: { account_nm: string; thstrm_amount: string; currency?: string }[] };
  vision?: { pages: { page: number; status: string; reason?: string; candidates?: { text: string; kind: string }[]; metrics?: { vision_only?: { text: string }[] }; chart_bindings?: { points: { metric: string; series: string; value: string; unit: string; year: string | null; number_present_in_pdf: boolean; review_status?: string; labels_present_in_pdf?: boolean }[] } }[] };
};
type DartConfig = { enabled: boolean; corp_code: string; year: string; rcept_no: string; fs_div: string };
const localAnalysis = import.meta.env.VITE_LOCAL_ANALYSIS === "true";
const stageLabels: Record<string, string> = { review_required: "검토 필요", not_applicable: "비적용", candidate_only: "후보 검증 완료", retrieved: "공시 조회 완료", off: "OFF", unavailable: "조회 불가", blocked: "처리 보류" };
const tracks: Record<string, string> = { goal: "목표", performance: "성과", management: "관리체계" };
const errors: Record<string, string> = {
  ...localAnalysisErrors,
  DAILY_LIMIT: "오늘의 분석 비용 한도에 도달했습니다. 내일 다시 이용해 주세요.",
  RATE_LIMITED: "요청이 많습니다. 1분 후 다시 시도해 주세요.",
  LIVE_DISABLED: "실시간 분석이 일시 중지되었습니다.",
  LIMIT_CHECK_UNAVAILABLE: "비용 한도를 확인할 수 없어 분석을 중지했습니다. 잠시 후 다시 시도해 주세요.", ACCESS_DENIED: "접근 키를 확인해 주세요.", BODY_TOO_LARGE: "선택한 쪽의 PDF가 4MB를 넘습니다. 쪽수를 줄여 주세요.", INVALID_PDF: "선택한 PDF를 읽지 못했습니다.", INVALID_PAGES: "쪽 번호를 확인해 주세요.", UPSTAGE_UNAVAILABLE: "문서 파싱을 완료하지 못했습니다. 다시 시도해 주세요.", LUNA_UNAVAILABLE: "주장 분석을 완료하지 못했습니다. 다시 시도해 주세요.", REQUEST_COST_CAP: "요청 비용 한도를 넘습니다. 쪽수를 줄여 주세요." };
const sections: [Section, string][] = [["E", "환경(E)"], ["S", "사회(S)"], ["G", "지배구조(G)"], ["A", "부록"], ["O", "기타"]];
function parsePages(value: string, total: number): number[] {
  const pages: number[] = [];
  for (const token of value.split(",")) {
    const match = token.trim().match(/^(\d+)(?:\s*-\s*(\d+))?$/);
    if (!match) throw new Error("쪽 번호를 26,28,31 또는 26-28 형식으로 입력해 주세요.");
    const start = Number(match[1]); const end = Number(match[2] || match[1]);
    if (start < 1 || end > total || end < start || end - start > 59) throw new Error(`1–${total}쪽 중 최대 60쪽을 선택해 주세요.`);
    for (let page = start; page <= end; page++) if (!pages.includes(page)) pages.push(page);
  }
  if (!pages.length || pages.length > 60) throw new Error("1–60쪽을 선택해 주세요.");
  return pages.sort((a, b) => a - b);
}

export function LiveReport({ file, renderClaims }: { file: File; renderClaims?: (claims: LiveResultClaim[]) => ReactNode }) {
  const panel = useRef<HTMLElement>(null);
  const results = useRef<HTMLElement>(null);
  const [range, setRange] = useState("");
  const [code, setCode] = useState("");
  const [stage, setStage] = useState("");
  const [error, setError] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [info, setInfo] = useState<PageInfo[]>([]);
  const [checked, setChecked] = useState<Section[]>(["E", "A"]);
  const [dropped, setDropped] = useState(0);
  const [dart, setDart] = useState<DartConfig>({ enabled: false, corp_code: "", year: "", rcept_no: "", fs_div: "" });
  const [filings, setFilings] = useState<{ rcept_no: string; report_nm: string; rcept_dt: string }[]>([]);
  const [finding, setFinding] = useState(false);
  const [filingNotice, setFilingNotice] = useState("");
  useEffect(() => {
    const reviewed = (event: Event) => {
      const data = (event as CustomEvent<{parent_run: string; result: Result}>).detail;
      if (!data?.result?.claims) return;
      setResult(previous => {
        if (!previous) return previous;
        const claims = previous.claims.map(claim => claim.review_handle?.run_id === data.parent_run
          ? data.result.claims[claim.review_handle.claim_index] ?? claim : claim);
        const grades = claims.filter(c => c.decision?.evidence_grade).length;
        const ranges = claims.filter(c => c.decision?.grade_range).length;
        return { ...previous, claims, stages: previous.stages?.map(s => s.name === "요소·근거·규칙 판정"
          ? {...s, detail: `등급 ${grades}개 · 범위 ${ranges}개 · 검토 후 재계산 · 프로젝트 해석 기준`} : s) };
      });
    };
    window.addEventListener("report-evidence-reviewed", reviewed);
    return () => window.removeEventListener("report-evidence-reviewed", reviewed);
  }, []);
  async function findFilings() {
    setFinding(true); setFilingNotice(""); setFilings([]);
    try {
      const response = await fetch("/api/dart-filings", { method: "POST", signal: AbortSignal.timeout(30000), headers: { "Content-Type": "application/json", "X-Demo-Access-Code": code }, body: JSON.stringify(dart) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error === "DART_LOOKUP_BUSY" ? "다른 공시 조회가 진행 중입니다. 잠시 후 다시 시도해 주세요." : "공시 조회에 실패했습니다. 입력값과 서버 연결을 확인해 주세요.");
      setFilings(data.filings || []);
      setFilingNotice(data.status === "complete" ? `${data.filings.length}개 후보 · 조회일 ${data.as_of}. 공시를 선택해 주세요.` : "조회가 완전하지 않습니다. 공시 목록을 확인해 주세요.");
    } catch (e) { setFilingNotice(e instanceof Error ? e.message : "DART 조회 실패"); }
    finally { setFinding(false); }
  }
  useEffect(() => {
    if (!localAnalysis) return;
    const controller = new AbortController();
    fetch("/api/local-runtime", { signal: controller.signal }).then(async response => {
      if (!response.ok) throw new Error();
      const runtime = await response.json();
      if (typeof runtime.access_code !== "string") throw new Error();
      if (runtime.model !== "gpt-6-sol") throw new Error("실행 중인 분석 서버가 이전 버전입니다. API 서버를 재시작해 주세요.");
      setCode(runtime.access_code);
    }).catch(reason => { if (!controller.signal.aborted) setError(reason instanceof Error && reason.message ? reason.message : "로컬 분석 서버에 연결할 수 없습니다. 서버 실행 상태를 확인해 주세요."); });
    return () => controller.abort();
  }, []);
  const busy = !!stage && stage !== "완료" && stage !== "일부 완료";
  const selectedPages = useMemo(() => {
    try { return parsePages(range, info.length || 10000); } catch { return []; }
  }, [range, info.length]);

  useEffect(() => {
    let cancelled = false;
    setStage("보고서 목차와 쪽 내용 읽는 중"); setInfo([]); setRange(""); setResult(null); setError("");
    void import("./sectionPicker").then(({ scanSections }) =>
      scanSections(file, (current, total) => { if (!cancelled) setStage(`구역 찾는 중 · ${current}/${total}쪽`); }))
      .then(found => { if (cancelled) return; setInfo(found); const picked = pickPages(found, ["E", "A"]);
        setRange(picked.pages.join(",")); setDropped(picked.dropped); setStage(""); })
      .catch(() => { if (!cancelled) { setStage(""); setError("구역을 자동으로 찾지 못했습니다. 쪽 번호를 직접 입력해 주세요."); } });
    return () => { cancelled = true; };
  }, [file]);
  useEffect(() => { panel.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [file]);
  useEffect(() => { if (result) results.current?.scrollIntoView({ behavior: "smooth", block: "start" }); }, [result]);

  function chooseSection(section: Section) {
    const next = checked.includes(section) ? checked.filter(item => item !== section) : [...checked, section];
    setChecked(next);
    const picked = pickPages(info, next);
    setRange(picked.pages.join(",")); setDropped(picked.dropped); setResult(null);
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setStage("선택한 쪽 준비 중"); setError(""); setResult(null);
    try {
      const { PDFDocument, PDFName } = await import("pdf-lib");
      const originalBytes = await file.arrayBuffer();
      const original = await PDFDocument.load(originalBytes);
      const pages = parsePages(range, original.getPageCount());
      // Link annotations point at other pages, so copying them drags the whole
      // report along; thumbnails and editor data are not page content either.
      for (const page of pages) {
        const node = original.getPage(page - 1).node;
        for (const key of ["Annots", "Thumb", "PieceInfo"]) node.delete(PDFName.of(key));
      }
      const chunks: number[][] = [];
      for (let i = 0; i < pages.length; i += 10) chunks.push(pages.slice(i, i + 10));
      const combined: Result = { claims: [], pages, duration_ms: 0, cost_usd: 0, notice: "사용자 최종 검토 전" };
      const started = performance.now();
      const skipped: number[] = [];
      const failed: string[] = [];
      let successfulBatches = 0;
      let documentId = "";
      if (localAnalysis) {
        if (originalBytes.byteLength > 100 * 1024 * 1024) throw new Error("로컬 분석 PDF 한도는 100MB입니다.");
        const upload = await fetch("/api/local-documents", { method: "POST", headers: { "X-Demo-Access-Code": code }, body: new Blob([originalBytes], { type: "application/pdf" }) });
        const receipt = await upload.json();
        if (!upload.ok || typeof receipt.document_id !== "string") throw new Error("PDF 전송에 실패했습니다.");
        documentId = receipt.document_id;
      }
      for (let i = 0; i < chunks.length; i++) {
        const selected = await PDFDocument.create();
        const copies = await selected.copyPages(original, chunks[i].map(page => page - 1));
        copies.forEach(page => selected.addPage(page));
        const bytes = localAnalysis ? new TextEncoder().encode("{}") : await selected.save({ useObjectStreams: true });
        if (localAnalysis && bytes.length > 100 * 1024 * 1024) throw new Error("로컬 분석 PDF 한도는 100MB입니다.");
        if (!localAnalysis && bytes.length > 4_000_000) {
          if (chunks[i].length === 1) { skipped.push(chunks[i][0]); chunks.splice(i, 1); i--; continue; }
          const half = Math.ceil(chunks[i].length / 2);
          chunks.splice(i, 1, chunks[i].slice(0, half), chunks[i].slice(half)); i--; continue;
        }
        setStage(`문서 파싱 · 원문 대조 · 규칙 판정 중 (${i + 1}/${chunks.length}묶음)`);
        const response = await fetch("/api/live-report", { method: "POST", body: new Blob([new Uint8Array(bytes)], { type: "application/pdf" }),
          headers: { "X-Demo-Access-Code": code, "X-Page-Numbers": JSON.stringify(chunks[i]), ...(localAnalysis ? { "X-Full-Document": "true", "X-Document-Id": documentId, "X-Dart-Config": encodeURIComponent(JSON.stringify(dart)) } : {}) }, cache: "no-store" });
        const data = await response.json().catch(() => ({})) as Result & { error?: string };
        if (response.status === 403) throw new Error(errors[data.error || ""] || "접근 키를 확인해 주세요.");
        if (!response.ok || !Array.isArray(data.claims)) {
          failed.push(`${chunks[i].join(",")}쪽(${errors[data.error || ""] || `분석 오류 (${response.status})`})`);
          continue;
        }
        combined.claims.push(...data.claims);
        if (data.coverage?.complete === false) failed.push(`${chunks[i].join(",")}쪽: 추출 미처리 또는 상한 도달 (부분 결과 보존)`);
        if (data.stages?.some(s => s.status === "일부 완료")) failed.push(`${chunks[i].join(",")}쪽: 모델 분석 일부 완료`);
        successfulBatches++;
        combined.notice = data.notice || combined.notice;
        combined.stages = [...(combined.stages || []), ...(data.stages || []).map(s => ({ ...s, name: `${chunks[i].join(",")}쪽 · ${s.name}` }))];
        combined.dart = data.dart;
        combined.vision = { pages: [...(combined.vision?.pages || []), ...(data.vision?.pages || [])] };
        combined.cost_usd += data.cost_usd;
        combined.duration_ms = Math.round(performance.now() - started);
        setResult({ ...combined, claims: [...combined.claims] });
      }
      const notes = [
        skipped.length ? `이미지가 커서 전송 한도(4MB)를 넘은 ${skipped.join(", ")}쪽은 건너뛰었습니다.` : "",
        failed.length ? `분석하지 못한 묶음: ${failed.join(", ")}` : "",
      ].filter(Boolean).join(" ");
      if (!successfulBatches) {
        setError(notes || "분석을 완료하지 못했습니다.");
        setResult(null); setStage(""); return;
      }
      if (notes) setError(notes);
      setResult({ ...combined, claims: [...combined.claims], duration_ms: Math.round(performance.now() - started) });
      setStage(notes ? "일부 완료" : "완료");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "분석을 완료하지 못했습니다."); setStage("");
    }
  }

  const detectedBy = [...new Set(info.filter(item => selectedPages.includes(item.page)).map(item => item.source))].join("·");
  return <><section ref={panel} className="surface live-report" aria-label="실시간 보고서 분석">
    <p className="eyebrow">LIVE REPORT</p><h2>실시간 분석</h2>
    <p>{localAnalysis ? "전체 PDF를 로컬 분석 서버에 한 번 전송합니다. 설정에 따라 원문은 Docling 실행 서버에, 선택된 원문·차트는 OpenAI에 전달됩니다." : "선택한 쪽만 분석 서비스로 전송합니다. 원본 PDF는 이 브라우저에 남습니다."}</p>
    {localAnalysis && <p>독립 파서 대조 → 연도·범위 정규화 → 요소·근거·판정 → 차트 검증 → 선택적 DART 대사. 후보 근거와 최종 승인을 구분합니다.</p>}
    {info.length > 0 && <div className="live-report-sections"><strong>분석할 구역</strong><div>{sections.map(([id, label]) =>
      <label key={id}><input type="checkbox" checked={checked.includes(id)} onChange={() => chooseSection(id)} /> {label} <small>{info.filter(page => page.section === id).length}쪽</small></label>)}</div>
      <p>구역 판별: {detectedBy || "키워드"} · 기본 선택: 환경(E) + 부록</p>
    </div>}
    <form onSubmit={submit} className="live-report-form">
      <label>분석할 쪽 <small>최대 60쪽 · 예: 26,28,31 또는 83-95,218-244</small><input value={range} onChange={event => { setRange(event.target.value); setDropped(0); }} required placeholder="26,28,31" /></label>
      {localAnalysis ? <p>로컬 분석 서버 연결 · API 키는 서버에서 관리합니다.</p> : <label>접근 키<input type="password" autoComplete="off" value={code} onChange={event => setCode(event.target.value)} required placeholder="접근 키" /></label>}
      {localAnalysis && <fieldset className="dart-settings" disabled={busy || finding}><legend>DART 비교</legend>
        <label><input type="checkbox" checked={dart.enabled} onChange={e => setDart({ ...dart, enabled: e.target.checked })} /> DART 비교 ON / OFF</label>
      <p>기본 OFF. 비교할 기업코드·사업연도·접수번호·재무제표 기준을 입력하세요.</p>
        {dart.enabled && <>
          <label>기업코드<input aria-label="DART 기업코드" value={dart.corp_code} pattern="[0-9]{8}" required onChange={e => { setDart({ ...dart, corp_code: e.target.value, rcept_no: "" }); setFilings([]); }} /></label>
          <label>사업연도<input aria-label="DART 사업연도" value={dart.year} pattern="20[0-9]{2}" required onChange={e => { setDart({ ...dart, year: e.target.value, rcept_no: "" }); setFilings([]); }} /></label>
          <button type="button" onClick={findFilings} disabled={!code}>공시 후보 찾기</button>
          {filingNotice && <p role="status">{filingNotice}</p>}
          {filings.map(f => <label key={f.rcept_no}><input type="radio" name="dart-receipt" checked={dart.rcept_no === f.rcept_no} onChange={() => setDart({ ...dart, rcept_no: f.rcept_no })} /> {f.report_nm} · {f.rcept_dt} · <a href={`https://dart.fss.or.kr/dsaf001/main.do?rcpNo=${f.rcept_no}`} target="_blank" rel="noreferrer">공시 열기</a></label>)}
          <label>접수번호<input aria-label="DART 접수번호" value={dart.rcept_no} pattern="[0-9]{14}" required onChange={e => setDart({ ...dart, rcept_no: e.target.value })} /></label>
          <label>재무제표 기준<select aria-label="DART 재무제표 기준" value={dart.fs_div} required onChange={e => setDart({ ...dart, fs_div: e.target.value })}><option value="">선택 필요</option><option value="OFS">별도 (OFS)</option><option value="CFS">연결 (CFS)</option></select></label>
          <p>선택은 공시 조회 기준입니다. 주장 범위 매핑과 대사 정책의 승인으로 간주하지 않습니다.</p>
        </>}
      </fieldset>}
      <button type="submit" disabled={busy || finding || (localAnalysis && !code)}>{busy ? stage : "실시간 분석 시작 ↗"}</button>
    </form>
    {dropped > 0 && <p className="live-report-selection">60쪽 한도에 맞춰 환경 본문과 환경 키워드 점수가 높은 쪽을 우선 유지하고, {dropped}쪽을 제외했습니다.</p>}
    {selectedPages.length > 0 && <p className="live-report-selection">선택: {selectedPages.length}쪽 · {selectedPages.join(", ")}</p>}
    {error && <p className="live-report-error" role="alert">{error}</p>}
    {stage && <p className="live-report-stage" role="status">{stage}</p>}
  </section>
    {result && <section ref={results} className="surface live-report-results analyze-results" aria-label="분석 결과"><h3>선택한 쪽의 분석 결과</h3>
      <p>{result.notice}</p>
      <LiveExport report={result} />
      {result.stages && <div className="surface pipeline-stages"><h3>단계별 처리 결과</h3>{result.stages.map((s, i) => <div key={i}><strong>{s.name}</strong><span className="badge amber">{stageLabels[s.status] || s.status}</span><p>{s.detail}</p></div>)}</div>}
      {result.dart && <details className="surface"><summary>DART 비교 · {result.dart.notice}</summary>{result.dart.url && <p><a href={result.dart.url} target="_blank" rel="noreferrer">선택한 실제 공시 ↗</a> · 재무제표 {result.dart.statement_rows}행</p>}{result.dart.revenue_candidates?.map((r, i) => <p key={i}>{r.account_nm}: {r.thstrm_amount} {r.currency} · 재무 참고값, 환경 주장과 직접 비교하지 않음</p>)}</details>}
      {!!result.vision?.pages.length && <details className="surface"><summary>차트 비전 검증 · {result.vision.pages.length}쪽</summary>{result.vision.pages.map(v => <section key={v.page}><h4>p.{v.page} · {stageLabels[v.status] || v.status}</h4><p>{v.reason || "비전 후보 · 범례·연도 연결 검토 필요"}</p>{v.chart_bindings && <div className="element-table-wrap"><table className="element-table chart-points"><thead><tr><th>지표</th><th>범례</th><th>수치</th><th>원문 대조</th></tr></thead><tbody>{v.chart_bindings.points.map((pt, i) => <tr key={i}><td>{pt.metric} ({pt.year || "?"})</td><td>{pt.series}{pt.labels_present_in_pdf === false && pt.review_status !== "source_reviewed" && <small> · 범례 문구 대조 필요</small>}</td><td>{pt.value}{pt.unit && !pt.value.endsWith(pt.unit) ? ` ${pt.unit}` : ""}</td><td>{pt.review_status === "source_reviewed" ? "원문 직접 검토 완료" : pt.number_present_in_pdf ? "숫자 확인 / 연결 검토 필요" : "원문 미확인"}</td></tr>)}</tbody></table></div>}{v.chart_bindings?.points.length === 0 && <p>차트의 수치·범례 쌍을 찾지 못했습니다.</p>}</section>)}</details>}
      {renderClaims ? renderClaims(result.claims) : <ol>{result.claims.map((claim, index) => <li key={`${claim.page}-${index}`}>
        <div className="live-report-claim-head"><strong>{claim.page}쪽 · {claim.track ? tracks[claim.track] || claim.track : "분류 검토 필요"}</strong><span>{claim.source_verified ? "원문 확인" : "원문 대조 필요"}</span></div>
        <blockquote>{claim.quote}</blockquote>
        {claim.decision?.decision_status === "blocked_rule_gap" ? <p>{claim.blocked_reason}</p> : claim.decision?.evidence_grade ? <p>규칙 판정 {claim.decision.evidence_grade}</p> : claim.decision?.grade_range ? <p>가능 범위 {claim.decision.grade_range.floor}–{claim.decision.grade_range.ceiling} · 검토 필요</p> : <p>{claim.blocked_reason || "판정 검토 필요"}</p>}
        {claim.elements.length > 0 && <details><summary>요소와 근거</summary><ul>{claim.elements.map(element => <li key={element.name}><strong>{getElementLabel(element.element_id)}</strong> · {element.state === "present" ? "근거 확인" : "미확인"}{element.quote && <q>{element.quote}</q>}</li>)}</ul></details>}
      </li>)}</ol>}
    </section>}
  </>;
}
