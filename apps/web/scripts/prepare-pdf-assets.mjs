// Serve the pinned PDF.js codecs, CMaps and fallback fonts from our own origin.
import { cpSync, mkdirSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
const require = createRequire(import.meta.url);
const packageRoot = dirname(require.resolve('pdfjs-dist/package.json'));
const target = new URL('../public/pdfjs/', import.meta.url);
mkdirSync(target, { recursive: true });
for (const directory of ['wasm', 'cmaps', 'standard_fonts']) cpSync(join(packageRoot, directory), new URL(directory, target), { recursive: true });
cpSync(join(packageRoot, 'LICENSE'), new URL('LICENSE', target));
