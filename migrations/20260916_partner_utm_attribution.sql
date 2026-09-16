-- 20260916_partner_utm_attribution.sql
-- Adds first-touch attribution columns to cuba_partner_accounts so the
-- /partners submit path can persist UTM params captured client-side,
-- mirroring the /start path. Idempotent: safe to run multiple times.
-- All columns are nullable; existing rows keep NULL attribution.

alter table cuba_partner_accounts add column if not exists utm_source text;
alter table cuba_partner_accounts add column if not exists utm_medium text;
alter table cuba_partner_accounts add column if not exists utm_campaign text;
alter table cuba_partner_accounts add column if not exists referrer text;
alter table cuba_partner_accounts add column if not exists first_touch_source text;
