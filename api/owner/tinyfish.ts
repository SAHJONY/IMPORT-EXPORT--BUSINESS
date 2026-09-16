const TINYFISH_BASE='https://agent.tinyfish.ai/v1/automation/run-async';
const CONSEQUENTIAL=/\b(pay|purchase|buy|transfer|wire|sign|contract|delete|remove account|change owner|permission|publish|send message|submit order|checkout|book|cancel|approve|accept terms)\b/i;

function send(res:any,status:number,body:any){res.status(status).setHeader('cache-control','no-store').json(body)}
function bearer(req:any){const raw=String(req.headers?.authorization||'');return raw.startsWith('Bearer ')?raw.slice(7):''}
function configured(name:string){return Boolean(process.env[name]?.trim())}
function safeError(status:number){return status===401?'provider_unauthorized':status===402?'provider_funding_required':status===429?'provider_rate_limited':'provider_request_failed'}

export default async function handler(req:any,res:any){
  if(req.method==='GET'){
    const tinyfish=configured('TINYFISH_API_KEY');
    const owner=configured('OWNER_CONTROL_TOKEN');
    return send(res,200,{service:'tinyfish-governed-gateway',status:tinyfish&&owner?'ready':'configuration_required',ready:tinyfish&&owner,tinyfish_ready:tinyfish,owner_gate_ready:owner,fail_closed:true,direct_client_secret_exposure:false,endpoint_mode:'async'});
  }
  if(req.method!=='POST')return send(res,405,{error:'method_not_allowed'});
  if(!configured('OWNER_CONTROL_TOKEN'))return send(res,503,{error:'owner_gate_not_configured',fail_closed:true});
  if(bearer(req)!==process.env.OWNER_CONTROL_TOKEN)return send(res,401,{error:'unauthorized'});
  if(!configured('TINYFISH_API_KEY'))return send(res,503,{error:'tinyfish_not_configured',fail_closed:true});

  const body=req.body&&typeof req.body==='object'?req.body:{};
  const url=String(body.url||'').trim();
  const goal=String(body.goal||'').trim();
  const risk=String(body.risk_level||'low').toLowerCase();
  const approval=String(body.approval_state||'not_required').toLowerCase();
  const budgetCents=Math.max(0,Math.min(Number(body.budget_cents||100),100000));
  const maxSteps=Math.max(1,Math.min(Number(body.max_steps||80),500));
  if(!/^https:\/\//i.test(url))return send(res,400,{error:'https_target_required'});
  if(goal.length<8||goal.length>4000)return send(res,400,{error:'invalid_goal'});
  const consequential=CONSEQUENTIAL.test(goal)||['high','critical'].includes(risk);
  if(consequential&&approval!=='approved')return send(res,409,{error:'owner_approval_required',state:'requires_approval',risk_level:risk,fail_closed:true});
  if(risk==='critical')return send(res,409,{error:'critical_browser_action_blocked',state:'requires_approval',fail_closed:true});

  const payload:any={url,goal,browser_profile:body.browser_profile==='stealth'?'stealth':'lite',agent_config:{mode:'strict',max_steps:maxSteps},capture_config:{elements:true,snapshots:true,screenshots:true,recording:false,html:false}};
  if(typeof body.webhook_url==='string'&&/^https:\/\//i.test(body.webhook_url))payload.webhook_url=body.webhook_url;
  if(body.use_profile===true)payload.use_profile=true;
  if(typeof body.profile_id==='string'&&body.profile_id)payload.profile_id=body.profile_id;
  if(body.use_vault===true)payload.use_vault=true;
  if(Array.isArray(body.credential_item_ids)&&body.credential_item_ids.length)payload.credential_item_ids=body.credential_item_ids.slice(0,20);

  try{
    const response=await fetch(TINYFISH_BASE,{method:'POST',headers:{'content-type':'application/json','x-api-key':String(process.env.TINYFISH_API_KEY)},body:JSON.stringify(payload)});
    const text=await response.text();let data:any={};try{data=text?JSON.parse(text):{}}catch{}
    if(!response.ok)return send(res,502,{error:safeError(response.status),provider_status:response.status,fail_closed:true});
    return send(res,202,{state:'in_progress',provider:'tinyfish',run_id:data.run_id||data.id||null,budget_cents:budgetCents,max_steps:maxSteps,approval_state:approval,risk_level:risk,evidence_capture:true});
  }catch(error){return send(res,502,{error:'tinyfish_unreachable',fail_closed:true});}
}
