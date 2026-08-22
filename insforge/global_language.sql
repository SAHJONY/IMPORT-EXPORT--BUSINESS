-- SAHJONY Global Trade worldwide language and translation layer
-- Original content is never overwritten. Translations are additive, attributable and reviewable.

create table if not exists language_preferences (
  id bigserial primary key,
  preference_id text unique not null,
  participant_role text not null check (participant_role in ('owner','employee','customer','supplier','buyer','broker','carrier','other')),
  participant_id text not null,
  primary_locale text not null default 'en-US',
  fallback_locale text default 'en-US',
  auto_translate boolean not null default true,
  bilingual_view boolean not null default true,
  translate_messages boolean not null default true,
  translate_documents boolean not null default false,
  translate_notifications boolean not null default true,
  require_human_review_for_legal boolean not null default true,
  timezone text default 'UTC',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(participant_role, participant_id)
);

create table if not exists translations (
  id bigserial primary key,
  translation_id text unique not null,
  source_type text not null,
  source_id text not null,
  field_name text not null,
  source_locale text,
  target_locale text not null,
  source_text text not null,
  translated_text text not null,
  provider text not null,
  provider_model text,
  confidence numeric,
  legal_or_regulatory boolean not null default false,
  human_review_required boolean not null default false,
  human_review_status text not null default 'not_required' check (human_review_status in ('not_required','pending','approved','rejected')),
  reviewed_by_role text,
  reviewed_by_id text,
  reviewed_at timestamptz,
  created_at timestamptz not null default now(),
  unique(source_type, source_id, field_name, target_locale)
);

create index if not exists idx_translations_source on translations(source_type, source_id);
create index if not exists idx_translations_target_locale on translations(target_locale);
create index if not exists idx_language_preferences_participant on language_preferences(participant_role, participant_id);

create table if not exists translation_audit_events (
  id bigserial primary key,
  event_id text unique not null,
  translation_id text,
  actor_role text not null,
  actor_id text not null,
  action text not null,
  detail text,
  created_at timestamptz not null default now()
);

create index if not exists idx_translation_audit_translation on translation_audit_events(translation_id, created_at);
