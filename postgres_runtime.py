from __future__ import annotations

import socket
from urllib.parse import urlsplit, urlunsplit


_SUPABASE_POOLER_REGIONS = {
    # SAHJONY Global Trade canonical Supabase project.
    "qprlbmcoksrpuvodxjtt": "ca-central-1",
}


def _supabase_transaction_pooler_url(conninfo: str) -> tuple[str, bool]:
    """Convert a known Supabase direct URL to its IPv4 Supavisor transaction pooler.

    Supabase direct database endpoints are IPv6 by default. Vercel serverless
    functions are IPv4-only for outbound Postgres connections, so production
    traffic must use the shared transaction pooler on port 6543.

    Credentials are preserved exactly as encoded in the incoming URL and are
    never logged or returned to callers.
    """
    try:
        parsed = urlsplit(conninfo)
        host = (parsed.hostname or "").lower()
        if not (host.startswith("db.") and host.endswith(".supabase.co")):
            return conninfo, False

        project_ref = host.removeprefix("db.").removesuffix(".supabase.co")
        region = _SUPABASE_POOLER_REGIONS.get(project_ref)
        if not region:
            return conninfo, False

        raw_userinfo = parsed.netloc.rsplit("@", 1)[0] if "@" in parsed.netloc else ""
        if ":" in raw_userinfo:
            _, raw_password = raw_userinfo.split(":", 1)
            pooler_userinfo = f"postgres.{project_ref}:{raw_password}"
        elif raw_userinfo:
            pooler_userinfo = f"postgres.{project_ref}"
        else:
            pooler_userinfo = f"postgres.{project_ref}"

        pooler_host = f"aws-0-{region}.pooler.supabase.com"
        netloc = f"{pooler_userinfo}@{pooler_host}:6543"
        query = parsed.query
        if "sslmode=" not in query.lower():
            query = f"{query}&sslmode=require" if query else "sslmode=require"
        return urlunsplit((parsed.scheme, netloc, parsed.path or "/postgres", query, parsed.fragment)), True
    except Exception:
        return conninfo, False


def install_neon_ipv4_preference() -> None:
    """Install provider-aware Postgres routing for Vercel production.

    * Neon: preserve the hostname for TLS while preferring an IPv4 hostaddr.
    * Supabase: rewrite known IPv6 direct endpoints to the IPv4 Supavisor
      transaction pooler and disable prepared statements for transaction mode.

    The historic function name is retained to avoid changing every importer.
    """
    try:
        import psycopg
    except Exception:
        return

    original = psycopg.connect
    if getattr(original, "_sahjony_postgres_runtime", False):
        return

    def connect(conninfo: str = "", *args, **kwargs):
        effective = conninfo
        if isinstance(conninfo, str) and conninfo:
            effective, using_supabase_transaction_pooler = _supabase_transaction_pooler_url(conninfo)
            if using_supabase_transaction_pooler:
                kwargs.setdefault("prepare_threshold", None)

            try:
                parsed = urlsplit(effective)
                host = parsed.hostname or ""
                if host.endswith(".neon.tech") and "hostaddr" not in kwargs:
                    port = parsed.port or 5432
                    ipv4 = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
                    if ipv4:
                        kwargs["hostaddr"] = ipv4[0][4][0]
            except Exception:
                pass

        return original(effective, *args, **kwargs)

    connect._sahjony_neon_ipv4 = True
    connect._sahjony_postgres_runtime = True
    psycopg.connect = connect
