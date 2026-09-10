import type { SupabaseClient } from '@supabase/supabase-js';

export type SofiaInteractionKind = 'new_outreach' | 'followup' | 'inbound_reply';

export type SofiaCommercialGateInput = {
  requestId: string;
  email?: string;
  companyName?: string;
  interactionKind: SofiaInteractionKind;
  gmailThreadRead: boolean;
  genuineInboundReply?: boolean;
  gmailLatestOutboundAt?: string | null;
};

export type SofiaCommercialGateMatch = {
  record_key: string;
  company_name: string | null;
  public_email: string | null;
  verification_status: string | null;
  registry_status: string | null;
  outreach_status: string | null;
  consent_status: string | null;
  interaction_kind: SofiaInteractionKind;
  gmail_latest_outbound_at: string | null;
  followup_elapsed_hours: number | null;
  allowed: boolean;
  reason_codes: string[];
};

export type SofiaCommercialGateDecision = {
  gate_version: string;
  authoritative_source: 'supabase_crm';
  request_id: string;
  interaction_kind: SofiaInteractionKind;
  match_count: number;
  ambiguous: boolean;
  allow: boolean;
  fail_closed: boolean;
  idempotent?: boolean;
  rules?: Record<string, unknown>;
  matches: SofiaCommercialGateMatch[];
};

export type SofiaCommercialSendEvidence = {
  requestId: string;
  gmailMessageId: string;
  gmailThreadId: string;
  gmailSentAt: string;
};

export type SofiaCommercialSendRecord = {
  gate_version: string;
  recorded: boolean;
  idempotent: boolean;
  request_id: string;
  prospect_record_key?: string;
};

const FOLLOWUP_MIN_HOURS = 168;

function validEmail(value: string | undefined): boolean {
  if (!value) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

function validRequestId(value: string): boolean {
  return /^[A-Za-z0-9._:-]{16,160}$/.test(value);
}

function normalizeIso(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return null;
  return parsed.toISOString();
}

export function createSofiaGateRequestId(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `sofia-${Date.now()}-${Math.random().toString(36).slice(2, 18)}`;
}

/**
 * Mandatory fail-closed preflight before any Sofia commercial email send.
 *
 * A successful ALLOW is only an authorization decision. It is not evidence that
 * Gmail actually sent anything. After Gmail confirms the send, callers MUST invoke
 * recordSofiaCommercialSend with the same requestId and Gmail's real evidence.
 */
export async function evaluateSofiaCommercialSend(
  supabase: SupabaseClient,
  input: SofiaCommercialGateInput,
): Promise<SofiaCommercialGateDecision> {
  const email = input.email?.trim().toLowerCase();
  const companyName = input.companyName?.trim();

  if (!validRequestId(input.requestId)) throw new Error('SOFIA_GATE_VALID_REQUEST_ID_REQUIRED');
  if (!email && !companyName) throw new Error('SOFIA_GATE_INPUT_REQUIRED');
  if (email && !validEmail(email)) throw new Error('SOFIA_GATE_INVALID_EMAIL');
  if (!input.gmailThreadRead) throw new Error('SOFIA_GATE_FULL_THREAD_REQUIRED');

  let latestOutboundAt: string | null = null;
  if (input.interactionKind === 'followup') {
    latestOutboundAt = normalizeIso(input.gmailLatestOutboundAt);
    if (!latestOutboundAt) throw new Error('SOFIA_GATE_GMAIL_TIMESTAMP_REQUIRED');

    const elapsedHours = (Date.now() - new Date(latestOutboundAt).getTime()) / 3_600_000;
    if (elapsedHours < 0 || elapsedHours < FOLLOWUP_MIN_HOURS) {
      return {
        gate_version: 'client-preflight',
        authoritative_source: 'supabase_crm',
        request_id: input.requestId,
        interaction_kind: input.interactionKind,
        match_count: 0,
        ambiguous: false,
        allow: false,
        fail_closed: true,
        matches: [],
      };
    }
  }

  if (input.interactionKind === 'inbound_reply' && !input.genuineInboundReply) {
    throw new Error('SOFIA_GATE_GENUINE_INBOUND_REQUIRED');
  }

  const { data, error } = await supabase.functions.invoke<SofiaCommercialGateDecision>('sofia-crm-gate', {
    body: {
      action: 'evaluate',
      request_id: input.requestId,
      email: email || undefined,
      company_name: companyName || undefined,
      interaction_kind: input.interactionKind,
      gmail_thread_read: true,
      genuine_inbound_reply: input.genuineInboundReply === true,
      gmail_latest_outbound_at: latestOutboundAt,
      outbound_timestamp_source: input.interactionKind === 'followup' ? 'gmail' : undefined,
    },
  });

  if (error || !data) throw new Error('SOFIA_GATE_CRM_UNAVAILABLE');

  if (
    data.gate_version !== '3.0' ||
    data.authoritative_source !== 'supabase_crm' ||
    data.request_id !== input.requestId ||
    data.fail_closed !== false ||
    data.allow !== true ||
    data.ambiguous !== false ||
    data.match_count !== 1
  ) {
    return { ...data, allow: false, fail_closed: true };
  }

  return data;
}

export function assertSofiaCommercialSendAllowed(decision: SofiaCommercialGateDecision): void {
  if (
    decision.gate_version !== '3.0' ||
    !decision.allow ||
    decision.fail_closed ||
    decision.ambiguous ||
    decision.match_count !== 1 ||
    !validRequestId(decision.request_id)
  ) {
    throw new Error('SOFIA_COMMERCIAL_SEND_BLOCKED');
  }
}

/**
 * Call only AFTER Gmail reports a successful send. This binds the approved gate
 * decision to the actual Gmail message and atomically reconciles CRM state.
 */
export async function recordSofiaCommercialSend(
  supabase: SupabaseClient,
  evidence: SofiaCommercialSendEvidence,
): Promise<SofiaCommercialSendRecord> {
  if (!validRequestId(evidence.requestId)) throw new Error('SOFIA_GATE_VALID_REQUEST_ID_REQUIRED');
  if (!evidence.gmailMessageId.trim() || !evidence.gmailThreadId.trim()) {
    throw new Error('SOFIA_GATE_GMAIL_SEND_EVIDENCE_REQUIRED');
  }

  const gmailSentAt = normalizeIso(evidence.gmailSentAt);
  if (!gmailSentAt) throw new Error('SOFIA_GATE_GMAIL_SEND_TIMESTAMP_REQUIRED');

  const { data, error } = await supabase.functions.invoke<SofiaCommercialSendRecord>('sofia-crm-gate', {
    body: {
      action: 'record_send',
      request_id: evidence.requestId,
      gmail_message_id: evidence.gmailMessageId,
      gmail_thread_id: evidence.gmailThreadId,
      gmail_sent_at: gmailSentAt,
    },
  });

  if (error || !data?.recorded || data.gate_version !== '3.0' || data.request_id !== evidence.requestId) {
    throw new Error('SOFIA_GATE_POST_SEND_RECONCILIATION_FAILED');
  }

  return data;
}
