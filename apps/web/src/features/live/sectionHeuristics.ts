export type Section = "E" | "S" | "G" | "A" | "O";
export type PageInfo = { page: number; section: Section; source: "북마크" | "목차" | "머리글" | "키워드"; score: number; assurance: boolean };
export type Anchor = { page: number; section: Section };
const environment = /온실가스|배출|Scope\s*[123]|탄소|재생에너지|RE100|에너지|용수|폐기물|기후|TCFD|감축|생물다양성|자원순환/gi;
const assurance = /검증의견서|제3자 검증|독립된 검증|Assurance|GRI Index|GRI Standards/i;
const social = /인권|인재|안전보건|공급망|고객만족|사회공헌|정보보안/gi;
const governance = /이사회|주주|조세|윤리|준법|리스크 관리|지배구조/gi;
const appendix = /ESG Data|Appendix|부록|ESG 지표|검증의견서|GRI Index|Reporting Index/gi;
const titles: [Section, RegExp][] = [
  ["A", /Appendix|부록|ESG Data|GRI Index|검증의견서/i],
  ["E", /\bEnvironment(?:al)?\b|환경|기후변화|자원순환|온실가스|에너지관리/i],
  ["S", /Social|사회|인권경영|인재관리/i],
  ["G", /Governance|지배구조|이사회/i],
];

export function titleSection(title: string): Section | null {
  for (const [section, pattern] of titles) if (pattern.test(title)) return section;
  return null;
}

export function tocAnchors(text: string, total: number): Anchor[] {
  if (!/Contents|목차|Table of Contents/i.test(text.slice(0, 120))) return [];
  const headings: [Section, RegExp, RegExp][] = [
    ["E", /\bEnvironmental\b/gi, /환경(?:\s*분야)?/gi],
    ["S", /\bSocial\b/gi, /사회(?:\s*분야)?/gi],
    ["G", /\bGovernance\b/gi, /지배구조/gi],
    ["A", /ESG Data & Appendix|\bAppendix\b/gi, /부록/gi],
  ];
  const found: Anchor[] = [];
  for (const [section, english, korean] of headings) {
    const matches = [...text.matchAll(english)];
    if (!matches.length) matches.push(...text.matchAll(korean));
    const last = matches[0];
    if (last?.index == null) continue;
    // Accept only an adjacent page label; a distant number may belong to another column.
    const nextNumber = text.slice(last.index + last[0].length).match(/^\s*[.·…\s]*(\d{1,3})(?:\s|$)/);
    const page = Number(nextNumber?.[1]);
    if (page >= 1 && page <= total) found.push({ page, section });
  }
  return found;
}

export function category(text: string): { section: Section; score: number; assurance: boolean; source: PageInfo["source"] } {
  const head = text.slice(0, 260);
  const singular = titles.filter(([, pattern]) => pattern.test(head));
  const headerSection = singular.length === 1 ? singular[0][0] : null;
  const counts: [Section, number][] = [
    ["E", [...text.matchAll(environment)].length],
    ["S", [...text.matchAll(social)].length],
    ["G", [...text.matchAll(governance)].length],
    ["A", [...text.matchAll(appendix)].length],
  ];
  counts.sort((a, b) => b[1] - a[1]);
  const strongContent = counts[0][1] >= 4 && counts[0][1] >= counts[1][1] * 2;
  const section = strongContent ? counts[0][0] : headerSection || (counts[0][1] >= 2 && counts[0][1] > counts[1][1] ? counts[0][0] : "O");
  return { section, score: [...text.matchAll(environment)].length,
    assurance: assurance.test(text), source: headerSection ? "머리글" : "키워드" };
}

export function pickPages(info: PageInfo[], selected: Section[]) {
  const matches = info.filter(item => selected.includes(item.section));
  const retained = matches.length <= 60 ? matches : [...matches].sort((a, b) =>
    Number(b.section === "E") - Number(a.section === "E") || b.score - a.score || Number(b.assurance) - Number(a.assurance) || a.page - b.page).slice(0, 60);
  return { pages: retained.map(item => item.page).sort((a, b) => a - b), dropped: matches.length - retained.length };
}
