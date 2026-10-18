/** Display only names supplied by the uploader/API, never infer a company from claims. */
export type DocumentMetadata = { ux1_metadata?: { original_filename?: string; title?: string; policy_sha256?: string }; display_name?: string; company_name?: string; original_filename?: string; filename?: string; title?: string };

export function metadataText(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  const text = value.trim();
  return text && !/^(?:.*미제공|없음|unknown|undefined|null|n\/?a|[-—])$/i.test(text) ? text : undefined;
}

export function reportTitle(value: unknown): string | undefined {
  const supplied = metadataText(value);
  const text = supplied && metadataText(cleanReportName(supplied));
  if (!text || /^(?:(?:기존 )?보고서(?:\s*·?\s*(?:\d+쪽|\d+|[a-f0-9]{8}))?|분석 보고서)$/i.test(text)) return undefined;
  return text;
}

export function documentName(document: DocumentMetadata, uploadedFilename?: string): string | undefined {
  const titles = [document.ux1_metadata?.title, document.title]
    .filter(value => !/^(?:Microsoft (?:Word|Excel|PowerPoint)\b|Untitled\b)/i.test(value?.trim() ?? ""));
  // Require Hangul in the supplied title too: translating an English filename
  // convention must not make English-only PDF metadata outrank an upload name.
  const koreanTitle = titles.filter(value => /[가-힣]/.test(value ?? "")).map(reportTitle)
    .find(title => title && /[가-힣]/.test(title) && !/^(?:(?:20\d{2}년?\s*)?(?:지속가능(?:경영)?보고서|통합보고서|보고서)|(?:내부\s*)?제목(?:\s*없음)?|무제|새\s*문서)(?:\s*20\d{2}년?)?$/i.test(title));
  return koreanTitle
    ?? [uploadedFilename, document.ux1_metadata?.original_filename, document.original_filename, document.filename].map(reportTitle).find(Boolean)
    ?? titles.map(reportTitle).find(Boolean)
    ?? reportTitle(document.display_name)
    ?? metadataText(document.company_name);
}

/** Recover legacy upload names only from metadata for the exact same PDF bytes. */
export function reportNames(documents: (DocumentMetadata & { document_id: string; sha256?: string })[]): Record<string, string | undefined> {
  const bySha = new Map<string, string>();
  for (const doc of documents) {
    const name = documentName(doc);
    if (doc.sha256 && name && !bySha.has(doc.sha256)) bySha.set(doc.sha256, name);
  }
  return Object.fromEntries(documents.map(doc => [doc.document_id, documentName(doc) ?? (doc.sha256 ? bySha.get(doc.sha256) : undefined)]));
}

/** Shared display normalization; source filenames/metadata remain untouched. */
export function cleanReportName(name: string): string {
  // Titles can contain markup-like text; preserve it for the renderer to escape.
  const file = (/[<>]/.test(name) ? name : name.replace(/^.*[/\\]/, "")).trim().replace(/\.pdf$/i, "");
  const text = file.replace(/_/g, " ").replace(/\s+/g, " ").trim()
    .replace(/(20\d{2})(?:(?:[ -]*(?:final|korean|kor|eng|kr|en|fn|f|k)|[ -]*\((?:kor|kr|korean|eng|en)\)))+$/i, "$1");
  const title = /20\d{2}/.test(text)
    ? text.replace(/(?:[ -]+(?:final|korean|kor|eng|kr|en|fn|f|k|\((?:kor|kr|korean|eng|en)\)))+$/i, "")
    : text;
  const companyFirst = /^(.+?)[ -]+Sustainability[ -]*Report[ -]*(20\d{2}(?:[-–]20\d{2})?)(?:[ -]+(?:Korean|KOR|KR|ENG|EN))?$/i.exec(title);
  if (companyFirst) return `${companyFirst[1]} ${companyFirst[2]} 지속가능경영보고서`;
  const yearFirst = /^(20\d{2}(?:[-–]20\d{2})?)[ -]+(.+?)[ -]+Sustainability[ -]*Report(?:[ -]+(?:Korean|KOR|KR|ENG|EN))?$/i.exec(title);
  return yearFirst ? `${yearFirst[2]} ${yearFirst[1]} 지속가능경영보고서` : title;
}
