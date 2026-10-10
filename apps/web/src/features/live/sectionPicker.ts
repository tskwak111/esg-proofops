import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

GlobalWorkerOptions.workerSrc = workerUrl;

import { category, titleSection, tocAnchors, type Anchor, type PageInfo, type Section } from "./sectionHeuristics";
export type { PageInfo, Section } from "./sectionHeuristics";

async function bookmarkAnchors(pdf: PDFDocumentProxy): Promise<Anchor[]> {
  const outline = await pdf.getOutline();
  if (!outline) return [];
  const anchors: Anchor[] = [];
  async function visit(nodes: typeof outline, inherited: Section = "O") {
    for (const node of nodes) {
      const section = titleSection(node.title) || inherited;
      if (node.dest) {
        try {
          const destination = typeof node.dest === "string" ? await pdf.getDestination(node.dest) : node.dest;
          if (destination) anchors.push({ page: (await pdf.getPageIndex(destination[0])) + 1, section });
        } catch { /* Broken bookmark: use contents or text. */ }
      }
      if (node.items.length) await visit(node.items, section);
    }
  }
  await visit(outline);
  return anchors;
}

export async function scanSections(file: File, onProgress: (current: number, total: number) => void): Promise<PageInfo[]> {
  const pdf = await getDocument({ data: new Uint8Array(await file.arrayBuffer()) }).promise;
  try {
    const total = pdf.numPages;
    const outline = await bookmarkAnchors(pdf);
    const texts: string[] = [];
    for (let page = 1; page <= total; page++) {
      const content = await (await pdf.getPage(page)).getTextContent();
      texts.push(content.items.filter(item => "str" in item).map(item => item.str + (item.hasEOL ? "\n" : " ")).join(""));
      if (page % 5 === 0 || page === total) onProgress(page, total);
    }
    // Repeated navigation bars (Environment / Social / Appendix on every page)
    // must not become section headings. Keep report-specific topic headings.
    const repeated = new Map<string, number>();
    for (const text of texts) {
      const lines = text.split("\n").map(line => line.trim()).filter(Boolean);
      for (const line of new Set([...lines.slice(0, 6), ...lines.slice(-3)])) repeated.set(line, (repeated.get(line) || 0) + 1);
    }
    for (let i = 0; i < texts.length; i++) {
      const lines = texts[i].split("\n");
      texts[i] = lines.filter((line, index) => !((index < 6 || index >= lines.length - 3) && (repeated.get(line.trim()) || 0) >= Math.max(5, total * 0.3))).join(" ");
    }
    const toc = outline.length >= 2 ? [] : texts.slice(0, Math.min(12, total)).flatMap(text => tocAnchors(text, total));
    // A bookmark/TOC is a hint, not authority over every subsequent page.
    // Reject section starts whose actual page does not support that section.
    const anchors = (outline.length >= 2 ? outline : toc).filter(anchor =>
      anchor.page >= 1 && anchor.page <= total &&
      (anchor.section === "O" || category(texts[anchor.page - 1]).section === anchor.section)
    ).sort((a, b) => a.page - b.page);
    const source = outline.length >= 2 ? "북마크" : "목차";
    return texts.map((text, index) => {
      const guessed = category(text);
      const anchor = anchors.filter(item => item.page <= index + 1).at(-1);
      const anchored = anchor && anchor.section !== "O" && guessed.section === "O" && index + 1 - anchor.page <= 12;
      return { page: index + 1, section: anchored ? anchor.section : guessed.section,
        source: anchored ? source : guessed.source,
        score: guessed.score, assurance: guessed.assurance };
    });
  } finally { await pdf.destroy(); }
}
