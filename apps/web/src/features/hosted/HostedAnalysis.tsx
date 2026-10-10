import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { createHostedClient, HostedApiError, parsePageSelection, providerLimitCodes, providerLimitMessage, runOutcome, terminalStatuses, type HostedClient, type HostedDocument, type HostedResult, type HostedRun, type Runtime, type Session, type ScopePlan } from "./hostedClient";
import { ResultView } from "./HostedResult";

const scopeCategory: Record<string, string> = { ceo_message: "CEO 메시지", e_narrative: "환경 본문", assurance: "검증 의견서", gri_index: "GRI 색인", environmental_data: "환경 데이터", esg_data: "ESG 데이터", appendix: "부록", toc: "목차", conflict: "분류 충돌", unreadable: "판독 불가", unknown: "분류 미확인", other: "기타" };
const scopeReason: Record<string, string> = { section_boundaries_disagree: "구역 경계가 서로 다름", native_text_missing_or_unusable: "문자층을 읽을 수 없음", navigation_is_not_claim_text: "목차는 주장 본문에서 제외", evidence_search_only: "근거 검색 전용", native_heading: "쪽 제목 기준", section_container: "구역 분류 기준", front_20_pages: "앞쪽 20쪽 범위", ceo_title: "CEO 제목 확인", claim_extraction_candidate: "주장 추출 후보", environmental_section: "환경 구역", readable_environmental_body: "읽을 수 있는 환경 본문", physical_page_heading: "실제 쪽 제목", environmental_density: "환경 내용 밀도", source_role_unresolved: "기존 구역 분류 미확인", insufficient_environmental_body_density: "환경 본문 밀도 부족", "scope_only_intro_ceo_hierarchy;original_conflict_preserved": "CEO 구역으로 제안하되 원래 분류 충돌 보존" };
const stageLabel: Record<string, string> = { queued: "대기", parse: "문서 파싱", extract: "주장 추출", tag: "요소 태깅", result: "결과 정리" };
const statusLabel: Record<string, string> = { queued: "대기 중", running: "분석 중", accounting_pending: "비용 정산 확인 중", partial_blocked: "보류", completed: "완료", cancelled: "취소됨", failed: "실패" };

export function RuntimeOff({ runtime }: { runtime: Runtime }) {
  return <div className="hosted-notice" role="status">
    <h3>현재 실시간 분석이 꺼져 있습니다</h3>
    <p>서버에서 실시간 분석(OCR·모델)을 아직 열지 않았습니다. 업로드·접수는 시험 운영 중이며 {runtime.accept_new_runs ? "분석 접수는 열려 있으나 결과는 보류로 표시됩니다." : "새 분석 접수는 중지되어 있습니다."}</p>
    <p><Link className="primary-link" to="/demo">저장된 분석 사례 보기 ↗</Link></p>
  </div>;
}

export function RunOutcomeView({ run }: { run: HostedRun }) {
  const outcome = runOutcome(run);
  return <div className={`hosted-outcome hosted-${outcome.kind}`} role="status" aria-live="polite">
    <p className="eyebrow">분석 {run.run_id.slice(0, 8)}</p>
    <h3>{outcome.title}<small> · {run.selected_pages.join(", ")}쪽</small></h3>
    {outcome.kind === "pending" && <>
      <p>{statusLabel[run.status] ?? run.status}{run.stage ? ` · 단계: ${stageLabel[run.stage] ?? run.stage}` : ""}
        {typeof run.queue_position === "number" && ` · 대기 순번 ${run.queue_position}`}
        {typeof run.progress === "number" && ` · 진행 ${Math.round(run.progress * 100)}%`}</p>
      {typeof run.progress === "number" && <progress max={1} value={Math.min(Math.max(run.progress, 0), 1)} aria-label="분석 진행률" />}
      {typeof run.claims_extracted === "number" && <p>추출된 주장 {run.claims_extracted}개 · 태깅 처리 {run.claims_processed ?? 0}개</p>}
      <p className="hosted-note">진행률은 단계 추정치이며 분석 품질이나 완료를 보증하지 않습니다.</p></>}
    {outcome.reasons.map(reason => <p key={reason}>{reason}</p>)}
  </div>;
}

