"""Runtime network compatibility hooks for SAHJONY Global Trade.

Vercel's Python runtime may resolve a dual-stack Neon endpoint to IPv6 even when
that invocation cannot open an IPv6 socket.  Keep the canonical DATABASE_URL
unchanged, preserve the hostname for TLS/SNI, and provide libpq an IPv4
``hostaddr`` when one is available.

This module is imported automatically by Python's site initialization when it is
present on sys.path.  The patch is intentionally narrow: Vercel runtime +
Neon-hosted Postgres only.  No credentials or connection-string values are
logged or exposed.
"""
from __future__ import annotations

import os
import socket
from urllib.parse import urlsplit


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
                # Fail closed to the normal driver path; never mutate DATABASE_URL.
                pass
        return original_connect(conninfo, *args, **kwargs)

    connect_with_ipv4_preference._sahjony_ipv4_preference = True
    psycopg.connect = connect_with_ipv4_preference


_install_neon_ipv4_preference()
