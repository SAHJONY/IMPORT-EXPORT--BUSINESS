-- 20260917_envios_intakes.sql
-- Server-side persistence for the SAHJONY Envios (Houston → Cuba) quote intake.
-- Idempotent: safe to run multiple times.
-- Business separation: this table belongs ONLY to the import/export business
-- (Envios Houston → Cuba). Leads are never cross-filed with other businesses.

create table if not exists envios_intakes (
  id bigserial primary key,
  reference text not null unique,                 -- ENV-2026-XXXXXX
  full_name text not null,
  whatsapp text not null,
  cargo_type text not null,                      -- contenedor_fcl | pallet_consolidado
  origin_detail text not null,                   -- Houston pickup address OR drop-off point
  origin_mode text not null default 'pickup',    -- pickup | dropoff
  cuba_province text not null,
  cuba_city text not null,
  container_size text,                           -- '20' | '40' (FCL branch)
  goods_description text not null,
  pieces integer,                                -- pallet branch
  weight_kg double precision,                   -- pallet branch
  dimensions_cm text,                            -- pallet branch
  notes text,
  preferred_language text not null default 'es',
  status text not null default 'REQUESTED',      -- REQUESTED → QUOTED → ...
  first_touch jsonb,                             -- utm_* / referrer captured client-side only
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_envios_intakes_reference on envios_intakes (reference);
create index if not exists idx_envios_intakes_created on envios_intakes (created_at desc);
create index if not exists idx_envios_intakes_status on envios_intakes (status);
