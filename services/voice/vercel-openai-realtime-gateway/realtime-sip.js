import OpenAI from 'openai';

const MODEL = process.env.OPENAI_REALTIME_MODEL || 'gpt-realtime-2.1';
const VOICE = process.env.OPENAI_REALTIME_VOICE || 'marin';

const SOFIA_INSTRUCTIONS = `You are Sofía Smith, Executive Manager for SAHJONY LLC on a live inbound business call.
Speak naturally, warmly, confidently, and briefly. Spanish is primary; switch naturally to English when the caller does.
Use a subtle Caribbean / Cuban-Miami conversational rhythm without caricature or exaggerated slang.
Keep most turns to one short sentence, occasionally two. Ask one focused question at a time.
React to interruptions immediately. If audio is unclear, say briefly that you did not hear it well and ask for repetition. Never guess.
Never sound like an IVR, call-center script, questionnaire, or compliance recording.
Never invent prices, inventory, capacity, certifications, credit, purchases, payments, contracts, refunds, banking instructions, legal conclusions, or verified counterparty status.
If a current price is unavailable, say naturally that you do not want to invent a number and need the exact route to quote it.
Introduce yourself as Sofía from SAHJONY. If asked directly whether you are AI, say clearly that you are SAHJONY's AI executive assistant.
Never request passwords, card data, government IDs, or secrets. Close once, naturally, when the caller is finished.`;

function send(res, status, body) {
  res.statusCode = status;
  res.setHeader('content-type', 'application/json');
  res.setHeader('cache-control', 'no-store');
  res.end(JSON.stringify(body));
}

async function readRaw(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(Buffer.from(chunk));
  return Buffer.concat(chunks).toString('utf8');
}

export default async function handler(req, res) {
  const apiKey = process.env.OPENAI_API_KEY;
  const secret = process.env.OPENAI_WEBHOOK_SECRET;

  if (req.method === 'GET') {
    return send(res, apiKey && secret ? 200 : 503, {
      ok: Boolean(apiKey && secret),
      service: 'sahjony-sofia-native-openai-realtime-sip',
      model: MODEL,
      voice: VOICE,
      mode: 'native-openai-sip-speech-to-speech',
      external_tts: false,
      ambient_audio: false,
    });
  }

  if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed' });
  if (!apiKey || !secret) return send(res, 503, { error: 'gateway_not_configured' });

  const raw = await readRaw(req);
  const client = new OpenAI({ apiKey, webhookSecret: secret });

  let event;
  try {
    event = await client.webhooks.unwrap(raw, req.headers);
  } catch (error) {
    console.error('OpenAI webhook verification failed', error?.message || error);
    return send(res, 401, { error: 'invalid_webhook_signature' });
  }

  if (event.type !== 'realtime.call.incoming') {
    return send(res, 200, { ok: true, ignored: true, type: event.type });
  }

  const callId = event?.data?.call_id;
  if (!callId) {
    console.info('Verified realtime.call.incoming without call_id; treating as webhook test event');
    return send(res, 200, {
      ok: true,
      verified: true,
      test_event: true,
      type: event.type,
      message: 'Webhook signature verified; no live SIP call_id was supplied.',
    });
  }

  const response = await fetch(`https://api.openai.com/v1/realtime/calls/${encodeURIComponent(callId)}/accept`, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${apiKey}`,
      'content-type': 'application/json',
    },
    body: JSON.stringify({
      type: 'realtime',
      model: MODEL,
      output_modalities: ['audio'],
      instructions: SOFIA_INSTRUCTIONS,
      reasoning: { effort: 'medium' },
      parallel_tool_calls: true,
      audio: {
        input: {
          turn_detection: {
            type: 'server_vad',
            threshold: 0.45,
            prefix_padding_ms: 300,
            silence_duration_ms: 420,
            create_response: true,
            interrupt_response: true,
          },
        },
        output: { voice: VOICE },
      },
      max_output_tokens: 900,
      tracing: { workflow_name: 'SAHJONY Sofia Native Realtime SIP' },
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    console.error('OpenAI Realtime accept failed', response.status, detail.slice(0, 1000));
    return send(res, 502, { error: 'openai_accept_failed', status: response.status });
  }

  return send(res, 200, {
    ok: true,
    accepted: true,
    call_id: callId,
    model: MODEL,
    voice: VOICE,
  });
}
