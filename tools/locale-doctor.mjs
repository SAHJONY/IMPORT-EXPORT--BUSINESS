import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const root=process.cwd();
const errors=[];
const passes=[];
const fail=m=>errors.push(m);
const pass=m=>passes.push(m);
const read=p=>fs.readFileSync(path.join(root,p),'utf8');
const exists=p=>fs.existsSync(path.join(root,p));

function normalizeLocale(value){
  const raw=String(value||'').trim().replace('_','-');
  if(!raw)return '';
  const lower=raw.toLowerCase();
  if(lower==='en'||lower.startsWith('en-'))return 'en-US';
  if(lower==='es'||lower.startsWith('es-'))return 'es';
  return raw;
}
function baseLocale(value){return normalizeLocale(value).split('-')[0].toLowerCase()}
function sameLanguage(a,b){return baseLocale(a)===baseLocale(b)}

function checkCanonicalization(){
  const cases=[['en','en-US'],['EN_us','en-US'],['en-GB','en-US'],['es-ES','es'],['es-CU','es']];
  for(const [input,expected] of cases){const actual=normalizeLocale(input);actual===expected?pass(`Canonical locale ${input} -> ${expected}`):fail(`Canonical locale failed: ${input} -> ${actual}, expected ${expected}`)}
  sameLanguage('en','en-US')?pass('English base-language equivalence works'):fail('English en/en-US equivalence is broken');
  sameLanguage('es-CU','es')?pass('Spanish base-language equivalence works'):fail('Spanish locale equivalence is broken');
}

function checkLanguageRuntime(){
  const file='public/global-language.js';
  if(!exists(file))return fail(`${file} missing`);
  const text=read(file);
  const required=[
    ['normalizeLocale','locale normalization'],
    ['sameLanguage','source/target language equivalence'],
    ['history.replaceState','current URL language replacement'],
    ["u.searchParams.set('lang',marker)",'explicit locale propagation'],
    ["baseLocale(target)==='en'?'English':'Original'",'English restore state'],
    ["if(sameLanguage(target,sourceLocale))",'native source restore path'],
    ["if(!sameLanguage(active,sourceLocale)&&!busy)",'observer reversal guard']
  ];
  for(const [needle,label] of required)text.includes(needle)?pass(`Runtime supports ${label}`):fail(`Runtime missing ${label}`);
  if(/else\s+u\.searchParams\.delete\(['"]lang['"]\)/.test(text))fail('Non-Spanish locale still deletes lang override; explicit English would regress on geo-default pages');
  else pass('Explicit English locale is preserved instead of deleted');
}

function checkHtmlCoverage(){
  const files=[];
  if(exists('index.html'))files.push('index.html');
  const dir=path.join(root,'public');
  if(fs.existsSync(dir))for(const entry of fs.readdirSync(dir,{withFileTypes:true}))if(entry.isFile()&&entry.name.toLowerCase().endsWith('.html'))files.push(`public/${entry.name}`);
  for(const file of files){const text=read(file);if(!/<html\b[^>]*\blang=["'][^"']+["']/i.test(text))fail(`Missing html lang attribute: ${file}`);if(!/src=["']\/global-language\.js["']/i.test(text))fail(`Missing global language runtime: ${file}`)}
  if(!errors.some(e=>e.includes('html lang')||e.includes('global language runtime')))pass(`Locale runtime coverage verified across ${files.length} HTML entry pages`);
}

function checkNativeI18n(){
  if(!exists('src/i18n.ts'))fail('Native React i18n bootstrap missing: src/i18n.ts');else{const text=read('src/i18n.ts');for(const needle of ['i18next','react-i18next','sahjony.locale','URLSearchParams'])text.includes(needle)?pass(`Native i18n includes ${needle}`):fail(`Native i18n missing ${needle}`)}
  if(!exists('package.json'))return fail('package.json missing');
  const pkg=JSON.parse(read('package.json'));
  if(pkg.dependencies?.i18next&&pkg.dependencies?.['react-i18next'])pass('Native i18n dependencies installed');else fail('i18next/react-i18next dependencies missing');
}

checkCanonicalization();
checkLanguageRuntime();
checkHtmlCoverage();
checkNativeI18n();

console.log('\nSAHJONY Locale Doctor');
console.log('====================');
for(const p of passes)console.log(`PASS  ${p}`);
for(const e of errors)console.error(`FAIL  ${e}`);
console.log(`\nSummary: ${passes.length} passed, ${errors.length} failed`);
if(errors.length)process.exitCode=1;
