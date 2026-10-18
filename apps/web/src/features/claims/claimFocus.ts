/** Move mobile readers between the sentence list and its existing detail pane. */
export function focusClaimDetail(element: HTMLElement | null) {
  if (!element || !window.matchMedia("(max-width: 1024px)").matches) return;
  focusClaimRegion(element);
}
export function focusClaimRegion(element: HTMLElement | null) {
  if (!element) return;
  element.focus({ preventScroll: true });
  element.scrollIntoView({ block: "start", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}