type Phase = "checking" | "login" | "ready";
type Intake = { key: string; name: string; doc?: HostedDocument; error?: string };

export function HostedAnalysis({ client: injected }: { client?: HostedClient }) {
  const client = useMemo(() => injected ?? createHostedClient({ base: import.meta.env.VITE_HOSTED_API_BASE || "/hosted-api" }), [injected]);
  const [runtime, setRuntime] = useState<Runtime | null>(null);
  const [phase, setPhase] = useState<Phase>("checking");
  const [session, setSession] = useState<Session | null>(null);
  const [code, setCode] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [intake, setIntake] = useState<Intake[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const uploadAbort = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const expire = useCallback(() => {
    uploadAbort.current?.abort(); setSession(null); setIntake([]); setFiles([]); setNotice(""); setPhase("login");
    if (fileInput.current) fileInput.current.value = "";
  }, []);
  const fail = useCallback((err: unknown) => {
    if (err instanceof HostedApiError) {
      setError(`${err.userMessage} (${err.code})`);
      if (err.status === 401) expire();
    } else if (err instanceof Error) setError(err.message);
  }, [expire]);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const rt = await client.runtime();
        if (!live) return; setRuntime(rt);
        try { const next = await client.session(); if (live) { setSession(next); setPhase("ready"); } }
        catch (err) { if (live && err instanceof HostedApiError && err.status === 401) setPhase("login"); else throw err; }
      } catch (err) { if (live) { fail(err); setPhase("login"); } }
    })();
    return () => { live = false; uploadAbort.current?.abort(); };
  }, [client, fail]);

  async function login(event: FormEvent) {
    event.preventDefault(); setError(""); setBusy("로그인 중");
    try { setSession(await client.login(code)); setCode(""); setPhase("ready"); } catch (err) { fail(err); } finally { setBusy(""); }
  }
  async function upload() {
    const controller = new AbortController(); uploadAbort.current = controller;
    setError(""); setBusy("업로드 중");
    for (const file of files) {
      if (controller.signal.aborted) break;
      const key = crypto.randomUUID();
      try {
        if (new TextDecoder().decode(await file.slice(0, 4).arrayBuffer()) !== "%PDF") throw new Error("PDF 파일을 선택해 주세요.");
        if (runtime && file.size > runtime.limits.max_upload_bytes) throw new Error(`PDF가 ${Math.floor(runtime.limits.max_upload_bytes / 1048576)}MB를 넘습니다.`);
        const doc = await client.uploadDocument(file, undefined, controller.signal);
        if (!controller.signal.aborted) setIntake(items => [...items, { key, name: file.name, doc }]);
      } catch (err) {
        if (controller.signal.aborted) break;
        if (err instanceof HostedApiError && err.status === 401) { fail(err); break; }
        const message = err instanceof HostedApiError ? `${err.userMessage} (${err.code})` : err instanceof Error ? err.message : "업로드 실패";
        setIntake(items => [...items, { key, name: file.name, error: message }]);
      }
    }
    setFiles([]); if (fileInput.current) fileInput.current.value = ""; setBusy("");
  }
  async function logout() {
    uploadAbort.current?.abort();
    try { await client.logout(); } catch { /* session may already be gone */ }
    expire(); setFiles([]); setError("");
  }
  function loginForm() {
    return <form className="hosted-login" onSubmit={login}>
      <label>초대 코드<input type="password" autoComplete="off" value={code} onChange={event => setCode(event.target.value)} required minLength={32} /></label>
      <button type="submit" disabled={!!busy}>초대 코드로 입장</button>
    </form>;
  }
  let body: ReactNode;
  if (phase === "checking") body = <p role="status">서버 상태 확인 중…</p>;
  else if (phase === "login") body = <>
    {runtime && !runtime.live_analysis && <RuntimeOff runtime={runtime} />}
    {loginForm()}
  </>;
  else body = <>
    {runtime && !runtime.live_analysis && <RuntimeOff runtime={runtime} />}
    {runtime && <p className="hosted-notice-text" data-testid="upload-notice">{runtime.upload_notice}</p>}
    <div className="hosted-upload">
      <label>PDF 보고서<input ref={fileInput} type="file" accept=".pdf,application/pdf" multiple disabled={!!busy} onChange={event => setFiles(Array.from(event.target.files ?? []))} /></label>
      <button type="button" disabled={!files.length || !!busy || runtime?.accept_uploads === false} onClick={() => void upload()}>업로드</button>
    </div>
    <p className="hosted-note">{runtime?.maintenance ? "각 문서의 범위를 확인하세요. 새 분석은 서버 점검이 끝난 뒤 접수할 수 있습니다." : "여러 PDF를 선택할 수 있습니다. 각 문서의 범위를 확인하고 분석을 시작하세요. 다른 문서가 분석 중이어도 추가 업로드와 접수가 가능합니다."}</p>
    {runtime?.accept_uploads === false && <p className="hosted-error">현재 업로드가 닫혀 있습니다.</p>}
    <ul className="hosted-documents" aria-label="문서별 분석 상태">
      {intake.map(item => <li key={item.key}>
        {item.doc ? <HostedDocumentAnalysis name={item.name} doc={item.doc} client={client} runtime={runtime} session={session} onExpired={expire} onRemoved={() => { setIntake(items => items.filter(next => next.key !== item.key)); setNotice(`${item.name} 원본 PDF와 분석 기록을 삭제했습니다.`); }} />
          : <article><h3>{item.name}</h3><p role="alert" className="hosted-error">{item.error}</p></article>}
      </li>)}
    </ul>
  </>;
  return <section className="surface live-report hosted-analysis" aria-label="호스팅 분석">
    <p className="eyebrow">HOSTED ANALYSIS</p><h2>무인 보고서 분석 (초대 코드)</h2>
    <p>실행 비용 상한 USD 1.0 · 일·행사 USD 7. 사람 검토 없이 처리하되 등급은 잠정·미확정으로 구분합니다.</p>
    {session && <p className="hosted-session">로그인됨 · {session.role ?? "역할 없음"} <button type="button" onClick={() => void logout()}>로그아웃</button></p>}
    {Object.values(runtime?.provider_limits ?? {}).some(limit => limit.status === "blocked") && <p className="hosted-error" role="alert">{providerLimitMessage}</p>}
    {runtime?.maintenance && <p className="hosted-notice" role="status">{runtime.maintenance_message ?? "서버 점검 중입니다. 새 분석은 점검 후 접수합니다."}</p>}
    {body}
    {notice && <p role="status">{notice}</p>}
    {busy && <p role="status">{busy}…</p>}
    {error && <p className="hosted-error" role="alert">{error}</p>}
  </section>;
}

