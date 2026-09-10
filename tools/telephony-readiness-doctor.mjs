import tls from 'node:tls';
import process from 'node:process';

const args = new Map(process.argv.slice(2).map((v) => {
  const i = v.indexOf('=');
  return i > 0 ? [v.slice(0, i), v.slice(i + 1)] : [v, 'true'];
}));

const gateway = args.get('--gateway') || 'https://sahjony-sofia-realtime-voice.vercel.app/api/realtime-sip';
const did = args.get('--did') || '+12815490295';
const appName = args.get('--app') || 'SAHJONY OpenAI Realtime TeXML';
const mediaName = args.get('--media') || 'SAHJONYOpenAIRealtime.xml';
const sipUser = args.get('--sip-user') || 'proj_wo5NVFLZGfkoDpPyGghDAzuw';
const sipHost = args.get('--sip-host') || 'sip.api.openai.com';
const fallback = args.get('--fallback') || '+13465346545';
const telnyxKey = process.env.TELNYX_API_KEY || '';
const report = { checked_at: new Date().toISOString(), did, appName, fallback, checks: {} };

const jsonFetch = async (url, init = {}) => {
  const r = await fetch(url, init);
  const text = await r.text();
  let body; try { body = JSON.parse(text); } catch { body = text; }
  return { ok: r.ok, status: r.status, body };
};

try {
  const h = await jsonFetch(gateway);
  report.checks.openai_gateway = {
    ok: h.ok && h.body?.ok === true,
    http_status: h.status,
    service: h.body?.service || null,
    model: h.body?.model || null,
    voice: h.body?.voice || null,
  };
} catch (e) {
  report.checks.openai_gateway = { ok: false, error: e.message };
}

report.checks.openai_sip_tls = await new Promise((resolve) => {
  const socket = tls.connect({ host: sipHost, port: 5061, servername: sipHost, timeout: 7000 }, () => {
    resolve({ ok: socket.authorized, authorized: socket.authorized, protocol: socket.getProtocol() });
    socket.end();
  });
  socket.on('timeout', () => { resolve({ ok: false, error: 'timeout' }); socket.destroy(); });
  socket.on('error', (e) => resolve({ ok: false, error: e.message }));
});

if (telnyxKey) {
  const auth = { authorization: `Bearer ${telnyxKey}` };
  try {
    const apps = await jsonFetch(`https://api.telnyx.com/v2/texml_applications?filter[friendly_name]=${encodeURIComponent(appName)}`, { headers: auth });
    const app = Array.isArray(apps.body?.data) ? apps.body.data[0] : null;
    report.checks.telnyx_texml_app = { ok: !!app?.id, id: app?.id || null, active: app?.active ?? null, voice_url: app?.voice_url || null };
  } catch (e) { report.checks.telnyx_texml_app = { ok: false, error: e.message }; }

  try {
    const media = await fetch(`https://api.telnyx.com/v2/media/${encodeURIComponent(mediaName)}/download`, { headers: auth });
    const xml = await media.text();
    const expected = `sip:${sipUser}@${sipHost};transport=tls`;
    report.checks.telnyx_texml_bin = { ok: media.ok && xml.includes(expected), http_status: media.status, target_present: xml.includes(expected) };
  } catch (e) { report.checks.telnyx_texml_bin = { ok: false, error: e.message }; }
} else {
  report.checks.telnyx_api = { ok: null, status: 'not_checked', reason: 'TELNYX_API_KEY not configured' };
}

try {
  const pub = await fetch(`https://api.telnyx.com/v2/media/${encodeURIComponent(mediaName)}`);
  report.checks.public_media_url = {
    ok: pub.ok,
    http_status: pub.status,
    classification: pub.status === 401 ? 'private_telnyx_media_expected' : (pub.ok ? 'public' : 'unexpected'),
  };
} catch (e) { report.checks.public_media_url = { ok: false, error: e.message }; }

report.checks.fallback = { ok: true, number: fallback, mode: 'known_good_production_route_until_native_e2e_passes' };
const hard = ['openai_gateway', 'openai_sip_tls'];
const hardOk = hard.every((k) => report.checks[k]?.ok === true);
const telnyxVerified = telnyxKey ? (report.checks.telnyx_texml_app?.ok && report.checks.telnyx_texml_bin?.ok) : false;
report.native_route = {
  status: hardOk && telnyxVerified ? 'CONFIG_VERIFIED_NEEDS_REAL_PSTN_TEST' : 'NOT_READY',
  hard_checks_ok: hardOk,
  telnyx_config_verified: telnyxVerified,
  real_pstn_test_required: true,
};
console.log(JSON.stringify(report, null, 2));
if (report.native_route.status === 'NOT_READY') process.exitCode = 2;
