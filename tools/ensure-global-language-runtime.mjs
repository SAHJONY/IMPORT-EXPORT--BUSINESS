import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const targets = [
  'public/owner-cuba-mipymes.html',
];

for (const rel of targets) {
  const abs = path.join(root, rel);
  if (!fs.existsSync(abs)) {
    console.error(`Missing target for language runtime repair: ${rel}`);
    process.exitCode = 1;
    continue;
  }

  let html = fs.readFileSync(abs, 'utf8');
  if (/src=["']\/global-language\.js["']/i.test(html)) {
    console.log(`Global language runtime already present: ${rel}`);
    continue;
  }

  const runtime = '<script src="/global-language.js" defer></script>';
  if (/<\/body>/i.test(html)) {
    html = html.replace(/<\/body>/i, `${runtime}</body>`);
  } else {
    html += runtime;
  }

  fs.writeFileSync(abs, html);
  console.log(`Injected global language runtime: ${rel}`);
}

if (process.exitCode) process.exit(process.exitCode);
