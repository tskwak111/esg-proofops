import { useEffect, useRef, useState } from "react";
import { ApiError, requestJson, type Session } from "../session/api";

type Track = "goal" | "performance" | "management";
export type SourceRef = {
  source_id: string; document_version_id: string; parse_manifest_id: string;
  page_num: number; printed_page_label: string | null; bbox: number[] | null;
  raw_text_sha256: string; quote: string; char_start: number; char_end: number;
  location_quality: "located" | "unlocated" | "unreadable";
  verification_state: "candidate" | "verified" | "rejected";
};
export type ReviewElement = {
  element_id: string; state: "present" | "absent" | "unknown" | "conflict" | "not_applicable";
  evidence_refs: SourceRef[]; normalized_value: string | null;
  credited_from: string | null; reason_code: string | null;
};
export type Review = {
  review_id: string; run_id: string; claim_id: string; status: "open" | "resolved" | "superseded";
  revision: number; base_tag_revision: number; reason_codes: string[];
};
export type ReviewSnapshot = { review: Review; track: Track; elements: ReviewElement[] };
export type ReviewResolution = {
  review: Review; new_tag_revision: number;
  decision: { decision_status: string; evidence_grade: string | null; label: string | null; gap_ids: string[] };
};
type Props = ReviewSnapshot & {
  session: Session;
  sourceChoices?: SourceRef[];
  loadLatest: () => Promise<ReviewSnapshot>;
  onResolved: (result: ReviewResolution) => void;
  onSourceOpen?: (source: SourceRef) => void;
  localSynthetic?: boolean;
};
const trackElements: Record<Track, string[]> = {
  goal: Array.from({ length: 8 }, (_, i) => `G${i + 1}`),
  performance: Array.from({ length: 6 }, (_, i) => `P${i + 1}`),
  management: Array.from({ length: 6 }, (_, i) => `M${i + 1}`),
};
const states: ReviewElement["state"][] = ["present", "absent", "unknown", "conflict", "not_applicable"];
const sourceKey = (source: SourceRef) => `${source.source_id}:${source.char_start}:${source.char_end}`;

export function ReviewWorkspace(props: Props) {
  // Tenant/session changes discard sensitive drafts and pending source choices.
  return <Editor key={`${props.session.tenant_id}:${props.session.user_id}:${props.review.review_id}`} {...props} />;
}

