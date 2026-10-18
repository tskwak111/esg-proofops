import { useEffect, useRef, useState } from "react";
import type { HostedClient, HostedResult, ListedRun } from "./hostedClient";
import { documentName } from "./documentName";
import { resultBrowserSummary, resultScope } from "./resultModel";
import { reportInsights, UX1_HASH } from "./ux1Model";

type ComparisonReport = { result: HostedResult; name: string; pageCount: number; pages: number[]; runId: string };
export function ComparisonResults({ reports }: { reports: ComparisonReport[] }) {
  return <div className="ux1-comparison-results"><p className="hosted-note">선택 범위·주장 수·보고기간이 다르면 직접적인 기업 순위로 해석할 수 없습니다. 비율은 각 보고서의 전체 추출 주장 수를 분모로 사용합니다. 확정 등급만 분포에 집계하며 보류는 등급을 부여하지 않습니다.</p>
    <div className="ux1-compare-grid">{reports.map(report=>{
      const counts = resultBrowserSummary(report.result), scope = resultScope(report.result,report.pageCount,report.pages), insight = reportInsights(report.result);
      return <article className="ux1-card" key={report.runId}><h4>{report.name}</h4>{counts.provisional > 0 && <p className="hosted-state">이전 버전 결과 · 추가 확인 필요 주장은 확정·보류와 별도로 집계합니다.</p>}<p>분석 범위 {scope.pages.length} / 전체 {scope.total ?? "미제공"}쪽 · {report.result.pipeline?.reporting_scope?.report_year ?? "보고연도 미제공"}</p><p>추출 {counts.total} · 확정 {counts.confirmed}{counts.provisional > 0 && <> · 추가 확인 필요 {counts.provisional}</>} · 보류 {counts.hold}건</p>
        <h5>확정 등급 분포</h5>{["E3","E2","E1","E0"].map(g=><div className="ux1-compare-grade" key={g}><b>{g}</b><meter min={0} max={Math.max(1,counts.total)} value={counts.confirmedGrades[g]} aria-label={`${report.name} ${g}`} /><span>{counts.confirmedGrades[g]}건 · {counts.total ? Math.round(100*counts.confirmedGrades[g]/counts.total) : 0}%</span></div>)}
        <h5>트랙별 확정 등급 / 보류</h5><table><thead><tr><th>트랙</th><th>E3 / E2 / E1 / E0</th><th>보류</th></tr></thead><tbody>{insight.tracks.map(t=><tr key={t.track}><th>{t.name}<small> {t.total}건</small></th><td>{["E3","E2","E1","E0"].map(g=>t.grades[g]).join(" / ")}</td><td>{t.hold}</td></tr>)}</tbody></table>
      </article>;
    })}</div></div>;
}
export function UX1Comparison({ client, onFailure }: { client: HostedClient; onFailure: (error: unknown)=>void }) {
  const [open,setOpen]=useState(false), [runs,setRuns]=useState<ListedRun[]>([]), [names,setNames]=useState<Record<string,string>>({});
  const [cursor,setCursor]=useState<string|null>(null), [ids,setIds]=useState<[string,string]>(["",""]), [reports,setReports]=useState<ComparisonReport[]>([]);
  const [busy,setBusy]=useState(false), [error,setError]=useState("");
  const abort=useRef<AbortController|null>(null);
  useEffect(()=>()=>abort.current?.abort(),[]);
  async function load(more=false) {
    abort.current?.abort(); const controller=new AbortController(); abort.current=controller;
    setBusy(true);setError("");
    try {
      const [executions,docs]=await Promise.all([client.listRuns(more?cursor:null,controller.signal),client.listDocuments(null,controller.signal)]);
      if(controller.signal.aborted)return;
      const available=executions.items.filter(r=>["completed","partial_blocked"].includes(r.status));
      setRuns(old=>more?[...old,...available.filter(r=>!old.some(o=>o.run_id===r.run_id))]:available);setCursor(executions.next_cursor);
      setNames(Object.fromEntries(docs.items.map(d=>[d.document_id,documentName(d)??`보고서 ${d.document_id.slice(0,8)}`])));
    } catch(err){if(!controller.signal.aborted){setError("비교할 실행 목록을 불러오지 못했습니다.");onFailure(err);}}
    finally{if(!controller.signal.aborted)setBusy(false);}
  }
  async function compare() {
    if(!ids[0] || !ids[1] || ids[0]===ids[1])return;
    abort.current?.abort(); const controller=new AbortController();abort.current=controller;
    setBusy(true);setError("");setReports([]);
    try {
      const loaded=await Promise.all(ids.map(async id=>{
        const run=await client.getRun(`/v1/runs/${id}`,controller.signal);
        if(!["completed","partial_blocked"].includes(run.status))throw new Error("분석이 완료되지 않았습니다.");
        const [result,doc]=await Promise.all([run.result_url?client.getResult(run.result_url,controller.signal,UX1_HASH):Promise.resolve(run.result),client.getDocument(run.document_id,controller.signal)]);
        if(!result)throw new Error("저장된 결과가 없습니다.");
        return {result,name:documentName(doc)??`보고서 ${run.document_id.slice(0,8)}`,pageCount:doc.page_count,pages:run.selected_pages,runId:id};
      }));
      if(!controller.signal.aborted)setReports(loaded);
    } catch(err){if(!controller.signal.aborted){setError("두 보고서를 비교하지 못했습니다. 접근 권한과 결과 상태를 확인해 주세요.");onFailure(err);}}
    finally{if(!controller.signal.aborted)setBusy(false);}
  }
  return <section className="ux1-comparison ux1-card" aria-label="보고서 비교"><button type="button" className="hosted-secondary" aria-expanded={open} onClick={()=>{setOpen(!open);if(!open)void load();}}>보고서 2개 비교{open?" 닫기":" 열기"}</button>
    {open && <><h3>두 보고서의 근거 수준 비교</h3><div className="ux1-compare-controls">{[0,1].map(i=><label key={i}>보고서 {i+1}<select aria-label={`비교 보고서 ${i+1}`} value={ids[i]} disabled={busy} onChange={e=>{setIds(old=>i===0?[e.target.value,old[1]]:[old[0],e.target.value]);setReports([]);}}><option value="">분석 결과 선택</option>{runs.map(r=><option key={r.run_id} value={r.run_id}>{names[r.document_id]??`보고서 ${r.document_id.slice(0,8)}`} · {r.run_id.slice(0,8)}</option>)}</select></label>)}<button className="hosted-primary" type="button" disabled={busy||!ids[0]||!ids[1]||ids[0]===ids[1]} onClick={()=>void compare()}>비교하기</button></div>
    {ids[0]&&ids[0]===ids[1]&&<p>서로 다른 분석 결과를 선택해 주세요.</p>}{cursor&&<button type="button" disabled={busy} onClick={()=>void load(true)}>실행 더 보기</button>}{busy&&<p role="status">비교 데이터 불러오는 중…</p>}{error&&<p role="alert">{error}</p>}{!busy&&!runs.length&&!error&&<p>완료된 분석 결과가 없습니다.</p>}{reports.length===2&&<ComparisonResults reports={reports}/>}</>}
  </section>;
}
