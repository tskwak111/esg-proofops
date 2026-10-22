import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { SourceViewer, type SourceOpenRequest } from "../../components/SourceViewer";
import { ApiError, errorMessage, isSessionError, requestJson } from "../session/api";
import { ReviewWorkspace, type Review, type ReviewResolution, type ReviewSnapshot } from "../reviews/ReviewWorkspace";
import { completeElements } from "../shared/reviewElements";
import type { ClaimDetail, ClaimSummary, CommonProps, LoadState } from "./claimTypes";

const MAX_SNAPSHOT_PAGES = 20;

async function allPages<T>(url: string, signal: AbortSignal): Promise<T[]> {
  const items: T[] = [];
  let cursor: string | null = null;
  for (let page = 0; page < MAX_SNAPSHOT_PAGES; page += 1) {
    const target = new URL(url, window.location.origin);
    target.searchParams.set("limit", "100");
    if (cursor) target.searchParams.set("cursor", cursor);
    const result = await requestJson<{ items: T[]; next_cursor: string | null }>(target.toString(), { signal });
    items.push(...result.items);
    cursor = result.next_cursor;
    if (!cursor) return items;
  }
  throw new Error("목록이 브라우저 검토 한도를 초과했습니다. 필터로 범위를 줄여 주세요.");
}

const reviewQueueStatusText: Record<Review["status"], string> = {
  open: "검토 대기",
  resolved: "검토 완료",
  superseded: "대체됨",
};

