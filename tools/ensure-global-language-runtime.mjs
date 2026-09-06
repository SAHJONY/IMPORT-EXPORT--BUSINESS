import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const targets = [
  'public/owner-cuba-mipymes.html',
  'public/agency-command-center.html',
];
const runtimePattern = /src=["']\/global-language\.js["']/i;
const runtimeTag = '<script src="/global-language.js" defer></script>';

for (const rel of targets) {
  const abs = path.join(root, rel);
  if (!fs.existsSync(abs)) {
    console.error(`Missing target for language runtime repair: ${rel}`);
    process.exitCode = 1;
    continue;
  }

  let html = fs.readFileSync(abs, 'utf8');
  if (!runtimePattern.test(html)) {
    if (/<\/body>/i.test(html)) {
      html = html.replace(/<\/body>/i, `${runtimeTag}</body>`);
    } else {
      html += runtimeTag;
    }
    fs.writeFileSync(abs, html);
    console.log(`Injected global language runtime: ${rel}`);
  } else {
    console.log(`Global language runtime already present: ${rel}`);
  }

  const verified = fs.readFileSync(abs, 'utf8');
  if (!runtimePattern.test(verified)) {
    console.error(`Failed to persist global language runtime: ${rel}`);
    process.exitCode = 1;
  } else {
    console.log(`Verified global language runtime: ${rel}`);
  }
}

if (process.exitCode) process.exit(process.exitCode);
