-- SAHJONY Global Trade
-- Migration 004: Communication OS privacy modes, consent, and human WebRTC signaling.
--
-- IMPORTANT:
-- - Explicit migration artifact only. Do not execute from a health endpoint.
-- - Apply to a Neon temporary branch and verify before production promotion.
-- - PRIVATE_HUMAN rooms never authorize AI audio/vision processing.
-- - AI_ASSISTED rooms require explicit participant consent before AI processing.
-- - This schema stores signaling metadata only; it does not store call audio/video.

alter table if exists public.communication_rooms
  add column if not exists privacy_mode text not null default 'AI_ASSISTED';

alter table if exists public.communication_rooms
  add column if not exists ai_enabled boolean not null default true;

alter table if exists public.communication_rooms
  add column if not exists ai_consent_required boolean not null default true;

alter table if exists public.communication_rooms
  add column if not exists human_webrtc_enabled boolean not null default false;

alter table if exists public.communication_rooms
  add column if not exists privacy_notice_version text not null default '2026-08-27-v1';

alter table if exists public.communication_rooms
  drop constraint if exists communication_rooms_privacy_mode_check;

alter table if exists public.communication_rooms
  add constraint communication_rooms_privacy_mode_check
  check (privacy_mode in ('PRIVATE_HUMAN','AI_ASSISTED'));

create table if not exists public.communication_room_consents (
  id bigserial primary key,
  consent_id text not null unique,
  room_id text not null,
  participant_id text not null,
  participant_type text not null check (participant_type in ('owner','employee','customer','lead')),
  ai_audio_consent boolean not null default false,
  ai_vision_consent boolean not null default false,
  notice_version text not null,
  consented_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique(room_id, participant_id)
);

create table if not exists public.communication_room_signals (
  id bigserial primary key,
  signal_id text not null unique,
  room_id text not null,
  sender_participant_id text not null,
  sender_type text not null check (sender_type in ('owner','employee','customer','lead')),
  signal_type text not null check (signal_type in ('offer','answer','ice','hangup')),
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  expires_at timestamptz not null default (now() + interval '15 minutes')
);

create index if not exists idx_room_consents_room_participant
  on public.communication_room_consents(room_id, participant_id);

create index if not exists idx_room_signals_room_time
  on public.communication_room_signals(room_id, created_at asc);

create index if not exists idx_room_signals_expiry
  on public.communication_room_signals(expires_at);

comment on table public.communication_room_consents is
  'Explicit per-participant consent ledger for AI audio/vision processing. PRIVATE_HUMAN rooms never use these grants to enable AI.';

comment on table public.communication_room_signals is
  'Short-lived WebRTC signaling metadata. Media does not traverse or persist in this table.';
