import { useEffect, useMemo, useState } from "react";
import { Link, Route, Routes, useLocation, useNavigate, useParams } from "react-router";
import { LiveClaim } from "./features/live/LiveClaim";
import { DecisionGuide, GuideHelp } from "./DecisionGuide";
import { elementLabels } from "./features/labels";
import "./static-demo.css";

type Evidence = { page: number | null; quote: string };
type Element = { id: string; state: string; evidence: Evidence[] };
type Claim = {
  id: string; page: number | null; track: string | null; quote: string; source_verified: boolean;
  elements: Element[];
  decision: { grade: string | null; label: string | null; grade_range: { floor: string; ceiling: string; open_elements: string[] } | null; status: string; missing: string[]; unresolved: string[] };
  review: { status: string; tag_revision: number; decision_revision: number; audit: string | null };
};
type Snapshot = {
  title: string; generated_at: string; partial: boolean;
  review_confirmation: { status: string; confirmed_by: string; confirmed_at: string; scope: string };
  processed_reports: { title: string; sha256: string; result_path: string; run_label: string; scope: string }[];
  coverage: { pages_processed: number; pages_total: number; pages_unprocessed: number; pages_unreadable: number; claims_discovered: number; claims_decided: number; claims_needs_review: number };
  funnel: { label: string; count: number }[]; funnel_source: string;
  run: { model_ids: string[]; model_note: string; model_binding_hash: string | null; rule_pack_id: string; rule_pack_name: string; rule_pack_hash: string; r72_cost_usd: number; r72_paid_calls: number; r72_elapsed_seconds: Record<string, number>; r85_review_seconds: number; r85_model_calls: number };
  audit: { agreed: number; disagreed: number; uncertain: number; scope: string };
  claims: Claim[];
};

const trackText: Record<string, string> = { management: "관리체계", goal: "목표", performance: "성과" };
const stateText: Record<string, string> = { present: "근거 확인", absent: "근거 없음", unknown: "미확인", conflict: "근거 충돌", unreadable: "판독 불가", not_applicable: "비적용" };
const statusText: Record<string, string> = { decided: "규칙 판정", blocked_evidence: "근거 보류", blocked_rule_gap: "규칙 보류", not_run: "미판정" };
const confirmationText = "AI 위임 검토 → 사용자 확인 완료 (2026-09-29)";

