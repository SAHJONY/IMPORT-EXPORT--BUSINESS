"""Runtime connection guards for SAHJONY Global Trade.

This module is imported automatically by Python site initialization. It keeps
HTTP(S) Supabase API URLs away from psycopg/libpq while preserving the existing
Vercel + Neon IPv4 compatibility hook for genuine PostgreSQL DSNs.
"""
from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit


_POSTGRES_ENV_NAMES = (
    "DATABASE_URL",
    "POSTGRES_URL",
    "NEON_DATABASE_URL",
    "NEON_POSTGRES_URL",
    "POSTGRES_PRISMA_URL",
)


def _sanitize_postgres_environment() -> None:
    """Only allow real PostgreSQL URI schemes in SQL connection variables."""
    for name in _POSTGRES_ENV_NAMES:
        value = os.getenv(name, "").strip()
        if value and not value.lower().startswith(("postgresql://", "postgres://")):
            # SUPABASE_URL is an HTTPS REST endpoint, never a psycopg DSN.
            os.environ.pop(name, None)


def _install_neon_ipv4_preference() -> None:
    if not (os.getenv("VERCEL") or os.getenv("VERCEL_ENV")):
        return

    try:
        import psycopg
    except Exception:
        return

    original_connect = psycopg.connect
    if getattr(original_connect, "_sahjony_ipv4_preference", False):
        return

    def connect_with_ipv4_preference(conninfo: str = "", *args, **kwargs):
        if "hostaddr" not in kwargs and isinstance(conninfo, str) and conninfo:
            try:
                parsed = urlsplit(conninfo)
                host = parsed.hostname or ""
                port = parsed.port or 5432
                if host.endswith(".neon.tech"):
                    addresses = socket.getaddrinfo(
                        host,
                        port,
                        family=socket.AF_INET,
                        type=socket.SOCK_STREAM,
                    )
                    if addresses:
                        kwargs["hostaddr"] = addresses[0][4][0]
            except Exception:
                # Fall back to the normal driver path without exposing secrets.
                pass
        return original_connect(conninfo, *args, **kwargs)

    connect_with_ipv4_preference._sahjony_ipv4_preference = True
    psycopg.connect = connect_with_ipv4_preference


_sanitize_postgres_environment()
_install_neon_ipv4_preference()
