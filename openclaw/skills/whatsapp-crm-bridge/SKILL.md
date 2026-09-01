# SAHJONY WhatsApp CRM Bridge

## Purpose
Use the authorized SAHJONY application bridge to read and update CRM context from the Hostinger/OpenClaw WhatsApp runtime without asking customers for administrative credentials and without bypassing authentication or authorization controls.

The CRM bridge is an internal server-to-server tool. It uses the same retained `OPENCLAW_APP_BRIDGE_SECRET` / `SAHJONY_APP_BRIDGE_SECRET` trust relationship already used by the authorized OpenClaw application bridge. The secret must never be printed, sent in chat, stored in CRM records, or exposed to a customer.

## Operator tool
Canonical host command:

```bash
/usr/local/sbin/sahjony-crm-bridge
```

Repository source:

`openclaw/hostinger-24x7/sahjony-crm-bridge.py`

The tool discovers the already-authorized bridge secret from the host or retained OpenClaw container, signs every CRM request with HMAC, binds the signature to HTTP method + path + body hash + timestamp + nonce, and never logs the secret.

## Required behavior on every WhatsApp lead
Before making a CRM-dependent statement:

1. Synchronize the contact when new identifying or commercial information arrives.
2. Load the contact's current CRM context before asking for information that may already be known.
3. Record useful internal notes and follow-up actions when appropriate.
4. Create a trade intake only when the customer has actually supplied a product/service requirement and destination. Do not invent missing commercial facts.
5. Continue the conversation naturally even if the remote CRM is temporarily unavailable. The local bridge may durably queue safe CRM mutations for later replay.

Do **not** tell a customer that they must provide "administrative authorization" to connect the CRM. Administrative/service authorization is an internal infrastructure concern. If the authorized bridge itself is unavailable, do not expose internal auth errors. Continue helping with the conversation and rely on the bridge's local deferred queue for permitted CRM writes.

## Commands
Health:

```bash
/usr/local/sbin/sahjony-crm-bridge health
```

Load contact 360 by phone:

```bash
/usr/local/sbin/sahjony-crm-bridge contact +12816628581
```

Synchronize a WhatsApp lead. Use stdin when text contains quotes or non-ASCII characters:

```bash
printf '%s' '{"phone":"+12816628581","contact_name":"Example","latest_message":"Necesito una cotización de aceite"}' \
  | /usr/local/sbin/sahjony-crm-bridge sync --json -
```

Record an internal CRM note:

```bash
printf '%s' '{"phone":"+12816628581","summary":"Customer requested a follow-up quote","note_type":"follow_up","action_required":true,"action_label":"Prepare quote"}' \
  | /usr/local/sbin/sahjony-crm-bridge note --json -
```

Create a trade intake only from facts the customer supplied:

```bash
printf '%s' '{"phone":"+12816628581","product_need":"Refined cooking oil","destination_country":"CU","quantity":1,"currency":"USD","notes":"Customer requested container pricing"}' \
  | /usr/local/sbin/sahjony-crm-bridge intake --json -
```

Flush any locally deferred writes:

```bash
/usr/local/sbin/sahjony-crm-bridge flush
```

Run self-diagnosis + queue replay:

```bash
/usr/local/sbin/sahjony-crm-bridge doctor
```

## Result semantics
- `synced` — lead/contact synchronization is committed to the CRM.
- `recorded` — internal note is committed.
- `created` — trade intake is committed.
- `duplicate` — the same idempotent operation was already committed; treat as success.
- `deferred` — the safe mutation is stored in the local protected queue and will be replayed. Do not claim the remote CRM commit already happened.
- `degraded` — the CRM bridge or backend needs repair. This does not mean the WhatsApp Linked Device session is down.
- `error` — the requested bridge operation failed and was not confirmed.

## Authorization and scope
Permitted bridge scopes:
- read contact 360 context;
- synchronize WhatsApp leads;
- link/create non-binding CRM prospect records;
- record internal notes and follow-up actions;
- capture a customer-supplied trade requirement as a pending intake.

Not permitted through this bridge:
- delete CRM records;
- modify owner/admin credentials;
- expose authentication secrets;
- approve payments or release funds;
- execute purchases, supplier commitments, contracts, shipments, sanctions/customs clearance, or legal approvals;
- fabricate prices, inventory, delivery commitments, licenses, documents, or customer facts.

Any action that creates an external commercial/legal/financial commitment must remain behind the appropriate SAHJONY owner/compliance workflow.

## Customer-facing conversation rule
CRM mechanics are internal. The customer should receive a useful business response, not infrastructure jargon. Never mention HMAC, API tokens, Supabase service keys, OpenClaw bridge secrets, Vercel, Hostinger credentials, scopes, queue files, or administrative authorization unless the owner is explicitly asking for technical diagnostics.

When the bridge returns `deferred`, it is acceptable to continue the conversation because the local queue preserves the permitted CRM mutation. Do not falsely say "it is already saved in the CRM" until the result is `synced`, `recorded`, `created`, or `duplicate`.

## Recovery
The CRM bridge is a separate failure domain from WhatsApp transport.

- A CRM failure must not trigger WhatsApp re-pairing, QR generation, logout, container recreation, or VPS recovery.
- A WhatsApp transport failure must not cause CRM credentials to be weakened or bypassed.
- The CRM systemd timer should run `doctor` periodically and replay safe pending writes.
- Queue files are local business data and must remain mode `0600` under a mode `0700` state directory.
- Never store passwords, API keys, payment-card details, authentication codes, or other secrets in CRM notes or the deferred queue.

## Acceptance
The CRM integration is ready when all of these are true:
- `/usr/local/sbin/sahjony-crm-bridge health` returns `status=ok`;
- the bridge reports the durable backend reachable;
- a signed contact lookup succeeds;
- a synchronization operation returns `synced` or `duplicate`;
- a repeat of the same operation is idempotent;
- the systemd CRM bridge timer is active;
- local pending queue is empty or drains successfully;
- WhatsApp replies no longer claim that CRM connection requires customer/admin authorization;
- no auth secret is exposed in logs or responses.