function Editor(props: Props) {
  const [base, setBase] = useState<ReviewSnapshot>(() => structuredClone({ review: props.review, track: props.track, elements: props.elements }));
  const [track, setTrack] = useState(props.track);
  const [elements, setElements] = useState(() => structuredClone(props.elements));
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [latest, setLatest] = useState<ReviewSnapshot | null>(null);
  const [stale, setStale] = useState(false);
  const [saved, setSaved] = useState<ReviewResolution | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const confirmButton = useRef<HTMLButtonElement>(null);
  const live = useRef(true);
  const key = useRef<{ payload: string; value: string } | null>(null);
  const dirty = !saved && (reason !== "" || track !== base.track || JSON.stringify(elements) !== JSON.stringify(base.elements));
  const editable = ["reviewer", "admin"].includes(props.session.role ?? "") && base.review.status === "open" && !saved;
  const sources = [...new Map([...props.elements.flatMap(e => e.evidence_refs), ...(props.sourceChoices ?? [])].map(s => [sourceKey(s), s])).values()];
  const changed = elements.filter(e => JSON.stringify(e) !== JSON.stringify(base.elements.find(old => old.element_id === e.element_id)));

  useEffect(() => {
    live.current = true;
    return () => { live.current = false; };
  }, []);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  function update(index: number, patch: Partial<ReviewElement>) {
    setElements(current => current.map((element, i) => i === index ? { ...element, ...patch } : element));
  }
  async function refresh() {
    try {
      const value = await props.loadLatest();
      if (live.current) setLatest(value);
    } catch { if (live.current) setError("최신 태깅을 불러오지 못했습니다. 초안은 보존되었습니다."); }
  }
  async function save() {
    dialog.current?.close();
    setBusy(true); setError("");
    const payload = JSON.stringify({ base_tag_revision: base.review.base_tag_revision, track, elements, reason });
    if (key.current?.payload !== payload) key.current = { payload, value: crypto.randomUUID() };
    try {
      const result = await requestJson<ReviewResolution>(`/v1/reviews/${base.review.review_id}/resolve`, {
        method: "POST", headers: { "Content-Type": "application/json", "X-CSRF-Token": props.session.csrf_token,
          "If-Match": `"${base.review.revision}"`, "Idempotency-Key": key.current!.value }, body: payload,
      });
      if (!live.current) return;
      setSaved(result); props.onResolved(result);
    } catch (failure) {
      if (!live.current) return;
      if (failure instanceof ApiError && failure.status === 412) {
        setStale(true);
        setError("다른 검토자가 먼저 변경했습니다. 초안을 유지한 채 최신 태깅과 비교해 주세요.");
        await refresh();
      } else {
        setError(failure instanceof ApiError && failure.status === 422
          ? "원문 근거·검색 범위·요소 입력을 확인해 주세요. 서버는 근거 없는 확정을 허용하지 않습니다."
          : "저장하지 못했습니다. 권한과 세션을 확인하고 다시 시도해 주세요.");
      }
    } finally { if (live.current) setBusy(false); }
  }

  return <section aria-label="인간 태깅 검토" aria-busy={busy}>
    <h2>태깅 검토</h2>
    {props.localSynthetic && <p>로컬 합성 자료 검증 — 실제 모델 결과가 아닙니다.</p>}
    <p>원문 근거와 태깅을 수정하면 규칙엔진이 새 판정을 계산합니다.</p>
    {base.review.reason_codes.length > 0 && <p>검토 사유: {base.review.reason_codes.join(", ")}</p>}
    {!editable && !saved && <p>검토자 권한과 열린 검토 항목이 필요합니다.</p>}
    {error && <p role="alert">{error}</p>}
    {saved && <p role="status">태깅 revision {saved.new_tag_revision} 저장됨. 판정: {saved.decision.decision_status}
      {saved.decision.gap_ids.length > 0 && ` · 미정 규칙: ${saved.decision.gap_ids.join(", ")}`}</p>}
    {stale && <section aria-label="충돌 비교">
      <h3>서버 최신 태깅과 내 초안</h3>
      <button type="button" onClick={refresh}>최신 태깅 다시 조회</button>
      {latest && <>
        <p>서버 revision {latest.review.revision} · {latest.review.status} · 트랙 {latest.track}</p>
        <table><thead><tr><th>요소</th><th>서버</th><th>내 초안</th></tr></thead><tbody>
          {elements.map(e => <tr key={e.element_id}><th>{e.element_id}</th>
            <td>{latest.elements.find(old => old.element_id === e.element_id)?.state ?? "미수집"}</td><td>{e.state}</td></tr>)}
        </tbody></table>
        <details><summary>근거와 값 전체 비교</summary><pre>{JSON.stringify({ server: latest.elements, draft: elements }, null, 2)}</pre></details>
        <button type="button" disabled={latest.review.status !== "open"} onClick={() => {
          setBase(structuredClone(latest)); setStale(false); setError(""); key.current = null;
        }}>차이를 확인했습니다. 내 초안을 새 기준에서 다시 검토</button>
      </>}
    </section>}
    <form onSubmit={event => { event.preventDefault(); dialog.current?.showModal(); }}>
      <fieldset disabled={!editable || busy || stale}>
        <legend>원문 태깅 수정</legend>
        <label>트랙 <select value={track} onChange={event => {
          const next = event.target.value as Track;
          setTrack(next);
          setElements(trackElements[next].map(element_id => ({ element_id, state: "unknown", evidence_refs: [],
            normalized_value: null, credited_from: null, reason_code: null })));
        }}><option value="goal">목표형</option><option value="performance">성과형</option><option value="management">관리체계형</option></select></label>
        {elements.map((element, index) => <fieldset key={element.element_id}>
          <legend>{element.element_id}</legend>
          <label>상태 <select value={element.state} onChange={event => update(index, { state: event.target.value as ReviewElement["state"] })}>
            {states.map(state => <option key={state}>{state}</option>)}
          </select></label>
          <label>원문 값 <input value={element.normalized_value ?? ""} onChange={event => update(index, { normalized_value: event.target.value || null })} /></label>
          <fieldset><legend>근거 선택</legend>
            {sources.length === 0 && <p>선택 가능한 원문 근거가 없습니다.</p>}
            {sources.map(source => <div key={sourceKey(source)}>
              <label><input type="checkbox" checked={element.evidence_refs.some(ref => sourceKey(ref) === sourceKey(source))} onChange={event => update(index, {
                evidence_refs: event.target.checked ? [...element.evidence_refs, source] : element.evidence_refs.filter(ref => sourceKey(ref) !== sourceKey(source)),
                credited_from: null,
              })} />{source.page_num}쪽: {source.quote}</label>
              {props.onSourceOpen && <button type="button" onClick={() => props.onSourceOpen?.(source)}>원문 위치 열기</button>}
            </div>)}
          </fieldset>
        </fieldset>)}
        <label>변경 사유 <textarea required minLength={5} maxLength={1000} value={reason} onChange={event => setReason(event.target.value)} /></label>
        <button ref={confirmButton} type="submit" disabled={reason.trim().length < 5 || elements.some(e => e.state === "present" && e.evidence_refs.length === 0)}>변경 확인</button>
      </fieldset>
    </form>
    <dialog ref={dialog} aria-labelledby="review-confirm-title" onClose={() => confirmButton.current?.focus()}>
      <h3 id="review-confirm-title">태깅 변경 후 재채점</h3>
      <p>트랙: {base.track} → {track}</p>
      <ul>{changed.map(e => <li key={e.element_id}>{e.element_id}: {base.elements.find(old => old.element_id === e.element_id)?.state ?? "미수집"} → {e.state} · 근거 {e.evidence_refs.length}개</li>)}</ul>
      <p>{reason}</p><p>기존 revision은 보존되며, 미정 규칙은 확정 뒤에도 남을 수 있습니다.</p>
      <button type="button" onClick={() => dialog.current?.close()}>취소</button>
      <button type="button" onClick={save}>태깅 확정 및 재채점</button>
    </dialog>
  </section>;
}
