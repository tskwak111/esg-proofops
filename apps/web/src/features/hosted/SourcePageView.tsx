import { useEffect, useState } from "react";
import type { HostedClient, HostedResult, ResultClaim, SourcePageManifest } from "./hostedClient";
import { claimRefs, originalRefPage, sourceErrorText, sourcePages, validateManifest, verifiedHighlights } from "./sourcePageModel";

export function SourcePageView({ claim, result, client, runId, openRequest }: { claim: ResultClaim; result: HostedResult; client: HostedClient; runId: string; openRequest?: { page: number; nonce: number } | null }) {
  const pages = sourcePages(result, claim);
  const [page, setPage] = useState(pages[0] ?? 0);
  const [opened, setOpened] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [zoom, setZoom] = useState(1);
  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const [manifest, setManifest] = useState<SourcePageManifest | null>(null);
  const [image, setImage] = useState("");
  useEffect(() => {
    if (openRequest && pages.includes(openRequest.page)) { setPage(openRequest.page); setOpened(true); }
  }, [openRequest]);
  useEffect(() => {
    if (!opened || !page) return;
    const controller = new AbortController();
    let objectUrl = "";
    setError(""); setImage(""); setManifest(null); setLoading("원문 위치 확인 중…"); setZoom(1);
    void (async () => {
      try {
        const next = await client.getSourceManifest(runId, page, claim.claim_id, controller.signal);
        if (controller.signal.aborted) return;
        const versions = claimRefs(claim).filter(ref => originalRefPage(result, claim, ref) === page).map(ref => ref.document_version_id);
        validateManifest(next, runId, page, versions);
        setLoading("원문 이미지 불러오는 중…");
        const blob = await client.getSourceImage(next, controller.signal);
        if (controller.signal.aborted) return;
        objectUrl = URL.createObjectURL(blob); setManifest(next); setImage(objectUrl); setLoading("");
      } catch (err) { if (!controller.signal.aborted) { setError(sourceErrorText(err as Error)); setLoading(""); } }
    })();
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl); };
  }, [opened, page, attempt, client, runId, claim, result]);
  const highlights = manifest ? verifiedHighlights(manifest) : [];
  const unresolved = manifest && (manifest.unresolved_refs.length > 0 || highlights.length < manifest.highlights.length || !highlights.length);
  return <section className="source-viewer detail-block" aria-label="원문 쪽 보기">
    <h4>원문 보기</h4>
    <p className="caption">박스는 검증된 원문 위치입니다. 위치 확인만으로 요소나 등급이 확정되지는 않습니다.</p>
    {!pages.length ? <p role="status">원문 미검증 · 연결된 원문 쪽 위치가 없습니다.</p> : <>
      <div className="source-controls"><label>원문 쪽<select value={page} onChange={event => setPage(Number(event.target.value))}>{pages.map(number => <option key={number} value={number}>p.{number}</option>)}</select></label>
        <button type="button" aria-expanded={opened} onClick={() => setOpened(value => !value)}>{opened ? "원문 닫기" : "원문 보기"}</button></div>
      {opened && <>
        {loading && <p role="status" aria-live="polite">{loading}</p>}
        {error && <div role="alert"><p>{error}</p><button type="button" onClick={() => setAttempt(value => value + 1)}>원문 다시 불러오기</button></div>}
        {image && manifest && <>
          {unresolved && <p className="hosted-notice" role="status">원문 미검증 · 확인되지 않은 위치에는 박스를 표시하지 않습니다.</p>}
          <div className="source-controls" role="group" aria-label="원문 확대 축소">
            <button type="button" aria-label="원문 축소" disabled={zoom <= 1} onClick={() => setZoom(value => Math.max(1, value - .25))}>−</button>
            <output aria-live="polite">{Math.round(zoom * 100)}%</output>
            <button type="button" aria-label="원문 확대" disabled={zoom >= 3} onClick={() => setZoom(value => Math.min(3, value + .25))}>+</button>
            <button type="button" onClick={() => setZoom(1)}>화면에 맞추기</button>
          </div>
          <div className="source-scroll" tabIndex={0} aria-label={`원문 p.${page} 이미지, 확대 시 가로로 이동`}>
            <div className="source-canvas" style={{ width: `${zoom * 100}%`, aspectRatio: `${manifest.image.width_px} / ${manifest.image.height_px}` }}>
              <img src={image} alt={`보고서 원문 p.${page}. 원문 인용은 위의 주장과 요소별 근거에서 확인할 수 있습니다.`} onError={() => { setImage(""); setError("원문 이미지를 표시하지 못했습니다. 다시 불러와 주세요."); }} />
              {highlights.map(ref => { const [x0,y0,x1,y1] = ref.bbox_normalized; return <span key={ref.ref_id} className="source-highlight" data-testid="source-highlight" aria-hidden="true" style={{ left: `${x0*100}%`, top: `${y0*100}%`, width: `${(x1-x0)*100}%`, height: `${(y1-y0)*100}%` }} />; })}
            </div>
          </div>
          <p className="caption">원문 p.{manifest.physical_page} · 검증된 위치 {highlights.length}곳 · 문서 버전 {manifest.document_version_id.slice(0,8)}</p>
        </>}
      </>}
    </>}
  </section>;
}