export function ReviewQueueWorkspace({ apiBase = "", tenantKey, session, runId, onSessionInvalid, onDataChanged, localSynthetic = false }: CommonProps & { localSynthetic?: boolean }) {
  const [sourceOpen, setSourceOpen] = useState<SourceOpenRequest | null>(null);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [snapshot, setSnapshot] = useState<ReviewSnapshot | null>(null);
  const [detail, setDetail] = useState<ClaimDetail | null>(null);
  const [state, setState] = useState<LoadState>("loading");
  const [message, setMessage] = useState("");
  const controller = useRef<AbortController | null>(null);
  const allowed = session.role === "reviewer" || session.role === "admin";

  const latest = useCallback(async (reviewId: string, signal: AbortSignal): Promise<{ snapshot: ReviewSnapshot; detail: ClaimDetail }> => {
    const [freshReviews, freshClaims] = await Promise.all([
      allPages<Review>(`${apiBase}/v1/runs/${runId}/reviews`, signal),
      allPages<ClaimSummary>(`${apiBase}/v1/runs/${runId}/claims`, signal),
    ]);
    const review = freshReviews.find(item => item.review_id === reviewId);
    if (!review || !freshClaims.some(item => item.claim_id === review.claim_id)) throw new Error("최신 검토 항목을 찾을 수 없습니다.");
    const claimDetail = await requestJson<ClaimDetail>(`${apiBase}/v1/runs/${runId}/claims/${review.claim_id}`, { signal });
    if (!claimDetail.claim.track) throw new Error("트랙이 미확정되어 검토 편집기를 열 수 없습니다.");
    return { snapshot: { review, track: claimDetail.claim.track, elements: completeElements(claimDetail.claim.track, claimDetail.elements), headTagRevision: claimDetail.claim.decision?.tag_revision ?? review.base_tag_revision }, detail: claimDetail };
  }, [apiBase, runId]);

  const load = useCallback(async (preferred?: string) => {
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setState("loading"); setMessage(""); setSourceOpen(null);
    try {
      const [nextReviews, nextClaims] = await Promise.all([
        allPages<Review>(`${apiBase}/v1/runs/${runId}/reviews`, request.signal),
        allPages<ClaimSummary>(`${apiBase}/v1/runs/${runId}/claims`, request.signal),
      ]);
      if (request.signal.aborted) return;
      setReviews(nextReviews); setClaims(nextClaims);
      const id = preferred && nextReviews.some(item => item.review_id === preferred) ? preferred : nextReviews.find(item => item.status === "open")?.review_id ?? nextReviews[0]?.review_id ?? "";
      setSelected(id);
      if (!id) { setSnapshot(null); setDetail(null); setState("ready"); return; }
      const value = await latest(id, request.signal);
      if (request.signal.aborted) return;
      setSnapshot(value.snapshot); setDetail(value.detail); setState("ready");
    } catch (reason: unknown) {
      if (request.signal.aborted) return;
      if (isSessionError(reason)) return onSessionInvalid();
      setState((reason instanceof ApiError && reason.status === 409) ? "pending" : "error");
      setMessage((reason instanceof ApiError && reason.status === 409) ? "검토 큐와 태깅 스냅샷이 아직 준비되지 않았습니다." : errorMessage(reason, "검토 큐를 불러오지 못했습니다."));
    }
  }, [apiBase, latest, onSessionInvalid, runId]);

  useEffect(() => {
    if (allowed) void load(); else setState("ready");
    return () => controller.current?.abort();
  }, [allowed, load, tenantKey]);

  async function choose(reviewId: string) {
    setSelected(reviewId); setState("loading"); setMessage(""); setSourceOpen(null);
    const request = new AbortController();
    controller.current?.abort(); controller.current = request;
    try {
      const value = await latest(reviewId, request.signal);
      if (!request.signal.aborted) { setSnapshot(value.snapshot); setDetail(value.detail); setState("ready"); }
    } catch (reason: unknown) {
      if (request.signal.aborted) return;
      if (isSessionError(reason)) return onSessionInvalid();
      setState((reason instanceof ApiError && reason.status === 409) ? "pending" : "error"); setMessage(errorMessage(reason, "검토 항목을 불러오지 못했습니다."));
    }
  }

  function resolved(_result: ReviewResolution) {
    onDataChanged();
    void load(selected);
  }

  if (!allowed) return <section><h1>태깅 검토</h1><p role="alert">검토자 또는 관리자 권한이 필요합니다. 가짜 승인 화면은 제공하지 않습니다.</p></section>;
  // Claims that are undecided and not yet on the review queue (no Review row and
  // no decided Decision) are hidden by the queue alone. Surface them read-only so
  // a reviewer can open the existing claim detail for source and hold reason. The
  // set spans several blocked states (e.g. preliminary track unresolved, source
  // span unverified), so the copy stays neutral and does not assert a single cause.
  const reviewedClaimIds = new Set(reviews.map(review => review.claim_id));
  const unregistered = claims.filter(claim =>
    !reviewedClaimIds.has(claim.claim_id) &&
    (claim.decision === null || claim.decision.decision_status !== "decided"));
  return <section aria-labelledby="review-queue-heading"><h1 id="review-queue-heading">검토 큐</h1>
    {state === "loading" ? <p role="status">최신 주장과 검토 큐 스냅샷을 불러오는 중입니다.</p> : null}
    {state === "pending" ? <p role="status">{message}</p> : null}
    {state === "error" ? <p role="alert">{message} <button type="button" onClick={() => void load(selected)}>다시 시도</button></p> : null}
    {state === "ready" && reviews.length === 0 && unregistered.length === 0 ? <p>현재 검토 큐가 비어 있습니다.</p> : null}
    {reviews.length ? <nav aria-label="검토 항목"><ul>{reviews.map(review => <li key={review.review_id}><button type="button" aria-current={selected === review.review_id ? "true" : undefined} onClick={() => void choose(review.review_id)}>{claims.find(claim => claim.claim_id === review.claim_id)?.quote ?? review.claim_id} · {reviewQueueStatusText[review.status]}</button></li>)}</ul></nav> : null}
    {state === "ready" && unregistered.length ? <section aria-labelledby="unregistered-heading"><h2 id="unregistered-heading">검토 큐에 아직 오르지 않은 미판정 주장 ({unregistered.length}건)</h2>
      <p role="status">아직 검토 항목으로 등록되지 않은 미판정 주장입니다. 상세에서 원문과 처리 상태·보류 사유를 확인하세요. 아직 태깅 검토에서 편집할 수 없습니다.</p>
      <ul>{unregistered.map(claim => <li key={claim.claim_id}>{claim.page_num}쪽 · <Link to={`/runs/${runId}/claims/${claim.claim_id}`}>{claim.quote}</Link></li>)}</ul>
    </section> : null}
    {state === "ready" && snapshot && detail ? <ReviewWorkspace key={`${snapshot.review.review_id}:${snapshot.review.revision}`} {...snapshot} session={session}
      sourceChoices={detail.source_refs} loadLatest={async () => (await latest(snapshot.review.review_id, new AbortController().signal)).snapshot}
      onResolved={resolved} onSourceOpen={source => setSourceOpen(current => ({ source, nonce: (current?.nonce ?? 0) + 1 }))} localSynthetic={localSynthetic} /> : null}
    {state === "ready" && detail && snapshot ? <section aria-label="검토 원문">
      <SourceViewer key={`${tenantKey}:${runId}:${selected}`} apiBase={apiBase} csrfToken={session.csrf_token} runId={runId}
        sources={[...new Map([...detail.source_refs, ...snapshot.elements.flatMap(element => element.evidence_refs)]
          .map(source => [`${source.source_id}:${source.char_start}:${source.char_end}`, source])).values()]}
        openRequest={sourceOpen} onSessionInvalid={onSessionInvalid} />
      <Link to={`/runs/${runId}/claims/${detail.claim.claim_id}`}>원문 PDF와 전체 상세 열기</Link>
    </section> : null}
  </section>;
}
