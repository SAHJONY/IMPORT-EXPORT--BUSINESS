from __future__ import annotations

import socket
from urllib.parse import urlsplit


_SUPABASE_POOLER_REGIONS = {
    # SAHJONY Global Trade canonical Supabase project.
    "qprlbmcoksrpuvodxjtt": "ca-central-1",
}


def _supabase_transaction_pooler_conninfo(conninfo: str) -> tuple[str, bool]:
    """Convert a known Supabase direct connection to its IPv4 transaction pooler.

    Uses psycopg's own conninfo parser so both PostgreSQL URIs and libpq-style
    keyword DSNs are supported, including safely encoded credentials. Secret
    values are never logged or returned outside the connection call.
    """
    try:
        from psycopg.conninfo import conninfo_to_dict, make_conninfo

        params = conninfo_to_dict(conninfo)
        host = str(params.get("host") or "").strip().lower()
        if not (host.startswith("db.") and host.endswith(".supabase.co")):
            return conninfo, False

        project_ref = host.removeprefix("db.").removesuffix(".supabase.co")
        region = _SUPABASE_POOLER_REGIONS.get(project_ref)
        if not region:
            return conninfo, False

        params["host"] = f"aws-0-{region}.pooler.supabase.com"
        params["port"] = "6543"
        params["user"] = f"postgres.{project_ref}"
        params["dbname"] = str(params.get("dbname") or "postgres")
        params["sslmode"] = str(params.get("sslmode") or "require")
        return make_conninfo(**params), True
    except Exception:
        # Last-resort detection keeps the original connection untouched. We
        # deliberately fail closed rather than attempting unsafe string surgery
        # around credentials.
        return conninfo, False


def install_neon_ipv4_preference() -> None:
    """Install provider-aware Postgres routing for Vercel production.

    * Neon: preserve hostname TLS verification while preferring IPv4 hostaddr.
    * Supabase: route known IPv6 direct endpoints through the IPv4 Supavisor
      transaction pooler and disable prepared statements for transaction mode.

    The historic function name is retained for compatibility with existing
    imports across the application.
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
            effective, using_supabase_transaction_pooler = _supabase_transaction_pooler_conninfo(conninfo)
            if using_supabase_transaction_pooler:
                kwargs.setdefault("prepare_threshold", None)

            try:
                from psycopg.conninfo import conninfo_to_dict

                parsed = conninfo_to_dict(effective)
                host = str(parsed.get("host") or "")
                port = int(parsed.get("port") or 5432)
                if host.endswith(".neon.tech") and "hostaddr" not in kwargs:
                    ipv4 = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
                    if ipv4:
                        kwargs["hostaddr"] = ipv4[0][4][0]
            except Exception:
                # Legacy URI fallback for Neon only.
                try:
                    parsed_uri = urlsplit(effective)
                    host = parsed_uri.hostname or ""
                    if host.endswith(".neon.tech") and "hostaddr" not in kwargs:
                        port = parsed_uri.port or 5432
                        ipv4 = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
                        if ipv4:
                            kwargs["hostaddr"] = ipv4[0][4][0]
                except Exception:
                    pass

        return original(effective, *args, **kwargs)

    connect._sahjony_neon_ipv4 = True
    connect._sahjony_postgres_runtime = True
    psycopg.connect = connect
