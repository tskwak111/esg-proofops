const assert = require('node:assert/strict');
const fs = require('node:fs');
const { test } = require('node:test');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, filename);
const { sourcePages, verifiedHighlights, validateManifest, sourceErrorText } = require('./sourcePageModel.ts');
const run = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const version = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
test('source refs map selected pages to original physical pages without guessing missing maps', () => {
  const claim = { page_num: 1, source_refs: [{ page_num: 1, document_version_id: version }], elements: [{ evidence_refs: [{ page_num: 2, document_version_id: version }] }] };
  assert.deepEqual(sourcePages({ page_map: [25,30] }, claim), [25,30]);
  assert.deepEqual(sourcePages({ page_map: [] }, claim), []);
});
test('C3 original refs preserve p36 and still reject pages outside the selected scope', () => {
  const claim = { source_ref_page_space: 'original', source_refs: [{ page_num: 36, document_version_id: version }], elements: [] };
  assert.deepEqual(sourcePages({ page_map: [36] }, claim), [36]);
  assert.deepEqual(sourcePages({ page_map: [35] }, claim), []);
});
test('only verified finite normalized boxes are displayed, with no second rotation', () => {
  const highlight = bbox => ({ verification_state: 'verified', bbox_normalized: bbox });
  const manifest = { highlights: [highlight([.1,.2,.3,.4]), { ...highlight([0,0,1,1]), verification_state: 'candidate' }, highlight([-.1,0,1,1]), highlight([.3,0,.2,1]), highlight([0,0,Infinity,1])] };
  assert.deepEqual(verifiedHighlights(manifest).map(x => x.bbox_normalized), [[.1,.2,.3,.4]]);
});
test('manifest identity and coordinate space fail closed; source failures retain their meaning', () => {
  const manifest = { run_id: run, physical_page: 25, document_version_id: version, image_sha256: 'a'.repeat(64), image: { width_px: 1200, height_px: 800 }, coordinates: { origin: 'top_left', space: 'rotated_cropbox_display', bbox_format: 'x0,y0,x1,y1' }, highlights: [], unresolved_refs: [] };
  assert.doesNotThrow(() => validateManifest(manifest, run, 25, [version]));
  assert.throws(() => validateManifest({ ...manifest, run_id: version }, run, 25, [version]));
  assert.throws(() => validateManifest(manifest, run, 25, [run]));
  assert.throws(() => validateManifest({ ...manifest, coordinates: { ...manifest.coordinates, origin: 'bottom_left' } }, run, 25, [version]));
  assert.match(sourceErrorText({ status: 410 }), /보관 기간.*만료/);
  assert.match(sourceErrorText({ status: 404 }), /권한.*없거나.*찾을 수/);
});
