import { type ReactNode } from "react";

export type BrowserOption = { value: string; label: string };
type Filter = { value: string; onChange: (value: string) => void; options: BrowserOption[]; help?: ReactNode };

/** Shared controls for saved cases and authenticated results. All state stays with the caller. */
export function ClaimBrowserControls({ tabs, queue, onQueueChange, panelId, search, onSearchChange, track, grade, status }: {
  tabs: { value: string; label: string; count: number }[]; queue: string; onQueueChange: (value: string) => void;
  panelId: string; search: string; onSearchChange: (value: string) => void; track: Filter; grade: Filter; status: Filter;
}) {
  const id = `${panelId}-tab`;
  return <>
    <div className="queue-tabs" role="tablist" aria-label="검토 상태">{tabs.map((tab, index) => <button type="button" role="tab" id={`${id}-${tab.value}`} aria-controls={panelId} tabIndex={queue === tab.value ? 0 : -1} aria-selected={queue === tab.value} key={tab.value} onClick={() => onQueueChange(tab.value)} onKeyDown={event => {
      const target = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
      if (target !== null) { event.preventDefault(); onQueueChange(tabs[target].value); document.getElementById(`${id}-${tabs[target].value}`)?.focus(); }
    }}>{tab.label} <span>{tab.count}</span></button>)}</div>
    <div className="filters">
      <label>검색<input value={search} onChange={event => onSearchChange(event.target.value)} placeholder="문장, 페이지 검색" /></label>
      {([["트랙", track], ["등급", grade], ["상태", status]] as const).map(([label, filter]) => <label key={label}>{label} {filter.help}<select value={filter.value} onChange={event => filter.onChange(event.target.value)}>{filter.options.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>)}
    </div>
  </>;
}
