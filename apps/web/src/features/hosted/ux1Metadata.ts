import { documentName, metadataText, reportTitle, type DocumentMetadata } from "./documentName";

/** Filename/title convention only; never guess a company from claim text or PDF author. */
export function ux1CompanyName(document: DocumentMetadata): string | undefined {
  const explicit = metadataText(document.company_name);
  if (explicit) return explicit;
  const title = documentName(document);
  if (!title) return undefined;
  const prefix = /^(.*?)[ -]+(?:지속가능(?:경영)?보고서|통합보고서|기업시민보고서|(?:sustainability|sustainable)[ -]*(?:report)?|ESG(?:[ -]*보고서)?|Report)(?=$|[ \d-])/i.exec(title)?.[1];
  if (!prefix) return undefined;
  const company = prefix
    .replace(/^(?:20\d{2}(?:[-–]20\d{2})?년?(?:[ -]+|$))+/, "")
    .replace(/(?:[ -]+20\d{2}(?:[-–]20\d{2})?년?)+$/, "").trim();
  if (!company || company.split(/[ -]+/).every(token => /^(?:\d+|sr|kor|kr|eng|en|fn|final|esg)$/i.test(token))) return undefined;
  return metadataText(company);
}
export async function uploadMetadata(file: Blob): Promise<{ original_filename?: string; title?: string }> {
  const original_filename = typeof File !== "undefined" && file instanceof File ? file.name.replace(/.*[/\\]/, "").replace(/[\x00-\x1f]/g, " ").slice(0,200) : undefined;
  let title: string | undefined;
  try {
    const { PDFDocument } = await import("pdf-lib");
    const pdf = await PDFDocument.load(await file.arrayBuffer(), { updateMetadata: false });
    title = reportTitle(pdf.getTitle()?.replace(/[\x00-\x1f]/g, " "))?.slice(0,200);
  } catch { /* Metadata is optional; the server still validates the untouched PDF bytes. */ }
  return { original_filename, title };
}
