import type { SupabaseClient } from '@supabase/supabase-js';

export type SofiaInteractionKind = 'new_outreach' | 'followup' | 'inbound_reply';

export type SofiaCommercialGateInput = {
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
  interaction_kind: SofiaInteractionKind;
  match_count: number;
  ambiguous: boolean;
  allow: boolean;
  fail_closed: boolean;
  matches: SofiaCommercialGateMatch[];
};

const FOLLOWUP_MIN_HOURS = 168;

function validEmail(value: string | undefined): boolean {
  if (!value) return false;
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

function normalizeIso(value: string | null | undefined): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return null;
  return parsed.toISOString();
}

/**
 * Mandatory fail-closed preflight before any Sofia commercial email send.
 *
 * IMPORTANT:
 * - `gmailLatestOutboundAt` must be read from Gmail for the actual recipient/thread.
 *   CRM timestamps are not an acceptable substitute for follow-up cooldown evidence.
 * - The caller must have already read the full relevant Gmail thread.
 * - This gate never creates qualified demand or an RFQ.
 * - Record the outbound in CRM only after Gmail confirms a successful send.
 */
export async function evaluateSofiaCommercialSend(
  supabase: SupabaseClient,
  input: SofiaCommercialGateInput,
): Promise<SofiaCommercialGateDecision> {
  const email = input.email?.trim().toLowerCase();
  const companyName = input.companyName?.trim();

  if (!email && !companyName) {
    throw new Error('SOFIA_GATE_INPUT_REQUIRED');
  }
  if (email && !validEmail(email)) {
    throw new Error('SOFIA_GATE_INVALID_EMAIL');
  }
  if (!input.gmailThreadRead) {
    throw new Error('SOFIA_GATE_FULL_THREAD_REQUIRED');
  }

  let latestOutboundAt: string | null = null;
  if (input.interactionKind === 'followup') {
    latestOutboundAt = normalizeIso(input.gmailLatestOutboundAt);
    if (!latestOutboundAt) {
      throw new Error('SOFIA_GATE_GMAIL_TIMESTAMP_REQUIRED');
    }

    const elapsedHours = (Date.now() - new Date(latestOutboundAt).getTime()) / 3_600_000;
    if (elapsedHours < 0 || elapsedHours < FOLLOWUP_MIN_HOURS) {
      return {
        gate_version: 'client-preflight',
        authoritative_source: 'supabase_crm',
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
      email: email || undefined,
      company_name: companyName || undefined,
      interaction_kind: input.interactionKind,
      gmail_thread_read: true,
      genuine_inbound_reply: input.genuineInboundReply === true,
      gmail_latest_outbound_at: latestOutboundAt,
      outbound_timestamp_source: input.interactionKind === 'followup' ? 'gmail' : undefined,
    },
  });

  if (error || !data) {
    throw new Error('SOFIA_GATE_CRM_UNAVAILABLE');
  }

  // The client never widens server authority. Missing, ambiguous, or malformed
  // decisions are denied even if a future backend response changes shape.
  if (
    data.authoritative_source !== 'supabase_crm' ||
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
  if (!decision.allow || decision.fail_closed || decision.ambiguous || decision.match_count !== 1) {
    throw new Error('SOFIA_COMMERCIAL_SEND_BLOCKED');
  }
}
