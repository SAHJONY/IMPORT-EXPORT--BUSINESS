# VPS fallback host

Hot standby for both SAHJONY business applications on the Hostinger VPS
(69.62.68.67), in case Vercel goes down again.

| App | Domains | How it's served |
|---|---|---|
| SAHJONY import/export | sahjony.com, www.sahjony.com | nginx (static) + uvicorn (FastAPI on :8101/:8102) |
| MY CUBA CASH | mycubacash.com, www.mycubacash.com | nginx → Next.js `next start` (:8103) |

Files:

- `setup.sh` — idempotent setup. Installs nginx, Python backends, Next.js, systemd
  units, nginx configs, nightly sync cron. Never touches the WhatsApp gateway.
- `sync.sh` — nightly sync from `main` (04:00 UTC), rebuilds, restarts services.
- `FAILOVER.md` — the runbook for flipping DNS + TLS when Vercel is down.

## One-command install (run on the VPS as root, e.g. Hostinger web terminal)

```bash
curl -sSL https://raw.githubusercontent.com/SAHJONY/IMPORT-EXPORT--BUSINESS/ops/vps-fallback-host/ops/vps-fallback/setup.sh | bash
```

After it finishes:

1. Copy the MY CUBA CASH production secrets into `/etc/sahjony-fallback/cubacash.env`
   (values from Vercel dashboard → cubacash → Settings → Environment Variables),
   then re-run the command above — it picks up where it left off.
2. Test locally on the VPS:
   `curl -H 'Host: www.sahjony.com' http://127.0.0.1/fallback-health`
3. Read `FAILOVER.md` so the DNS flip takes ~10 minutes when it matters.
