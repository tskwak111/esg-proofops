import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { StatusBadge } from "../../components/StatusBadge";
import { ApiError, errorMessage, isSessionError, requestJson } from "../session/api";
import type { Track } from "../shared/wireTypes";
import type { ClaimPage, ClaimSummary, ClaimWorkspaceProps, Decision, LoadState } from "./claimTypes";

const pendingDecisionText: Record<Exclude<Decision["decision_status"], "decided">, string> = {
  blocked_evidence: "미판정 · 입증 요소 확인 필요",
  blocked_rule_gap: "미판정 · 규칙 적용 결과가 갈리거나 규칙집에 정한 기준이 없음",
  not_applicable: "적용 제외",
  not_run: "아직 판정하지 않음",
};

export const trackText: Record<Track, string> = {
  goal: "목표형",
  performance: "성과형",
  management: "관리체계형",
};

export function decisionText(decision: Decision | null): string {
  if (!decision) return "판정 미확정 · 상세 확인";
  if (decision.decision_status !== "decided") {
    const range = decision.grade_range;
    const pending = pendingDecisionText[decision.decision_status];
    return range ? `${pending} · 가능 범위 ${range.floor}~${range.ceiling}` : pending;
  }
  return `${decision.evidence_grade} · ${decision.label}${decision.sublabel ? ` (${decision.sublabel})` : ""}`;
}

export function decisionTone(decision: Decision | null): "neutral" | "success" | "warning" | "danger" {
  if (!decision) return "warning";
  if (decision.decision_status === "not_applicable") return "neutral";
  if (decision.decision_status !== "decided") return "warning";
  if (decision.evidence_grade === "E3") return "success";
  return decision.evidence_grade === "E0" ? "danger" : "warning";
}

export function ClaimList({ apiBase = "", tenantKey, runId, onSessionInvalid }: ClaimWorkspaceProps) {
  const [search, setSearch] = useSearchParams();
  const [items, setItems] = useState<ClaimSummary[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [message, setMessage] = useState("");
  const [moreBusy, setMoreBusy] = useState(false);
  const controller = useRef<AbortController | null>(null);
  const filterKey = ["track", "grade", "review_status"].map(key => search.get(key) ?? "").join(":");

  const load = useCallback(async (nextCursor?: string) => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    if (nextCursor) setMoreBusy(true); else setState("loading");
    setMessage("");
    const target = new URL(`${apiBase}/v1/runs/${runId}/claims`, window.location.origin);
    target.searchParams.set("limit", "50");
    for (const key of ["track", "grade", "review_status"]) {
      const value = search.get(key);
      if (value) target.searchParams.set(key, value);
    }
    if (nextCursor) target.searchParams.set("cursor", nextCursor);
    try {
      const page = await requestJson<ClaimPage>(target.toString(), { signal: request.signal });
      if (request.signal.aborted) return;
      setItems(current => nextCursor ? [...current, ...page.items] : page.items);
      setCursor(page.next_cursor);
      setState("ready");
    } catch (reason: unknown) {
      if (request.signal.aborted) return;
      if (isSessionError(reason)) return onSessionInvalid();
      setState((reason instanceof ApiError && reason.status === 409) ? "pending" : "error");
      setMessage((reason instanceof ApiError && reason.status === 409)
        ? "주장 태깅과 무결성 검사가 아직 완료되지 않았습니다. 잠시 후 다시 확인해 주세요."
        : errorMessage(reason, "주장 목록을 불러오지 못했습니다."));
    } finally {
      if (!request.signal.aborted) setMoreBusy(false);
    }
  }, [apiBase, filterKey, onSessionInvalid, runId, search]);

  useEffect(() => {
    setItems([]);
    setCursor(null);
    void load();
    return () => controller.current?.abort();
  }, [load, tenantKey]);

  function setFilter(key: string, value: string) {
    const next = new URLSearchParams(search);
    if (value) next.set(key, value); else next.delete(key);
    next.delete("cursor");
    setSearch(next);
  }

  return <section aria-labelledby="claims-heading">
    <h1 id="claims-heading">주장 검토 목록</h1>
    <div aria-label="주장 필터" style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
      <label>트랙 <select value={search.get("track") ?? ""} onChange={event => setFilter("track", event.target.value)}>
        <option value="">전체</option><option value="goal">목표형</option><option value="performance">성과형</option><option value="management">관리체계형</option>
      </select></label>
      <label>등급 <select value={search.get("grade") ?? ""} onChange={event => setFilter("grade", event.target.value)}>
        <option value="">전체</option>{["E0", "E1", "E2", "E3"].map(grade => <option key={grade}>{grade}</option>)}
      </select></label>
      <label>검토 상태 <select value={search.get("review_status") ?? ""} onChange={event => setFilter("review_status", event.target.value)}>
        <option value="">전체</option><option value="auto_confirmed">자동 확인</option><option value="needs_review">검토 필요</option><option value="human_confirmed">사람 확인</option><option value="ai_delegated_confirmed">AI 검토(위임·사람 아님)</option>
      </select></label>
    </div>
    {state === "loading" ? <p role="status">주장 목록을 불러오는 중입니다.</p> : null}
    {state === "pending" ? <p role="status">{message}</p> : null}
    {state === "error" ? <p role="alert">{message} <button type="button" onClick={() => void load()}>다시 시도</button></p> : null}
    {state === "ready" && items.length === 0 ? <p>현재 필터에 해당하는 주장이 없습니다. 필터를 해제하거나 분석 진행 상태를 확인해 주세요.</p> : null}
    {items.length > 0 ? <table style={{ width: "100%" }}><thead><tr><th>쪽</th><th>주장</th><th>트랙</th><th>판정</th></tr></thead><tbody>
      {items.map(item => <tr key={item.claim_id}><td>{item.page_num}</td><td><Link to={`/runs/${runId}/claims/${item.claim_id}`}>{item.quote}</Link></td><td>{item.track ? trackText[item.track] : "미분류"}</td><td><StatusBadge label={decisionText(item.decision)} tone={decisionTone(item.decision)} /></td></tr>)}
    </tbody></table> : null}
    {cursor ? <button type="button" disabled={moreBusy} onClick={() => void load(cursor)} style={{ minHeight: 44 }}>{moreBusy ? "불러오는 중…" : "더 보기"}</button> : null}
  </section>;
}
