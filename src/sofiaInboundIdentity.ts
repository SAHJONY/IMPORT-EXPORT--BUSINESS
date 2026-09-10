import type { SupabaseClient } from '@supabase/supabase-js';

export type SofiaInboundIdentityInput = {
  email: string;
  companyName: string;
  contactName?: string;
  contactPhone?: string;
  sourceMessageId: string;
  sourceThreadId: string;
  sourceReceivedAt: string;
  sourceMailbox?: string;
};

export type SofiaInboundIdentityResult = {
  status: 'transactional_identity_created' | 'existing_identity';
  created: boolean;
  record_key: string;
  registry_status?: string | null;
  verification_status?: string | null;
  outreach_status?: string | null;
  consent_status?: string | null;
  qualified_demand?: boolean;
  trade_rfq_created?: boolean;
  fail_closed_for_new_outreach?: boolean;
};

const SOFIA_MAILBOX = 'sofiaexecutivemanager@gmail.com';

function validEmail(value: string): boolean {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value.trim());
}

function validTimestamp(value: string): boolean {
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime());
}

/**
 * Creates or resolves the minimum CRM identity required to reply to a genuine
 * inbound Gmail message. This function MUST NOT create qualified demand, an RFQ,
 * marketing consent, KYB completion, or binding authority.
 */
export async function resolveSofiaInboundIdentity(
  supabase: SupabaseClient,
  input: SofiaInboundIdentityInput,
): Promise<SofiaInboundIdentityResult> {
  const email = input.email.trim().toLowerCase();
  const companyName = input.companyName.trim();
  const sourceMailbox = (input.sourceMailbox || SOFIA_MAILBOX).trim().toLowerCase();

  if (!validEmail(email)) throw new Error('SOFIA_INBOUND_VALID_EMAIL_REQUIRED');
  if (!companyName) throw new Error('SOFIA_INBOUND_COMPANY_REQUIRED');
  if (!input.sourceMessageId.trim() || !input.sourceThreadId.trim()) {
    throw new Error('SOFIA_INBOUND_GMAIL_EVIDENCE_REQUIRED');
  }
  if (!validTimestamp(input.sourceReceivedAt)) {
    throw new Error('SOFIA_INBOUND_VALID_TIMESTAMP_REQUIRED');
  }
  if (sourceMailbox !== SOFIA_MAILBOX) {
    throw new Error('SOFIA_INBOUND_SOURCE_MAILBOX_INVALID');
  }

  const { data, error } = await supabase.functions.invoke<SofiaInboundIdentityResult>(
    'sofia-inbound-identity',
    {
      body: {
        email,
        company_name: companyName,
        contact_name: input.contactName?.trim() || undefined,
        contact_phone: input.contactPhone?.trim() || undefined,
        source_message_id: input.sourceMessageId.trim(),
        source_thread_id: input.sourceThreadId.trim(),
        source_received_at: new Date(input.sourceReceivedAt).toISOString(),
        source_mailbox: sourceMailbox,
        genuine_inbound_reply: true,
      },
    },
  );

  if (error || !data?.record_key) throw new Error('SOFIA_INBOUND_IDENTITY_RESOLUTION_FAILED');

  // The resolver may create only transactional-only state. Existing identities
  // may already be more mature, but a newly created record must never be promoted.
  if (
    data.created &&
    (
      data.registry_status !== 'CONTACTABLE' ||
      data.verification_status !== 'INBOUND_UNVERIFIED' ||
      data.outreach_status !== 'INBOUND_TRANSACTIONAL_ONLY' ||
      data.consent_status !== 'TRANSACTIONAL_INBOUND_ONLY' ||
      data.qualified_demand === true ||
      data.trade_rfq_created === true ||
      data.fail_closed_for_new_outreach !== true
    )
  ) {
    throw new Error('SOFIA_INBOUND_UNSAFE_IDENTITY_STATE');
  }

  return data;
}
