import { useEffect, useRef, type ReactNode } from "react";
import type { ResultTab } from "./hostedHistory";

export type ResultTabItem = { key: ResultTab; label: string; hint: string; badge?: ReactNode };
export const resultTabId = (base: string, key: ResultTab) => `${base}-result-tab-${key}`;
export const resultPanelId = (base: string, key: ResultTab) => `${base}-result-panel-${key}`;

/** WAI-ARIA tabs with manual activation: arrows/Home/End move focus, Enter/Space (native click) selects. */
export function ResultTabs({ base, tabs, selected, onSelect }: { base: string; tabs: ResultTabItem[]; selected: ResultTab; onSelect: (tab: ResultTab) => void }) {
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    // Keep the selected tab visible when the bar scrolls horizontally (also after breakpoint changes); never scroll the page.
    const reveal = () => {
      const bar = list.current, tab = bar?.querySelector<HTMLElement>('[aria-selected="true"]');
      if (!bar || !tab || bar.scrollWidth <= bar.clientWidth) return;
      if (tab.offsetLeft < bar.scrollLeft) bar.scrollLeft = tab.offsetLeft;
      else if (tab.offsetLeft + tab.offsetWidth > bar.scrollLeft + bar.clientWidth) bar.scrollLeft = tab.offsetLeft + tab.offsetWidth - bar.clientWidth;
    };
    reveal();
    window.addEventListener("resize", reveal);
    return () => window.removeEventListener("resize", reveal);
  }, [selected]);
  useEffect(() => {
    // Publish the bar height on the result section so sticky children (claim detail) sit right below it.
    const bar = list.current, owner = bar?.parentElement;
    if (!bar || !owner || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => owner.style.setProperty("--result-tabs-h", `${bar.offsetHeight}px`));
    observer.observe(bar);
    return () => observer.disconnect();
  }, []);
  return <div ref={list} className="result-tabs" role="tablist" aria-label="결과 보기 방식">{tabs.map((tab, index) =>
    <button type="button" role="tab" key={tab.key} id={resultTabId(base, tab.key)} aria-controls={resultPanelId(base, tab.key)} aria-selected={selected === tab.key} tabIndex={selected === tab.key ? 0 : -1}
      onClick={() => onSelect(tab.key)} onKeyDown={event => {
        const target = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft" ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
        if (target === null) return;
        event.preventDefault();
        const next = document.getElementById(resultTabId(base, tabs[target].key));
        next?.focus(); next?.scrollIntoView({ block: "nearest", inline: "nearest" });
      }}>
      <span className="result-tab-label">{tab.label}{tab.badge !== undefined && <span className="result-tab-badge">{tab.badge}</span>}</span>
      <span className="result-tab-hint">{tab.hint}</span>
    </button>)}</div>;
}