export function StaticDemo() {
  const isLive = useLocation().pathname === "/live";
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${import.meta.env.BASE_URL}demo/naver-2025.json`, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error("snapshot unavailable"); return response.json() as Promise<Snapshot>; })
      .then(setData).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, []);
  return <div className="demo-site">
    <header className="site-header"><div className="site-header-inner">
      <Link className="brand" to="/" aria-label="ProofOps 홈"><span className="brand-mark">P<span>◦</span></span> ProofOps</Link>
      <nav aria-label="주요 메뉴"><Link to="/">소개</Link><Link to="/analyze">보고서 분석</Link><Link to="/demo">실제 결과 보기</Link><Link to="/live">실시간 체험</Link></nav>
      <Link className="header-cta" to="/demo">데모 열기 <span aria-hidden="true">↗</span></Link>
    </div></header>
    {isLive ? <LiveClaim /> : error ? <main className="static-main"><section className="surface"><h1>데모 데이터를 불러오지 못했습니다</h1><p>잠시 후 새로고침해 주세요.</p></section></main> :
      !data ? <main className="static-main"><p role="status">실제 검토 결과를 불러오는 중입니다…</p></main> :
      <Routes><Route path="/" element={<Landing data={data} />} /><Route path="/analyze" element={<Analyze data={data} />} /><Route path="/demo" element={<Demo data={data} />} /><Route path="/demo/:claimId" element={<Demo data={data} />} /><Route path="*" element={<Landing data={data} />} /></Routes>}
    <footer className="site-footer"><div><strong>ProofOps</strong><span>공시 문장의 근거를 읽을 수 있는 검토 기록으로.</span></div><span>부분 실행(선택 페이지 54/244쪽) · {confirmationText}</span></footer>
  </div>;
}

const pipeline = ["PDF 파싱", "주장 추출", "원문 검증", "사전분류 · 태깅", "규칙엔진 등급", "검토", "보고서"];

function Analyze({ data }: { data: Snapshot }) {
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ name: string; matched: boolean; message: string } | null>(null);
  useEffect(() => {
    if (!result?.matched) return;
    const timer = window.setTimeout(() => navigate("/demo"), 2500);
    return () => window.clearTimeout(timer);
  }, [result, navigate]);

  async function inspect(file?: File) {
    if (!file) return;
    setBusy(true); setResult(null);
    try {
      if (!file.name.toLowerCase().endsWith(".pdf") || new TextDecoder().decode(await file.slice(0, 4).arrayBuffer()) !== "%PDF") throw new Error("PDF 파일을 선택해 주세요.");
      if (!window.crypto?.subtle) throw new Error("이 브라우저에서는 파일 지문을 계산할 수 없습니다. HTTPS 또는 localhost에서 다시 열어 주세요.");
      const hash = Array.from(new Uint8Array(await window.crypto.subtle.digest("SHA-256", await file.arrayBuffer()))).map(byte => byte.toString(16).padStart(2, "0")).join("");
      const match = data.processed_reports.find(report => report.sha256 === hash);
      setResult({ name: file.name, matched: !!match, message: match ? "이미 분석된 보고서입니다 — 저장된 실행 결과를 불러옵니다" : "저장된 실행 결과와 일치하지 않습니다." });
    } catch (error) {
      setResult({ name: file.name, matched: false, message: error instanceof Error ? error.message : "파일을 읽지 못했습니다." });
    } finally { setBusy(false); }
  }

  return <main className="static-main analyze-main"><div className="breadcrumb"><Link to="/">홈</Link><span>/</span> 보고서 분석</div>
    <section className="analyze-heading"><p className="eyebrow">REPORT ANALYSIS</p><h1>이미 처리한 보고서라면,<br />결과를 바로 불러옵니다.</h1><p>PDF의 SHA-256 지문을 이 브라우저에서 계산해 저장된 실행 기록과 대조합니다. 파일은 서버로 전송되지 않습니다.</p></section>
    <section className="analyze-grid"><div className="surface analyze-upload"><h2>PDF 보고서 선택</h2><p>파일을 놓거나 눌러 선택하세요.</p><label className="drop-zone" onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); void inspect(event.dataTransfer.files[0]); }}><span aria-hidden="true">↥</span><strong>{busy ? "파일 지문 계산 중…" : "PDF 파일을 여기에 놓기"}</strong><small>또는 클릭해 파일 선택 · PDF는 이 브라우저 안에서만 읽습니다</small><input type="file" accept=".pdf,application/pdf" aria-label="분석할 PDF 선택" disabled={busy} onChange={event => { void inspect(event.target.files?.[0]); event.target.value = ""; }} /></label>
      {result && <div className={`analyze-result ${result.matched ? "match" : "no-match"}`} role="status"><small>{result.name}</small><h3>{result.message}</h3>{result.matched ? <><p>{data.processed_reports[0].run_label} · {data.processed_reports[0].scope}</p><p>원래 모델 파이프라인 약 6.3시간 + 로컬 후처리 약 4분 → 캐시 즉시</p><p>저장된 실행 결과의 재생이며 새 분석이나 전체 보고서 판정이 아닙니다.</p><Link to="/demo">저장된 결과 바로 보기 ↗</Link><small>잠시 후 자동으로 결과 페이지로 이동합니다.</small></> : <><p>전체 보고서 분석은 로컬 파이프라인에서 진행되며, 수 시간이 걸리고 유료 모델 호출이 발생합니다.</p><Link to="/live">한 문장 실시간 체험하기 ↗</Link></>}</div>}
    </div><aside className="surface analyze-info"><p className="eyebrow">SAVED RUN</p><h2>NAVER 2025 통합보고서</h2><p>저장된 R72 → R85 실행을 다시 보여줍니다. AI 위임 검토 27건은 프로젝트 소유자가 2026-09-29 확인했습니다.</p><div><span>처리 범위</span><strong>선택 페이지 54 / 244쪽</strong></div><div><span>원자 주장</span><strong>{data.coverage.claims_discovered}건</strong></div><div><span>규칙 판정</span><strong>{data.coverage.claims_decided}건</strong></div><p className="analyze-note">일치하는 PDF만 저장된 결과에 연결됩니다. 새로운 PDF는 자동으로 모델에 보내지 않습니다.</p></aside></section>
  </main>;
}

function Landing({ data }: { data: Snapshot }) {
  return <main className="static-main">
    <section className="hero"><div className="hero-copy"><p className="eyebrow"><span className="live-dot" /> ESG EVIDENCE REVIEW</p>
      <h1>공시의 모든 문장에<br /><em>근거의 경로</em>를 만듭니다.</h1>
      <p className="hero-lead">지속가능성 보고서의 주장을 원문과 연결하고, 검토가 필요한 지점을 먼저 보여주는 입증 검토 도구입니다.</p>
      <div className="hero-actions"><Link className="primary-link" to="/demo">NAVER 실제 결과 살펴보기 <span>↗</span></Link><Link to="/live">실시간 체험 ↗</Link><a href="#how">작동 방식 ↓</a></div>
      <p className="hero-footnote">부분 실행(선택 페이지 54/244쪽) · {confirmationText}</p>
    </div><div className="hero-visual" aria-label="NAVER 실행 결과 미리보기"><div className="mock-top"><span className="mock-dots">● ● ●</span><span>PROOFOPS / REVIEW</span><span>↗</span></div><div className="mock-body"><div className="mock-label">SAVED CASE <span>01 / NAVER</span></div><h2>주장에서 근거까지,<br />한 화면에서.</h2><div className="mock-claim"><span className="tiny-label">공시 원문 · p.84</span><p>“Operation(환경운영부서)과 Internal Carbon Pricing TF(내부탄소가격제 조직) 운영”</p></div><div className="mock-result"><span className="tiny-label">규칙엔진 판정 · 저장된 실행 결과</span><strong>E3 <span>SUBSTANTIATED</span> <GuideHelp topic="grade" /><GuideHelp topic="label" /></strong><span className="mock-proof">✓ 원문 위치 확인 &nbsp; ✓ 요소 근거 연결</span></div><div className="mock-bottom">추출 → 검증 → 태깅 → 규칙 판정 <span>↗</span></div></div></div></section>
    <section className="intro-grid"><div><p className="eyebrow">THE PROBLEM</p><h2>공시는 길고,<br />검토 시간은 짧습니다.</h2><p>한 문장에 여러 주장이 섞이고, 숫자와 설명은 보고서 곳곳에 흩어집니다. 근거를 찾는 과정이 보이지 않으면 검토도 반복됩니다.</p></div><div><p className="eyebrow">OUR APPROACH</p><h2>문장과 근거를<br />함께 기록합니다.</h2><p>주장을 나누고 원문 위치를 확인한 다음, 요소별 근거와 미해결 상태를 남깁니다. 검토자는 판정의 입력부터 확인할 수 있습니다.</p></div></section>
    <section className="pipeline-section" id="how"><div className="section-top"><p className="eyebrow">HOW IT WORKS</p><h2>읽기부터 보고서까지, 7단계</h2><p>모델은 추출과 태깅을 돕고, 등급과 라벨은 고정된 Python 규칙엔진이 계산합니다.</p></div><ol className="pipeline">{pipeline.map((stage, index) => <li key={stage}><span>{String(index + 1).padStart(2, "0")}</span><strong>{stage}</strong></li>)}</ol></section>
    <section className="principles"><div className="section-top"><p className="eyebrow">DESIGN PRINCIPLES</p><h2>판정의 이유를 남기는 세 가지 원칙</h2></div><div className="principle-grid"><article><span>01</span><h3>등급은 규칙엔진이</h3><p>LLM은 주장과 근거를 읽고 태깅합니다. 등급·라벨은 기록된 규칙팩으로 재현합니다.</p></article><article><span>02</span><h3>모름은 부재가 아닙니다</h3><p>unknown, conflict, 판독 불가는 그대로 드러냅니다. 미확인을 E0로 계산하지 않습니다.</p></article><article><span>03</span><h3>원문까지 추적합니다</h3><p>근거 문구와 물리 페이지를 연결합니다. 검증된 원문 없이 present를 인정하지 않습니다.</p></article></div></section>
    <section className="landing-cta"><div><p className="eyebrow">REAL CASE / NAVER 2025</p><h2>실제 331개 주장 중<br />어디까지 검토됐을까요?</h2><p>처리 흐름과 판정·보류를 구분해 확인해 보세요.</p></div><div><div className="cta-number">{data.coverage.claims_decided}<span> / {data.coverage.claims_discovered}</span></div><p>규칙 판정 기록 / 추출 주장</p><Link className="primary-link light" to="/demo">결과 직접 살펴보기 ↗</Link></div></section>
  </main>;
}

function gradeText(claim: Claim) {
  if (claim.decision.grade) return claim.decision.grade;
  const range = claim.decision.grade_range;
  if (range) return `${range.floor}–${range.ceiling} 가능`;
  return "미판정";
}

const ladderElements: Record<string, Record<string, string[]>> = {
  management: { E1: ["M1"], E2: ["M1", "M2"], E3: ["M1", "M2", "M3"] },
  performance: { E1: ["P1"], E2: ["P1", "P2", "P3"], E3: ["P1", "P2", "P3", "P4"] },
  goal: { E1: ["G1", "G2"], E2: ["G1", "G2", "G3", "G4"], E3: ["G1", "G2", "G3", "G4", "G5", "G6"] },
};

function gradeWhy(claim: Claim) {
  const decision = claim.decision;
  const ladder = ladderElements[claim.track || ""];
  const required = decision.grade && ladder?.[decision.grade];
  const confirmed = (ladder ? claim.elements.filter(element => (required || ladder.E3).includes(element.id)) : claim.elements.slice(0, 3))
    .filter(element => element.state === "present" && element.evidence.length > 0)
    .map(element => `${element.id} ${elementLabels[element.id] || "요소"}는 ${element.evidence.slice(0, 3).map(ref => `p.${ref.page ?? "?"} “${ref.quote.slice(0, 65)}”`).join(" · ")}에서 확인`);
  const evidence = confirmed.length ? `${confirmed.join(", ")}됐습니다. ` : "연결된 확인 근거가 아직 없습니다. ";
  if (decision.grade) {
    const next = decision.grade === "E1" ? "E2" : decision.grade === "E2" ? "E3" : null;
    const missing = next && ladder?.[next].filter(id => !claim.elements.some(element => element.id === id && element.state === "present" && element.evidence.length));
    return `${trackText[claim.track || ""] || "해당"} 주장입니다. ${evidence}저장된 규칙 판정은 ${decision.grade}${decision.label ? ` (${decision.label})` : ""}입니다. ${next ? `${next}로 올라가려면 ${missing?.length ? missing.map(id => `${id} ${elementLabels[id]}`).join("·") + " 근거가 더 필요합니다." : "추가 규칙 요건을 충족해야 합니다."}` : "현재 사다리의 최상위 등급입니다."}`;
  }
  if (decision.grade_range) return `${evidence}${decision.grade_range.open_elements.map(id => `${id} ${elementLabels[id] || "요소"}`).join("·")}의 상태가 미해결이어서 ${decision.grade_range.floor}~${decision.grade_range.ceiling} 가능 범위만 기록됐습니다. 확정 등급은 아닙니다.`;
  return `${evidence}${decision.status === "not_run" ? "이 주장에는 규칙 판정이 실행되지 않았으므로 등급과 라벨이 없습니다." : `${statusText[decision.status] || "미해결 상태"}로 확정 등급을 계산하지 않았습니다.`}`;
}

function Demo({ data }: { data: Snapshot }) {
  const { claimId } = useParams();
  const { hash } = useLocation();
  const [track, setTrack] = useState("all");
  const [grade, setGrade] = useState("all");
  const [status, setStatus] = useState("all");
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(25);
  const [decidedOnly, setDecidedOnly] = useState(false);
  const selected = data.claims.find(claim => claim.id === claimId) || null;
  useEffect(() => { if (hash === "#claims") document.getElementById("claims")?.scrollIntoView(); }, [hash, claimId]);
  const filtered = useMemo(() => data.claims.filter(claim => {
    if (decidedOnly && claim.decision.status !== "decided") return false;
    if (track !== "all" && (claim.track || "unknown") !== track) return false;
    if (grade === "E3" && claim.decision.grade !== "E3") return false;
    if (grade === "range" && !claim.decision.grade_range) return false;
    if (grade === "none" && (claim.decision.grade || claim.decision.grade_range)) return false;
    if (status !== "all" && claim.decision.status !== status) return false;
    return !search || `${claim.quote} ${claim.id} ${claim.page ?? ""}`.toLowerCase().includes(search.toLowerCase());
  }), [data.claims, decidedOnly, track, grade, status, search]);
  const counts = { decided: data.claims.filter(c => c.decision.grade).length, range: data.claims.filter(c => c.decision.grade_range).length, pending: data.claims.filter(c => !c.decision.grade && !c.decision.grade_range).length };
  return <main className="static-main demo-main"><div className="breadcrumb"><Link to="/">홈</Link><span>/</span> 실제 검토 결과</div>
    <section className="demo-heading"><div><p className="eyebrow">CASE STUDY · 2025</p><h1>NAVER 공시 검토 결과</h1><p>실제 보고서에서 추출한 주장과 원문 근거, 규칙 판정을 탐색할 수 있습니다.</p><div className="badges"><span className="badge amber">부분 실행(선택 페이지 54/244쪽)</span><span className="badge blue">{confirmationText}</span><span className="badge blue">저장된 실행 결과 재생</span></div></div><div className="heading-side"><span>RUN STATUS</span><strong>R85 검토 사용자 확인 완료 <i /></strong><small>실행 기록 {new Date(data.generated_at).toLocaleDateString("ko-KR", { timeZone: "Asia/Seoul" })}</small></div></section>
    <section className="metrics" aria-label="실행 요약"><div><span>추출 주장</span><strong>{data.coverage.claims_discovered}<small>건</small></strong><p>선택 페이지의 원자 주장</p></div><div><span>원문 검증</span><strong>{data.funnel[1].count}<small>건</small></strong><p>R72 단계 기록</p></div><div><span>판정 기록</span><strong>{counts.decided}<small>건</small></strong><p>Python 규칙엔진</p></div><div><span>판정 미완료</span><strong>{data.coverage.claims_needs_review}<small>건</small></strong><p>미판정과 보류 포함</p></div></section>
    <section className="overview-grid"><div className="surface funnel-card"><div className="card-heading"><div><p className="eyebrow">PROCESS FUNNEL</p><h2>처리 흐름</h2></div><span>R72 → R85</span></div><div className="funnel-list">{data.funnel.map((step, index) => <div className="funnel-row" key={step.label}><span className="step-name"><b>{String(index + 1).padStart(2, "0")}</b>{step.label}</span><div className="bar-track"><div style={{ width: `${Math.max(step.count / 331 * 100, 3)}%` }} /></div><strong>{step.count}</strong></div>)}</div><p className="caption">{data.funnel_source}</p></div>
      <div className="surface grade-card"><p className="eyebrow">DECISION DISTRIBUTION</p><h2>등급과 보류 <GuideHelp topic="grade" /><GuideHelp topic="range" /></h2><div className="grade-bars"><div><span><b>E3</b> 규칙 판정</span><strong>{counts.decided}</strong></div><div className="grade-line e3"><i style={{ width: `${counts.decided / data.claims.length * 100}%` }} /></div><div><span><b>범위</b> 근거 보류</span><strong>{counts.range}</strong></div><div className="grade-line range"><i style={{ width: `${counts.range / data.claims.length * 100}%` }} /></div><div><span><b>미판정</b> 처리 전</span><strong>{counts.pending}</strong></div><div className="grade-line pending"><i style={{ width: `${counts.pending / data.claims.length * 100}%` }} /></div></div><p className="caption">막대는 전체 {data.claims.length}건 기준입니다. 판정된 {counts.decided}건의 등급은 모두 E3이며, 범위 {counts.range}건은 확정 등급이 아닙니다.</p></div></section>
    <section className="notice"><strong>검토 범위 안내</strong><p>244쪽 중 처리 54쪽, 미처리 187쪽, 판독 불가 3쪽입니다. 전체 보고서의 정확도나 공시 적합성을 뜻하지 않습니다. 독립 읽기 검토에서 E3 17건 중 15건 동의, 2건은 당시 추가 점검 대상으로 분류됐으며, 17건 모두 프로젝트 소유자가 2026-09-29 확인했습니다. <a href="https://www.navercorp.com/esg/esgReports" target="_blank" rel="noopener noreferrer">NAVER 공식 보고서 ↗</a></p></section>
    <section className="claims-section" id="claims"><div className="card-heading"><div><p className="eyebrow">EVIDENCE EXPLORER</p><h2>주장별 검토</h2><p>문장을 선택해 원문 페이지와 요소별 근거를 확인하세요.</p></div><span>{filtered.length} / {data.claims.length}건</span></div>
      <div className="filters"><label>검색<input value={search} onChange={event => { setSearch(event.target.value); setLimit(25); }} placeholder="문장, ID, 페이지 검색" /></label><label>트랙 <GuideHelp topic="track" /><select value={track} onChange={event => { setTrack(event.target.value); setLimit(25); }}><option value="all">전체 트랙</option><option value="management">관리체계</option><option value="goal">목표</option><option value="performance">성과</option><option value="unknown">분류 미합의</option></select></label><label>등급 <GuideHelp topic="grade" /><select value={grade} onChange={event => { setGrade(event.target.value); setLimit(25); }}><option value="all">전체 등급</option><option value="E3">E3 확정</option><option value="range">등급 범위</option><option value="none">미판정</option></select></label><label>상태 <GuideHelp topic="state" /><select value={status} onChange={event => { setStatus(event.target.value); setLimit(25); }}><option value="all">전체 상태</option><option value="decided">규칙 판정</option><option value="blocked_evidence">근거 보류</option><option value="not_run">미판정</option></select></label></div><div className="quick-filters"><button type="button" className={decidedOnly ? "active" : ""} aria-pressed={decidedOnly} onClick={() => { setDecidedOnly(!decidedOnly); setLimit(25); }}>판정된 {counts.decided}건</button><span title="목표·성과·관리체계 트랙의 태깅 합의가 아직 없어 규칙 판정을 실행하지 않은 주장입니다.">분류 미합의 ⓘ</span></div>
      <div className="claims-layout"><div className="claim-list" aria-label="주장 목록">{filtered.slice(0, limit).map(claim => <Link className={`claim-item ${selected?.id === claim.id ? "selected" : ""}`} to={`/demo/${claim.id}#claims`} key={claim.id}><div className="claim-item-top"><span>p.{claim.page ?? "?"} · {claim.track ? trackText[claim.track] : <span title="트랙 태깅 합의 전">분류 미합의 ⓘ</span>}</span><span className={`mini-status ${claim.decision.grade ? "good" : claim.decision.grade_range ? "warn" : "muted"}`}>{gradeText(claim)}</span></div><p>{claim.quote}</p><small>{statusText[claim.decision.status] || claim.decision.status}{claim.review.audit === "uncertain" ? " · 사용자 확인 완료" : ""}</small></Link>)}{filtered.length === 0 ? <p className="empty">조건에 맞는 주장이 없습니다.</p> : null}{filtered.length > limit ? <button className="more-button" onClick={() => setLimit(limit + 25)}>더 보기 ({filtered.length - limit}건 남음)</button> : null}</div><ClaimDetail claim={selected} /></div>
    </section>
    <DecisionGuide />
    <section className="method-note"><h2>실행 기록</h2><div><p><strong>규칙팩</strong> {data.run.rule_pack_name} ({data.run.rule_pack_id.slice(0, 8)}…) · <code>{data.run.rule_pack_hash.slice(0, 16)}…</code></p><p><strong>모델</strong> {data.run.model_note}</p><p><strong>R72 비용·시간</strong> 유료 호출 {data.run.r72_paid_calls.toLocaleString()}회 / ${data.run.r72_cost_usd.toFixed(6)} · 파싱·추출 {Math.round(data.run.r72_elapsed_seconds.parse_extraction / 60).toLocaleString()}분, 태깅 {Math.round(data.run.r72_elapsed_seconds.tagging / 60)}분, 로컬 후처리 {Math.round(data.run.r72_elapsed_seconds.local_postprocess / 60)}분</p><p><strong>R85 검토</strong> {Math.round(data.run.r85_review_seconds)}초 · 신규 모델 호출 {data.run.r85_model_calls}건</p></div></section>
  </main>;
}

