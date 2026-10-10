type Report = {
  claims: { quote: string; page: number; track: string | null; blocked_reason: string | null;
    decision: { evidence_grade: string | null; decision_status: string;
      grade_range?: {floor: string; ceiling: string} | null; unresolved_elements?: string[] } | null }[];
  notice: string;
};

export function LiveExport({ report }: { report: Report }) {
  function save(format: "json" | "csv" | "html") {
    const escape = (text: string) => text.replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]!);
    // Spreadsheet imports must not interpret report text as a formula.
    const csv = (value: unknown) => `"${String(value ?? "").replace(/^[=+@\-\t\r]/, "'$&").replaceAll('"', '""')}"`;
    const rows = report.claims.map(c => [c.page, c.quote, c.track, c.decision?.evidence_grade ??
      (c.decision?.grade_range ? `${c.decision.grade_range.floor}–${c.decision.grade_range.ceiling} (범위)` : "미확정"),
      c.blocked_reason || c.decision?.unresolved_elements?.join(", ") || c.decision?.decision_status]);
    const content = format === "json" ? JSON.stringify(report, null, 2) : format === "csv"
      ? "\ufeff" + [["쪽", "주장", "트랙", "등급", "보류·판정 상태"], ...rows].map(row => row.map(csv).join(",")).join("\r\n")
      : `<!doctype html><html lang="ko"><meta charset="utf-8"><title>ProofOps 근거 검토 보고서</title><style>body{font:16px sans-serif;max-width:900px;margin:40px auto;padding:24px}article{break-inside:avoid;border-bottom:1px solid #ccc;padding:16px 0}blockquote{margin:12px 0;white-space:pre-wrap}@media print{body{margin:0}}</style><h1>근거 검토 보고서</h1><p>${escape(report.notice)}</p><p>사용자 최종 검토 전 · 미확정은 부재나 통과가 아닙니다.</p>${rows.map(row => `<article><h2>p.${row[0]} · ${escape(String(row[2] ?? "분류 미확인"))}</h2><blockquote>${escape(String(row[1]))}</blockquote><p>${escape(String(row[3]))} · ${escape(String(row[4] ?? "검토 필요"))}</p></article>`).join("")}</html>`;
    const url = URL.createObjectURL(new Blob([content], { type: format === "html" ? "text/html;charset=utf-8" : format === "csv" ? "text/csv;charset=utf-8" : "application/json" }));
    const link = document.createElement("a"); link.href = url; link.download = `proofops-review.${format}`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <div className="live-export" aria-label="검토 보고서 내보내기"><button onClick={() => save("json")}>근거 JSON</button> <button onClick={() => save("csv")}>주장 CSV</button> <button onClick={() => save("html")}>검토 보고서 · 인쇄/PDF용 HTML</button></div>;
}
