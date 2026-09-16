import fs from 'node:fs';

const required=['api/owner/tinyfish.ts','src/TinyFishControlPlane.tsx','supabase/migrations/20260910_tinyfish_browser_control_plane.sql'];
const fail=[];
for(const file of required)if(!fs.existsSync(file))fail.push(`missing:${file}`);
if(fs.existsSync('api/owner/tinyfish.ts')){
 const api=fs.readFileSync('api/owner/tinyfish.ts','utf8');
 for(const marker of ['TINYFISH_API_KEY','OWNER_CONTROL_TOKEN','fail_closed:true','capture_config','critical_browser_action_blocked'])if(!api.includes(marker))fail.push(`gateway_marker:${marker}`);
 if(api.includes('VITE_TINYFISH'))fail.push('client_exposed_tinyfish_secret');
}
if(fs.existsSync('src/TinyFishControlPlane.tsx')){
 const ui=fs.readFileSync('src/TinyFishControlPlane.tsx','utf8');
 if(ui.includes('TINYFISH_API_KEY='))fail.push('secret_literal_in_ui');
 if(!ui.includes('/api/owner/tinyfish'))fail.push('ui_missing_gateway_health');
}
if(fs.existsSync('src/main.tsx')){
 const main=fs.readFileSync('src/main.tsx','utf8');
 if(!main.includes('/owner/tinyfish'))fail.push('route_missing:/owner/tinyfish');
}
if(fail.length){console.error('TINYFISH_CONTROL_PLANE_FAIL',fail.join(','));process.exit(1)}
console.log('TINYFISH_CONTROL_PLANE_OK');
