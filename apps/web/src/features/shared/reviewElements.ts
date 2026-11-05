import type { ReviewElement, Track } from "./wireTypes";

const elementIds: Record<Track, string[]> = {
  goal: Array.from({ length: 8 }, (_, index) => `G${index + 1}`),
  performance: Array.from({ length: 6 }, (_, index) => `P${index + 1}`),
  management: Array.from({ length: 6 }, (_, index) => `M${index + 1}`),
};

export function completeElements(track: Track, elements: ReviewElement[]): ReviewElement[] {
  return elementIds[track].map(element_id => elements.find(element => element.element_id === element_id) ?? {
    element_id,
    state: "unknown",
    evidence_refs: [],
    normalized_value: null,
    credited_from: null,
    reason_code: null,
  });
}
