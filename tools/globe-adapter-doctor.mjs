import fs from 'node:fs';

const file='src/spatial/globeAdapter.ts';
if(!fs.existsSync(file))throw new Error('GLOBE_ADAPTER_MISSING');
const source=fs.readFileSync(file,'utf8');
const required=[
  "GlobeProviderId='reference'|'cesium-ion'|'google-photorealistic'",
  "commercialPolicy:'internal-safe'|'provider-terms-required'",
  "browserCredential:'none'|'public-restricted-token'",
  "VITE_SAHJONY_GLOBE_PROVIDER",
  "Commercial-safe zero-key fallback active.",
  "Provider selected but no browser-restricted public token is configured."
];
for(const marker of required)if(!source.includes(marker))throw new Error(`GLOBE_ADAPTER_CONTRACT_MISSING:${marker}`);
if(source.includes('SECRET')||source.includes('PRIVATE_KEY'))throw new Error('GLOBE_ADAPTER_SECRET_PATTERN_DETECTED');
console.log('GLOBE_ADAPTER_OK');