function HostedDocumentAnalysis({ name, doc, client, runtime, session, onExpired, onRemoved }: {
  name: string; doc: HostedDocument; client: HostedClient; runtime: Runtime | null; session: Session | null; onExpired: () => void; onRemoved: () => void;
}) {
  const [profile, setProfile] = useState(runtime?.pipeline_profile ?? "unattended-v1");
  const [pages, setPages] = useState("");
  const [evidencePages, setEvidencePages] = useState("");
  const [reportYear, setReportYear] = useState("");
  const [periodStart, setPeriodStart] = useState("");
  const [periodEnd, setPeriodEnd] = useState("");
  const [scope, setScope] = useState<ScopePlan | null>(null);
  const [run, setRun] = useState<HostedRun | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [scopeConflict, setScopeConflict] = useState(false);
  const [result, setResult] = useState<HostedResult | null>(null);
  const abort = useRef<AbortController | null>(null);

  const fail = useCallback((err: unknown) => {
    if (err instanceof HostedApiError) {
      setError(`${err.userMessage} (${err.code})`);
      if (err.code === "SCOPE_CONFLICT") setScopeConflict(true);
      if (err.status === 401) onExpired();
    } else if (err instanceof Error) setError(err.message);
  }, [onExpired]);

  useEffect(() => {
    let live = true;
    setBusy("무료 자동 범위 계획 생성 중");
    void client.scopePlan(doc.document_id).then(next => { if (live) applyScope(next); }).catch(err => { if (live) fail(err); }).finally(() => { if (live) setBusy(""); });
    return () => { live = false; abort.current?.abort(); };
  }, [client, doc.document_id, fail]);

  function applyScope(next: ScopePlan) {
    setScope(next); setScopeConflict(false);
    setReportYear(String(next.reporting_scope?.report_year ?? ""));
    setPeriodStart(next.reporting_scope?.period_start ?? "");
    setPeriodEnd(next.reporting_scope?.period_end ?? "");
    const fallback = next.plan.status === "failed" && !next.selection ? next.plan.suggested_front_pages ?? [] : [];
    setPages((next.plan.selected_claim_pages.length ? next.plan.selected_claim_pages : fallback.slice(0, 10)).join(","));
    setEvidencePages((next.plan.selected_evidence_pages.length ? next.plan.selected_evidence_pages : fallback.slice(0, 30)).join(","));
  }
  async function reloadScope() {
    if (!doc) return;
    setError(""); setBusy("최신 계획 불러오는 중");
    try { applyScope(await client.getScopePlan(doc.document_id)); } catch (err) { fail(err); } finally { setBusy(""); }
  }
  function editedPeriod() {
    if (!scope?.reporting_scope && !reportYear && !periodStart && !periodEnd) return undefined;
    if (!/^\d{4}$/.test(reportYear) || !periodStart || !periodEnd || periodStart > periodEnd) throw new Error("보고연도와 보고기간 시작·종료일을 확인해 주세요.");
    return { report_year: Number(reportYear), period_start: periodStart, period_end: periodEnd };
  }
  function periodChanged() {
    return reportYear !== String(scope?.reporting_scope?.report_year ?? "") || periodStart !== (scope?.reporting_scope?.period_start ?? "") || periodEnd !== (scope?.reporting_scope?.period_end ?? "");
  }
  async function saveScope() {
    if (!doc || !scope) return;
    setError(""); setBusy("범위 저장 중");
    try {
      applyScope(await client.editScope(doc.document_id, scope,
        parsePageSelection(pages, doc.page_count, 10), parsePageSelection(evidencePages, doc.page_count, 30), periodChanged() ? editedPeriod() : undefined));
    } catch (err) { fail(err); } finally { setBusy(""); }
  }
  async function start() {
    if (!doc || !scope) return;
    setError(""); setBusy("접수 중");
    abort.current?.abort();
    const controller = new AbortController(); abort.current = controller;
    try {
      const claims = parsePageSelection(pages, doc.page_count, 10);
      const evidence = parsePageSelection(evidencePages, doc.page_count, 30);
      const period = periodChanged() ? editedPeriod() : undefined;
      const changed = periodChanged() || !scope.selection || claims.join(",") !== scope.plan.selected_claim_pages.join(",") || evidence.join(",") !== scope.plan.selected_evidence_pages.join(",");
      const current = changed ? await client.editScope(doc.document_id, scope, claims, evidence, period) : scope;
      if (controller.signal.aborted) return;
      applyScope(current);
      const accepted = await client.createRun(doc.document_id, current, undefined, profile);
      if (controller.signal.aborted) return;
      setRun(accepted); setResult(null); setBusy("");
      const finished = await client.pollRun(accepted, next => { if (!controller.signal.aborted) setRun(next); }, controller.signal);
      if (!controller.signal.aborted) await showResult(finished, controller.signal);
    } catch (err) { if (!controller.signal.aborted) fail(err); }
    finally { if (abort.current === controller) setBusy(current => current === "접수 중" ? "" : current); }
  }
  async function showResult(finished: HostedRun, signal: AbortSignal) {
    if (finished.status !== "partial_blocked" && finished.status !== "completed") return;
    if (finished.result) { setResult(finished.result); return; }
    if (finished.result_url) {
      const next = await client.getResult(finished.result_url, signal);
      if (!signal.aborted) setResult(next);
    }
  }
  async function reloadResult() {
    setError("");
    try { if (run?.result_url) setResult(await client.getResult(run.result_url)); } catch (err) { fail(err); }
  }
  async function cancel() {
    if (!run) return; setError(""); setBusy("취소 중");
    try { const cancelled = await client.cancelRun(run.run_id); abort.current?.abort(); setRun(cancelled); } catch (err) { fail(err); }
    finally { setBusy(""); }
  }
  async function remove() {
    if (!doc || !window.confirm("업로드한 원본 PDF와 분석 기록을 삭제합니다. 계속할까요?")) return;
    setError(""); setBusy("삭제 중");
    try {
      const deletion = await client.deleteDocument(doc.document_id);
      if (deletion.status !== "completed") throw new Error("삭제가 완료되지 않았습니다. 잠시 후 다시 시도해 주세요.");
      abort.current?.abort(); onRemoved();
    } catch (err) {
      if (err instanceof HostedApiError && err.status === 403) setError("삭제 권한이 없습니다. 본인이 올린 문서이거나 테넌트 관리자(admin)여야 삭제할 수 있습니다.");
      else fail(err);
    } finally { setBusy(""); }
  }
  const running = !!run && !terminalStatuses.includes(run.status);
  const providerBlocked = Object.values(runtime?.provider_limits ?? {}).some(limit => limit.status === "blocked")
    || (!!run?.error_code && providerLimitCodes.includes(run.error_code));
  return <article className="hosted-document" data-testid="document-analysis">
    <h3>{name}</h3>
    <p role="status" data-testid="document-status">{run ? `${statusLabel[run.status] ?? run.status}${run.status === "queued" && run.queue_position ? ` · 대기 ${run.queue_position}번째` : run.status === "running" && run.stage ? ` · ${stageLabel[run.stage] ?? run.stage}` : ""}` : scope ? "분석 접수 가능" : "범위 계획 준비 중"}</p>
    <details className="hosted-scope" open={!run}><summary>분석 범위와 보고기간</summary><div className="hosted-pages">
      <p>업로드 완료 · 총 {doc.page_count}쪽. 자동 선택: 주장 최대 10쪽 · 근거 검색 최대 30쪽(주장 포함). 수정하지 않으면 이 범위로 진행합니다.</p>
      {!scope && <button type="button" disabled={!!busy} onClick={() => { setBusy("자동 범위 계획 생성 중"); void client.scopePlan(doc.document_id).then(applyScope).catch(fail).finally(() => setBusy("")); }}>자동 범위 계획 생성</button>}
      {scope && <>
        <p>계획 상태: {scope.plan.status} · 선택 범위만 분석하며 원문 확인 필요 항목은 잠정 결과로 표시합니다.</p>
        <fieldset disabled={!!busy || running}>
          <legend>문서 보고기간</legend>
          <p>{scope.reporting_scope?.origin === "detected" ? "원문에서 감지" : scope.reporting_scope?.origin === "manual" ? "사람이 수정한 기간" : "운영자 기본값"} · {scope.reporting_scope?.report_year ?? "입력 필요"}년 ({scope.reporting_scope?.period_start ?? "미확인"} ~ {scope.reporting_scope?.period_end ?? "미확인"})</p>
          {scope.reporting_scope?.warning && <p role="status">{scope.reporting_scope.warning}</p>}
          <label>보고연도<input aria-label="보고연도" type="number" min="1900" max="2100" value={reportYear} onChange={event => setReportYear(event.target.value)} /></label>
          <label>보고기간 시작<input aria-label="보고기간 시작" type="date" value={periodStart} onChange={event => setPeriodStart(event.target.value)} /></label>
          <label>보고기간 종료<input aria-label="보고기간 종료" type="date" value={periodEnd} onChange={event => setPeriodEnd(event.target.value)} /></label>
          <details><summary>보고기간 원문과 예외</summary>
            {scope.plan.reporting_period_detection?.candidates.map((candidate, i) => <p key={`candidate-${i}`}>{candidate.source_ref.physical_page}쪽 · {candidate.source_ref.quote}</p>)}
            {scope.plan.reporting_period_detection?.exceptions.map((exception, i) => <p key={`exception-${i}`}>예외 · {exception.source_ref.physical_page}쪽 · {exception.source_ref.quote}</p>)}
            <p className="hosted-note">예외 문장으로 중심 보고기간을 넓히지 않습니다. 보고기간 설정은 주장·수치·목표연도의 근거 검증을 대신하지 않습니다.</p>
          </details>
        </fieldset>
        {scope.plan.failure_reasons.map(reason => <p role="alert" key={reason}>자동 범위 선택 실패: {reason}</p>)}
        {scope.plan.status === "failed" && <p className="hosted-note">앞쪽 제안 쪽을 기본값으로 넣었습니다. 원본을 확인하고 수동 범위를 지정하세요. 자동 분류 실패·판독 불명확 상태는 유지되며 근거 검증을 대신하지 않습니다.</p>}
        {scopeConflict && <button type="button" disabled={!!busy || running} onClick={() => void reloadScope()}>최신 계획 다시 불러오기</button>}
        <label>주장 쪽 번호<input value={pages} onChange={event => setPages(event.target.value)} disabled={!!busy || running} aria-label="주장 쪽 번호" /></label>
        <label>근거 검색 쪽 번호<input value={evidencePages} onChange={event => setEvidencePages(event.target.value)} disabled={!!busy || running} aria-label="근거 검색 쪽 번호" /></label>
        <button type="button" disabled={!!busy || running || scopeConflict} onClick={() => void saveScope()}>범위 수정 저장</button>
        <details open><summary>쪽별 분류와 선택 이유</summary><table><thead><tr><th>원본 쪽</th><th>분류</th><th>선택</th><th>이유</th></tr></thead><tbody>{scope.plan.pages.map(page => <tr key={page.page}><td>{page.page}</td><td>{scopeCategory[page.category] ?? page.category}</td><td>{scope.plan.selected_claim_pages.includes(page.page) ? "주장·근거" : scope.plan.selected_evidence_pages.includes(page.page) ? "근거 전용" : "제외"}</td><td>{page.reasons.map(reason => scopeReason[reason] ?? reason).join(" · ")}</td></tr>)}</tbody></table></details>
      </>}
      <label>분석 프로필<select aria-label="분석 프로필" value={profile} onChange={event => setProfile(event.target.value)} disabled={!!busy || running}>
        {!profile.startsWith("finals-unattended-") && <option value={profile}>기존 프로필</option>}
        <option value="finals-unattended-v1">v1 · 단계 중첩</option>
        <option value="finals-unattended-v2">v2 · 원문 대조 후 태깅</option>
      </select></label>
      <p className="hosted-note">v2 기본값은 잠정 설정이며 QI2 검토 이후 확정합니다.</p>
      <button type="button" disabled={!!busy || running || !scope || scopeConflict || providerBlocked || runtime?.accept_new_runs === false} onClick={() => void start()}>분석 시작</button>
      {runtime?.accept_new_runs === false && !runtime.maintenance && <p className="hosted-error">현재 새 분석 접수가 중지되어 있습니다.</p>}
    </div></details>
    {run && <RunOutcomeView run={result ? { ...run, result } : run} />}
    {run?.error_code && <p className="hosted-error">오류 코드: {run.provider_error_code ?? run.error_code}</p>}
    {result && run && <ResultView result={result} role={session?.role} client={client} runId={run.run_id} onReload={reloadResult} />}
    {running && <button type="button" disabled={!!busy} onClick={() => void cancel()}>분석 취소</button>}
    {doc && <p className="hosted-note">업로드한 PDF는 올린 본인 또는 테넌트 관리자(admin)가 삭제할 수 있습니다. 삭제하면 원본과 분석 기록이 함께 지워집니다.</p>}
    {doc && <button type="button" className="hosted-danger" disabled={!!busy} onClick={() => void remove()}>업로드한 PDF 삭제</button>}

    {busy && <p role="status">{busy}…</p>}
    {error && <p className="hosted-error" role="alert">{error}</p>}
    {providerBlocked && <p className="hosted-error">{providerLimitMessage}</p>}
  </article>;
}
