import type { HostedResult, ResultClaim, SourcePageManifest, SourceRefDto } from "./hostedClient";

export function claimRefs(claim: ResultClaim): SourceRefDto[] {
  return [...claim.source_refs, ...claim.elements.flatMap(element => element.evidence_refs), ...(claim.provisional_grade?.elements?.flatMap(element => element.evidence_refs) ?? [])];
}
export function sourcePages(result: Pick<HostedResult, "page_map">, claim: ResultClaim): number[] {
  return [...new Set(claimRefs(claim).map(ref => originalRefPage(result, claim, ref)).filter((page): page is number => Number.isInteger(page) && page != null && page > 0))];
}
export function originalRefPage(result: Pick<HostedResult, "page_map">, claim: ResultClaim, ref: Pick<SourceRefDto, "page_num">): number | undefined {
  return claim.source_ref_page_space === "original" ? result.page_map.includes(ref.page_num) ? ref.page_num : undefined : result.page_map?.[ref.page_num - 1];
}
export function verifiedHighlights(manifest: SourcePageManifest) {
  return manifest.highlights.filter(ref => ref.verification_state === "verified" && Array.isArray(ref.bbox_normalized) && ref.bbox_normalized.length === 4
    && ref.bbox_normalized.every(x => Number.isFinite(x) && x >= 0 && x <= 1)
    && ref.bbox_normalized[0] < ref.bbox_normalized[2] && ref.bbox_normalized[1] < ref.bbox_normalized[3]);
}
export function validateManifest(manifest: SourcePageManifest, runId: string, page: number, versions: string[]) {
  const image = manifest.image, coordinates = manifest.coordinates;
  if (manifest.run_id !== runId || manifest.physical_page !== page || !versions.length || !versions.includes(manifest.document_version_id)
    || !/^[0-9a-f]{64}$/.test(manifest.image_sha256) || !Array.isArray(manifest.highlights) || !Array.isArray(manifest.unresolved_refs)
    || !image || ![image.width_px,image.height_px].every(x => Number.isInteger(x) && x > 0 && x <= 2000) || image.width_px * image.height_px > 4000000
    || coordinates?.origin !== "top_left" || coordinates.space !== "rotated_cropbox_display" || coordinates.bbox_format !== "x0,y0,x1,y1") throw new Error("원문 버전 또는 좌표 정보를 확인할 수 없습니다. 이미지를 표시하지 않았습니다.");
}
export function sourceErrorText(error: { status?: number; code?: string; retryAfter?: number | null; message?: string }) {
  if (error.status === 410) return "원문 보관 기간이 만료되었습니다. 원문을 다시 업로드해야 볼 수 있습니다.";
  if (error.status === 404) return "원문을 볼 권한이 없거나 원문 쪽을 찾을 수 없습니다. 구버전 서버에서는 원문 보기를 지원하지 않을 수 있습니다.";
  if (error.status === 401) return "로그인이 만료되었습니다. 다시 로그인한 뒤 원문을 열어 주세요.";
  if (error.status === 403) return "원문을 볼 권한이 없습니다.";
  if (error.status === 429) return `원문 이미지 처리 중입니다. ${error.retryAfter ?? 5}초 뒤에 다시 열어 주세요.`;
  if (error.status === 409) return "원문 버전 또는 이미지 무결성을 확인할 수 없습니다. 이미지를 표시하지 않았습니다.";
  if (error.status === 422) return "이 원문 쪽을 이미지로 표시할 수 없습니다. 쪽 번호와 원문 인용을 확인해 주세요.";
  return error.message ?? "원문을 불러오지 못했습니다. 다시 시도해 주세요.";
}
