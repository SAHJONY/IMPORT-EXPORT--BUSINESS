import fs from 'node:fs';

const files={
  main:fs.readFileSync('src/main.tsx','utf8'),
  center:fs.readFileSync('src/GlobalOperationsCenter.tsx','utf8'),
  registry:fs.readFileSync('src/spatial/globalOperations.ts','utf8'),
};
const failures=[];
const requireText=(file,text,label)=>{if(!files[file].includes(text))failures.push(label)};
requireText('main','/owner/global-operations','global operations route missing');
requireText('center','REFERENCE ≠ LIVE BUSINESS DATA','truth-state warning missing');
requireText('center','Third-party God’s Eye datasets and models are not bundled here','commercial data policy missing');
requireText('registry',"evidence:'reference'",'reference evidence state missing');
requireText('registry','Reference geography only','reference-data disclaimer missing');
const banned=['telegeography_submarine_cables','public/models/'];
for(const token of banned){if(files.center.includes(token)||files.registry.includes(token))failures.push(`restricted asset reference present: ${token}`)}
if(failures.length){console.error('SPATIAL_INTELLIGENCE_DOCTOR_FAILED');for(const x of failures)console.error(`- ${x}`);process.exit(1)}
console.log('SPATIAL_INTELLIGENCE_DOCTOR_OK');
