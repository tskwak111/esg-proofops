import { useEffect, useRef, useState } from "react";
import { SourceViewer, type SourceOpenRequest } from "../../components/SourceViewer";
import type { SourceRef } from "../reviews/ReviewWorkspace";
import { ApiError, errorMessage, isSessionError, requestJson } from "../session/api";

type Issue = { issue_id: string; kind: string; page_num: number; source_ids: string[]; state: string; reason: string };
type Page = { items: Issue[]; next_cursor: string | null };
type Props = { apiBase?: string; runId: string; csrfToken: string; onSessionInvalid: () => void };
const reasons: Record<string, string> = {
  "Independent parser agreement; source and semantic approval remain separate.": "Docling과 Upstage의 행 값 및 위치가 일치합니다. 원문 검증과 의미 판단은 별도입니다.",
  "numeric_not_in_native_region": "이 영역의 PDF 원문에서 숫자를 확인하지 못해 제외했습니다.",
  "chart_requires_vision_review": "차트 수치는 이미지 대조와 사람 검토가 필요합니다.",
  "crosscheck_missing": "독립 파서의 일치하는 결과가 없어 확인이 필요합니다.",
  "table_grid_overlap": "표의 셀이 겹쳐 행·열 연결을 확인해야 합니다.",
  "parse_conflict": "두 파서의 행 값 또는 원문 위치가 일치하지 않습니다.",
  "Parser did not provide source geometry.": "파서가 원문 좌표를 제공하지 않았습니다. 원본 페이지에서 위치를 확인하세요.",
  "Vision cross-check not_run: approved runtime/account required.": "표의 이미지 대조 검증을 실행하지 않았습니다. 표 원문과 추출 내용을 확인하세요.",
  "No text extracted; absence of evidence is not established.": "텍스트를 추출하지 못했습니다. 근거가 없다는 뜻은 아니므로 원문을 확인하세요.",
};
const labels: Record<string, string> = {
  parser_consensus: "파서 합의",
  extraction_span_unprocessed: "주장 여부 미확정 구간",
  image_text_not_extracted: "이미지 영역 확인 필요", table_vision_not_run: "표 이미지 대조 미실행",
  no_extractable_text: "텍스트 추출 실패", parse_conflict: "파서 결과 불일치",
  source_geometry_invalid: "원문 좌표 확인 필요", source_geometry_missing: "원문 좌표 없음",
};

// Caller keys by tenant/run: previous tenant text and in-flight preview never carry over.
export function RunQuality({ apiBase = "", runId, csrfToken, onSessionInvalid }: Props) {
  const [items, setItems] = useState<Issue[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [state, setState] = useState("loading");
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [opening, setOpening] = useState(false);
  const [selection, setSelection] = useState<SourceOpenRequest | null>(null);
  const sourceRequest = useRef<AbortController | null>(null);
  const nonce = useRef(0);
  useEffect(() => () => sourceRequest.current?.abort(), []);
  useEffect(() => {
    const controller = new AbortController();
    setState("loading"); setError("");
    const query = new URLSearchParams({ limit: "20" });
    if (cursor) query.set("cursor", cursor);
    requestJson<Page>(`${apiBase}/v1/runs/${runId}/quality?${query}`, { signal: controller.signal }).then(page => {
      if (controller.signal.aborted) return;
      setItems(previous => cursor ? [...new Map([...previous, ...page.items].map(item => [item.issue_id, item])).values()] : page.items);
      setNext(page.next_cursor); setState("ready");
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      if (isSessionError(reason)) return onSessionInvalid();
      setState(reason instanceof ApiError && reason.status === 409 ? "pending" : "error");
      setError(errorMessage(reason, "원문 품질 정보를 불러오지 못했습니다."));
    });
    return () => controller.abort();
  }, [apiBase, cursor, onSessionInvalid, retry, runId]);

  async function openSource(sourceId: string) {
    sourceRequest.current?.abort();
    const controller = new AbortController(); sourceRequest.current = controller;
    setOpening(true); setError("");
    try {
      const source = await requestJson<SourceRef>(`${apiBase}/v1/runs/${runId}/sources/${sourceId}`, { signal: controller.signal });
      if (!controller.signal.aborted) setSelection({ source, nonce: ++nonce.current });
    } catch (reason) {
      if (controller.signal.aborted) return;
      if (isSessionError(reason)) return onSessionInvalid();
      setError(errorMessage(reason, "원문 위치를 열지 못했습니다."));
    } finally { if (!controller.signal.aborted) setOpening(false); }
  }
  return <section aria-labelledby="quality-heading">
    <h2 id="quality-heading">원문 읽기 확인</h2>
    <p>페이지 처리 수는 모든 글·표를 읽었다는 뜻이 아닙니다. 파서 합의와 원문 확인 필요 항목을 구분해서 표시합니다. 합의는 주장의 사실 여부를 확정하지 않습니다.</p>
    {state === "loading" ? <p role="status">원문 품질 정보를 불러오는 중입니다.</p> : null}
    {state === "pending" ? <p role="status">원문 품질 산출물이 준비되지 않았거나 무결성 확인이 필요합니다.</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {state === "error" || state === "pending" ? <button type="button" onClick={() => setRetry(value => value + 1)}>품질 정보 다시 확인</button> : null}
    {state === "ready" && items.length === 0 ? <p>현재 기록된 품질 이슈가 없습니다. 추출의 완전성이 검증된 것은 아닙니다.</p> : null}
    <ul>{items.map(item => <li key={item.issue_id}>
      <p><strong>{item.page_num}쪽 · {labels[item.kind] ?? "원문 품질 확인"}</strong> · {item.state === "resolved" ? "해결됨" : item.state === "unreadable" ? "판독 불가" : "확인 필요"}</p>
      <p>{reasons[item.reason] ?? item.reason}</p>
      {item.source_ids.map((id, index) => <button key={id} type="button" disabled={opening} onClick={() => void openSource(id)}>해당 원문 열기{item.source_ids.length > 1 ? ` ${index + 1}` : ""}</button>)}
    </li>)}</ul>
    {next && state === "ready" ? <button type="button" onClick={() => setCursor(next)}>품질 항목 더 보기</button> : null}
    <div hidden={!selection}><SourceViewer apiBase={apiBase} csrfToken={csrfToken} runId={runId} sources={[]} openRequest={selection} onSessionInvalid={onSessionInvalid} /></div>
  </section>;
}
