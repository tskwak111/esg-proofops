import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { elementLabels, getElementLabel, getReasonLabel } from "../../apps/web/src/features/labels.ts";

const domain = readFileSync(new URL("../../sources/PROJECT_DOMAIN_V2_ORIGINAL.md", import.meta.url), "utf8");
const rows = [...domain.matchAll(/^\| ([GPM]\d) \| ([^|]+) \|/gm)];
assert.equal(rows.length, 20);
assert.equal(Object.keys(elementLabels).length, rows.length);
for (const [, id, label] of rows) assert.equal(getElementLabel(id), `${id} · ${label.trim()}`);
for (const unknown of ["G9", "constructor", "__proto__", ""]) assert.equal(getElementLabel(unknown), unknown);
console.log("20 domain labels and unknown-ID fallback verified");
assert.equal(getReasonLabel('DOMAIN_RULEPACK_UNAPPROVED'), 'DOMAIN_RULEPACK_UNAPPROVED · 이 실행의 규칙집 검토가 완료되지 않았습니다');
assert.equal(getReasonLabel('RULEPACK_APPROVAL_REQUIRED'), 'RULEPACK_APPROVAL_REQUIRED · 규칙집 승인이 필요합니다');
for (const code of ['SOURCE_VALIDATION_REQUIRED', 'CONSENSUS_UNRESOLVED', 'RELATION_TAGS_UNRESOLVED', 'PRELIMINARY_TAGS_UNRESOLVED']) {
  assert.ok(getReasonLabel(code).startsWith(code + ' · '));
}
for (const unknown of ['FUTURE_REASON', 'constructor', '__proto__', '']) assert.equal(getReasonLabel(unknown), unknown);
console.log('Internal reason codes retain identity with Korean explanations');
