# VPS fallback — failover runbook

**When to use this:** Vercel is down (e.g. deployments disabled, 402 "Payment required"
on www.sahjony.com / mycubacash.com) and the outage is not resolving within minutes.

**What the fallback is:** a hot standby on the Hostinger VPS (69.62.68.67) serving both
business applications. It syncs from `main` nightly at 04:00 UTC. Public traffic only
arrives here after you flip DNS below.

The live WhatsApp gateway on the same VPS is untouched by all of this (separate ports).

## Failover (about 10 minutes)

1. **Flip DNS** — Vercel dashboard → Domains → DNS records:
   - `sahjony.com` — change the A record(s) to `69.62.68.67`
   - `www.sahjony.com` — change the A record(s) to `69.62.68.67`
   - `mycubacash.com` — change the A record(s) to `69.62.68.67`
   - `www.mycubacash.com` — change the A record(s) to `69.62.68.67`
   - Tip: set TTL to 60 seconds *before* you need this, so propagation takes ~1–2 min.

2. **Issue TLS certificates** — on the VPS (Hostinger web terminal, as root):
   ```bash
   certbot --nginx -d sahjony.com -d www.sahjony.com \
     -d mycubacash.com -d www.mycubacash.com \
     --agree-tos --email <your-email> --non-interactive --redirect
   ```

3. **Verify:**
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" https://www.sahjony.com/
   curl -s -o /dev/null -w "%{http_code}\n" https://www.mycubacash.com/api/health
   curl -s http://127.0.0.1/fallback-health -H "Host: www.sahjony.com"
   ```
   Expect 200s. The supplier-plans pages, intake forms, and WhatsApp endpoints
   are served from the fallback build (nightly sync from main).

4. **Announce** that traffic is on the fallback host.

## Failback (Vercel healthy again)

1. In the Vercel dashboard, revert the four A records to Vercel's values.
2. Wait for propagation, verify both sites return 200 on Vercel.
3. Leave the VPS standby running (it keeps syncing nightly) — do not dismantle it.

## Notes

- MY CUBA CASH needs its production secrets in `/etc/sahjony-fallback/cubacash.env`
  (values copied once from Vercel dashboard → cubacash → Settings → Environment
  Variables) or its dynamic features run degraded. The import/export Python
  backends degrade gracefully without secrets (public endpoints keep working).
- Fallback sync log: `/var/log/sahjony-fallback-sync.log` on the VPS.
- Never run two primaries at once: DNS points at exactly one host at a time.
