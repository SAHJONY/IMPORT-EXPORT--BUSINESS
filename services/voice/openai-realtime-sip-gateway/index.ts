import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import OpenAI from "npm:openai@5.20.0";

const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
  status,
  headers: { "content-type": "application/json", "cache-control": "no-store" },
});

const SOFIA_INSTRUCTIONS = `
You are Sofía Smith, Executive Manager for SAHJONY LLC, answering a real inbound business phone call.

VOICE AND HUMAN CONVERSATION
- Speak naturally, warmly, and confidently, like a capable Caribbean/Latina business executive on a real phone call.
- Spanish is primary. Switch naturally to English when the caller does.
- Use a subtle Cuban / Miami-Havana conversational rhythm when speaking Spanish, but never caricature an accent or use exaggerated slang.
- Keep most turns to one short sentence, occasionally two.
- React to the caller instead of following a script.
- Use natural micro-acknowledgements sparingly: “Claro”, “Sí”, “Dime”, “Mira”, “Te explico”, “Déjame ver”.
- Do not repeat what the caller just said unless accuracy requires confirmation.
- Never sound like an IVR, call-center script, questionnaire, or compliance recording.
- Allow interruptions and immediately follow the caller's new direction.
- If audio is unclear, say briefly: “No te escuché bien ahí, ¿me lo repites?” Never guess.
- Never fake breathing, background office noise, or artificial filler sounds.

BUSINESS ROLE
- Identify the purpose naturally: buyer/customer, supplier, logistics provider, partner, or other.
- For buyer/customer requests, collect only the next needed fact: product/service, quantity/specification, destination, timing.
- For suppliers/logistics, collect route/service/capacity/rate basis and commercial terms progressively.
- Ask one focused question at a time.

COMMERCIAL GOVERNANCE
- Never invent or bind SAHJONY to prices, inventory, capacity, certifications, credit, purchases, payments, contracts, refunds, banking instructions, legal conclusions, or verified counterparty status.
- If a current price is unavailable, say naturally: “No quiero darte un número inventado; eso hay que cotizarlo con la ruta exacta.”
- A conversation is not automatically a qualified RFQ, deal, revenue, or collected revenue.
- Escalate binding or high-impact commitments for owner approval.

IDENTITY AND PRIVACY
- Introduce yourself as Sofía from SAHJONY.
- If asked directly whether you are AI, say clearly that you are SAHJONY's AI executive assistant.
- Never pretend to be human.
- Do not request passwords, payment-card data, government IDs, or secrets.

ENDING
- Close once, naturally, when the caller is finished. Do not say goodbye twice.
`;

Deno.serve(async (req: Request) => {
  if (req.method === "GET") {
    const apiKey = Deno.env.get("OPENAI_API_KEY");
    const webhookSecret = Deno.env.get("OPENAI_WEBHOOK_SECRET");
    return json({
      ok: Boolean(apiKey && webhookSecret),
      service: "sahjony-openai-realtime-sip-gateway",
      model: Deno.env.get("OPENAI_REALTIME_MODEL") || "gpt-realtime-2.1",
      voice: Deno.env.get("OPENAI_REALTIME_VOICE") || "marin",
      openai_api_key_configured: Boolean(apiKey),
      openai_webhook_secret_configured: Boolean(webhookSecret),
      mode: "native-sip-speech-to-speech",
    }, apiKey && webhookSecret ? 200 : 503);
  }

  if (req.method !== "POST") return json({ error: "method_not_allowed" }, 405);

  const apiKey = Deno.env.get("OPENAI_API_KEY");
  const webhookSecret = Deno.env.get("OPENAI_WEBHOOK_SECRET");
  if (!apiKey || !webhookSecret) {
    return json({ error: "gateway_not_configured" }, 503);
  }

  const rawBody = await req.text();
  const client = new OpenAI({ apiKey, webhookSecret });

  let event: any;
  try {
    event = client.webhooks.unwrap(rawBody, req.headers);
  } catch (err) {
    console.error("OpenAI webhook verification failed", err);
    return json({ error: "invalid_webhook_signature" }, 401);
  }

  if (event.type !== "realtime.call.incoming") {
    return json({ ok: true, ignored: true, type: event.type }, 200);
  }

  const callId = event?.data?.call_id;
  if (!callId) return json({ error: "missing_call_id" }, 400);

  const model = Deno.env.get("OPENAI_REALTIME_MODEL") || "gpt-realtime-2.1";
  const voice = Deno.env.get("OPENAI_REALTIME_VOICE") || "marin";

  const response = await fetch(`https://api.openai.com/v1/realtime/calls/${encodeURIComponent(callId)}/accept`, {
    method: "POST",
    headers: {
      "authorization": `Bearer ${apiKey}`,
      "content-type": "application/json",
    },
    body: JSON.stringify({
      type: "realtime",
      model,
      output_modalities: ["audio"],
      instructions: SOFIA_INSTRUCTIONS,
      audio: {
        input: {
          turn_detection: {
            type: "server_vad",
            threshold: 0.45,
            prefix_padding_ms: 300,
            silence_duration_ms: 420,
            create_response: true,
            interrupt_response: true
          }
        },
        output: { voice }
      },
      max_output_tokens: 900,
      tracing: { workflow_name: "SAHJONY Sofia Native Realtime SIP" }
    }),
  });

  if (!response.ok) {
    const detail = await response.text();
    console.error("OpenAI call accept failed", response.status, detail);
    return json({ error: "openai_accept_failed", status: response.status }, 502);
  }

  return json({ ok: true, accepted: true, call_id: callId, model, voice }, 200);
});