function ClaimDetail({ claim }: { claim: Claim | null }) {
  if (!claim) return <aside className="claim-detail"><div className="detail-empty"><span>↖</span><h3>주장을 선택하세요</h3><p>왼쪽 목록에서 문장을 선택하면 근거와 판정 경로를 볼 수 있습니다.</p></div></aside>;
  const d = claim.decision;
  return <aside className="claim-detail"><div className="detail-top"><div><p className="eyebrow">CLAIM DETAIL · p.{claim.page ?? "?"}</p><h3>주장과 판정 근거</h3></div><Link to="/demo#claims" aria-label="상세 닫기">×</Link></div><div className="source-quote"><span>보고서 원문 · p.{claim.page ?? "?"}</span><blockquote>“{claim.quote}”</blockquote><small>{claim.source_verified ? "원문 인용 검증 기록 있음" : "원문 검증 기록 없음"}</small></div>
    <div className="why-panel"><h4>왜 이 등급인가 <GuideHelp topic="grade" /></h4><p>{gradeWhy(claim)}</p></div>
    <div className="decision-panel"><span>저장된 규칙엔진 결과 · {claim.review.status === "user_confirmed" ? confirmationText : "처리 단계 대기"}</span><strong>{gradeText(claim)} <GuideHelp topic={d.grade_range ? "range" : "grade"} /></strong><p>{d.label || statusText[d.status] || d.status} <GuideHelp topic="label" /></p>{claim.review.audit === "uncertain" ? <div className="audit-alert">독립 읽기 검토에서 당시 추가 점검 대상으로 분류 · 사용자 확인 완료 (2026-09-29)</div> : null}</div>
    <div className="detail-block"><h4>요소별 근거 <GuideHelp topic="state" /></h4>{claim.elements.length ? <div className="element-table-wrap"><table className="element-table"><thead><tr><th>요소</th><th>상태</th><th>원문 근거</th></tr></thead><tbody>{claim.elements.map(element => <tr key={element.id}><th scope="row"><b>{element.id}</b><span>{elementLabels[element.id] || element.id}</span></th><td><span className={`element-state ${element.state}`}>{stateText[element.state] || element.state}</span></td><td>{element.evidence.length ? element.evidence.map((ref, index) => <p key={index}><small>p.{ref.page ?? "?"}</small> “{ref.quote}”</p>) : <span className="no-evidence">연결된 원문 근거 없음</span>}</td></tr>)}</tbody></table></div> : <p className="caption">요소 태깅 전입니다. 빈 요소를 absent로 보지 않습니다.</p>}</div>
    <div className="provenance"><span className="badge blue">{claim.review.status === "user_confirmed" ? confirmationText : "AI 위임 검토 범위 밖 · 처리 단계 대기"}</span><p>태깅 revision {claim.review.tag_revision} · 판정 revision {claim.review.decision_revision}</p><small>주장 ID {claim.id.slice(0, 8)}…</small></div>
  </aside>;
}
