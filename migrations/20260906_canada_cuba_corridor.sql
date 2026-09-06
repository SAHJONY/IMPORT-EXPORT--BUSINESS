create table if not exists logistics_canada_cuba_corridors (
  corridor_id text primary key,
  agency_id text not null,
  origin_city text not null, origin_province text not null, destination_province_cuba text not null,
  transport_mode text not null, cargo_type text not null, currency text not null,
  declared_value numeric, country_of_origin text, hs_code text,
  export_reporting_status text not null, permit_status text not null, carrier_choice text not null,
  booking_ready boolean not null default false, status text not null,
  created_at timestamptz not null, updated_at timestamptz not null
);
create index if not exists idx_canada_cuba_agency on logistics_canada_cuba_corridors(agency_id, created_at desc);
