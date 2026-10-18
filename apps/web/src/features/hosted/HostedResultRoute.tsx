import { Link, Navigate, useLocation } from "react-router";
import { runIdFromResultPath } from "./hostedHistory";

export const hostedResultPaths = ["/v1/runs/:runId/result", "/runs/:runId/result"];

// Keep the run in the URL through invitation login, expiry and page reload.
export function HostedResultRoute() {
  const location = useLocation();
  const runId = runIdFromResultPath(location.pathname);
  if (!runId) return <main className="static-main"><h1>분석 번호를 확인해 주세요</h1><Link to="/analyze">분석 화면으로 이동</Link></main>;
  return <Navigate to={`/analyze${location.search}#run-${runId}`} replace />;
}
