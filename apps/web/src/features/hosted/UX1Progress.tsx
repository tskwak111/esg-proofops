import { useEffect, useState } from "react";
import type { HostedRun } from "./hostedClient";
import { progressSteps, remainingEstimate, stageActivity } from "./ux1Model";

export function UX1Progress({ run }: { run: HostedRun }) {
  return <div className="ux1-progress"><ol className="analysis-steps ux1-steps" aria-label="실제 분석 단계">{progressSteps(run).map(step=><li key={step.label} className={step.state === "active" ? "active" : step.state === "previous" || step.state === "done" ? "done" : ""} aria-current={step.state === "active" ? "step" : undefined}><b>{step.label}</b><span>{step.state === "active" ? "진행 중" : step.state === "done" ? "완료" : step.state === "previous" ? "완료" : "대기"}</span></li>)}</ol>
    <StageActivity key={`${run.run_id}:${run.status}:${run.stage}`} run={run} />
    <p><strong>{remainingEstimate(run)}</strong></p>
    <a className="hosted-secondary" href="/demo" target="_blank" rel="noopener noreferrer">기다리는 동안 분석 사례 보기 ↗</a>
  </div>;
}

function StageActivity({ run }: { run: HostedRun }) {
  const [startedAt] = useState(() => Date.now());
  const [seconds, setSeconds] = useState(0);
  const active = run.status === "running" || run.status === "queued";
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setSeconds((Date.now() - startedAt) / 1000), 1000);
    return () => window.clearInterval(timer);
  }, [active, startedAt]);
  const activity = stageActivity(run, seconds);
  if (!activity) return null;
  return <div className="ux2-stage-activity">
    <p><strong>현재 단계 관찰 시간 · <span role="timer" aria-live="off">{activity.elapsed}</span></strong></p>
    <p>{activity.description}</p>
    {activity.counters.length > 0 && <><dl className="ux2-stage-counts" aria-label="주장별 단계 처리 집계">{activity.counters.map(counter => <div key={counter.key}><dt>{counter.label}</dt><dd>{counter.completed}건</dd></div>)}</dl><p className="caption">서버가 보고한 단계별 처리 건수입니다. 같은 주장이 여러 단계에 포함될 수 있으며, 성공 판정 수와는 다릅니다.</p></>}
    <p className="caption">{activity.note}</p>
  </div>;
}
