import { useEffect, useRef, useState } from "react";
import { ApiError, errorMessage, isSessionError, requestJson } from "../features/session/api";
import type { SourceRef } from "../features/reviews/ReviewWorkspace";
import { StatusBadge } from "./StatusBadge";

type Download = { url: string; expires_at: string; sha256: string };
type Preview = {
  source: SourceRef;
  blobUrl: string;
  originalUrl: string;
  width: number | null;
  height: number | null;
  highlightAllowed: boolean;
};
type Props = {
  apiBase?: string;
  csrfToken: string;
  runId: string;
  sources: SourceRef[];
  onSessionInvalid: () => void;
};

function absoluteDownload(apiBase: string, value: string): string {
  const base = apiBase ? new URL(apiBase, window.location.origin).origin : window.location.origin;
  return new URL(value, base).toString();
}

function previewUrl(apiBase: string, download: Download): string {
  const target = new URL(absoluteDownload(apiBase, download.url));
  target.hash = "";
  target.searchParams.set("preview", "page");
  return target.toString();
}

function numberHeader(response: Response, name: string): number | null {
  const value = Number(response.headers.get(name));
  return Number.isFinite(value) && value > 0 ? value : null;
}

function locationLabel(source: SourceRef): string {
  if (source.location_quality === "unlocated") return "위치 없음";
  if (source.location_quality === "unreadable") return "판독 불가";
  return source.verification_state === "verified" ? "검증된 위치" : "위치 후보";
}

export function SourceViewer({ apiBase = "", csrfToken, runId, sources, onSessionInvalid }: Props) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const request = useRef<AbortController | null>(null);

  useEffect(() => () => {
    request.current?.abort();
    if (preview) URL.revokeObjectURL(preview.blobUrl);
  }, [preview]);

  async function issue(source: SourceRef, signal: AbortSignal): Promise<Download> {
    return requestJson<Download>(`${apiBase}/v1/runs/${runId}/sources/${source.source_id}/view`, {
      method: "POST", signal, headers: { "X-CSRF-Token": csrfToken },
    });
  }

  async function openSource(source: SourceRef) {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setMessage("");
    try {
      let download = await issue(source, controller.signal);
      let response = await fetch(previewUrl(apiBase, download), { credentials: "include", signal: controller.signal });
      if (response.status === 403) {
        download = await issue(source, controller.signal);
        response = await fetch(previewUrl(apiBase, download), { credentials: "include", signal: controller.signal });
      }
      if (!response.ok) throw new ApiError(response.status, `HTTP_${response.status}`, "원문 미리보기를 불러오지 못했습니다.");
      const blob = await response.blob();
      if (controller.signal.aborted) return;
      const next = { source, blobUrl: URL.createObjectURL(blob), originalUrl: absoluteDownload(apiBase, download.url),
        width: numberHeader(response, "X-Page-Width-Pt"), height: numberHeader(response, "X-Page-Height-Pt"),
        highlightAllowed: response.headers.get("X-Source-Highlight") === "allowed" };
      setPreview(current => { if (current) URL.revokeObjectURL(current.blobUrl); return next; });
    } catch (reason: unknown) {
      if (controller.signal.aborted) return;
      if (isSessionError(reason)) return onSessionInvalid();
      setMessage(errorMessage(reason, "원문 위치를 열지 못했습니다. 새 권한 URL을 다시 요청해 주세요."));
    } finally {
      if (!controller.signal.aborted) setBusy(false);
    }
  }

  const bbox = preview?.source.bbox;
  const canHighlight = Boolean(preview?.highlightAllowed && preview.width && preview.height && bbox &&
    preview.source.location_quality === "located" && preview.source.verification_state === "verified" &&
    bbox[0] >= 0 && bbox[1] >= 0 && bbox[2] > bbox[0] && bbox[3] > bbox[1] &&
    bbox[2] <= preview.width! && bbox[3] <= preview.height!);

  return <section aria-labelledby="source-heading"><h2 id="source-heading">원문</h2>
    {sources.length === 0 ? <p>연결된 원문 근거가 없습니다. 하이라이트를 표시하지 않습니다.</p> : sources.map(source => <article key={`${source.source_id}:${source.char_start}`}>
      <p>{source.page_num}쪽 · <StatusBadge label={`연결 상태: ${locationLabel(source)}`} tone={source.location_quality === "located" && source.verification_state === "verified" ? "success" : "warning"} /></p>
      <blockquote>{source.quote}</blockquote>
      <button type="button" disabled={busy} onClick={() => void openSource(source)}>원문 위치 열기</button>
    </article>)}
    {message ? <p role="alert">{message}</p> : null}
    {preview ? <section aria-label="선택한 원문 위치">
      <p>PDF {preview.source.page_num}쪽 미리보기</p>
      <div style={{ position: "relative", width: "100%" }}>
        <img src={preview.blobUrl} alt={`원문 PDF ${preview.source.page_num}쪽`} style={{ display: "block", width: "100%", height: "auto" }} />
        {canHighlight ? <span data-source-highlight="true" aria-label="검증된 근거 위치" style={{ position: "absolute", border: "3px solid #b42318", pointerEvents: "none",
          left: `${bbox![0] / preview.width! * 100}%`, top: `${bbox![1] / preview.height! * 100}%`,
          width: `${(bbox![2] - bbox![0]) / preview.width! * 100}%`, height: `${(bbox![3] - bbox![1]) / preview.height! * 100}%` }} /> : null}
      </div>
      {!canHighlight ? <p>{preview?.source.verification_state === "verified"
        ? "인용 문구는 검증되었지만, 이 페이지 미리보기의 좌표 앵커는 확인되지 않아 하이라이트를 표시하지 않습니다. 아래 인용문과 원본 PDF로 위치를 확인해 주세요."
        : "검증된 좌표가 없어 하이라이트하지 않습니다."}</p> : null}
      <p><a href={preview.originalUrl} target="_blank" rel="noopener noreferrer">원본 PDF 새 탭에서 열기</a></p>
      <details><summary>접근 가능한 원문 텍스트</summary><p>{preview.source.quote}</p></details>
    </section> : null}
  </section>;
}
