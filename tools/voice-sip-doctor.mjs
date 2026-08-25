import process from 'node:process';

const args = new Map(process.argv.slice(2).map((v) => {
  const i = v.indexOf('=');
  return i > 0 ? [v.slice(0, i), v.slice(i + 1)] : [v, 'true'];
}));
const base = (args.get('--url') || process.env.BUSINESS_CANONICAL_WEBSITE || process.env.APP_URL || '').replace(/\/$/, '');
const token = args.get('--token') || process.env.OWNER_CONTROL_TOKEN || process.env.OWNER_API_TOKEN || '';
const apply = args.get('--apply') === 'true';

if (!base) throw new Error('Missing --url or BUSINESS_CANONICAL_WEBSITE/APP_URL');
if (!token) throw new Error('Missing --token or OWNER_CONTROL_TOKEN/OWNER_API_TOKEN');

const headers = { authorization: `Bearer ${token}`, 'content-type': 'application/json', 'user-agent': 'SAHJONY-Voice-SIP-Doctor/1.0' };
const getJson = async (path, init = {}) => {
  const r = await fetch(base + path, { ...init, headers: { ...headers, ...(init.headers || {}) } });
  const text = await r.text();
  let body; try { body = JSON.parse(text); } catch { body = { raw: text.slice(0, 800) }; }
  return { ok: r.ok, status: r.status, body };
};

const doctor = await getJson('/voice/inbound/doctor');
console.log(JSON.stringify({ step: 'doctor', http_status: doctor.status, result: doctor.body }, null, 2));
if (!doctor.ok || doctor.body?.status === 'blocked') process.exitCode = 1;

if (apply && doctor.ok && doctor.body?.preflight_ok) {
  const configured = await getJson('/voice/inbound/configure', { method: 'POST', body: '{}' });
  console.log(JSON.stringify({ step: 'configure', http_status: configured.status, result: configured.body }, null, 2));
  if (!configured.ok) process.exitCode = 1;
  const status = await getJson('/voice/inbound/status');
  console.log(JSON.stringify({ step: 'verify', http_status: status.status, result: status.body }, null, 2));
  if (!status.ok || status.body?.sip_verified !== true) process.exitCode = 1;
}
