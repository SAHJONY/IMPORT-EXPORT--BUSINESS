from __future__ import annotations

import socket
from urllib.parse import urlsplit


def install_neon_ipv4_preference() -> None:
    """Prefer IPv4 for Neon while preserving hostname-based TLS verification.

    Vercel functions in this project have returned EADDRNOTAVAIL when libpq chose
    Neon IPv6 addresses.  Supplying hostaddr lets libpq connect to IPv4 while the
    original hostname remains in conninfo for TLS/SNI and certificate checks.
    """
    try:
        import psycopg
    except Exception:
        return

    original = psycopg.connect
    if getattr(original, "_sahjony_neon_ipv4", False):
        return

    def connect(conninfo: str = "", *args, **kwargs):
        if isinstance(conninfo, str) and conninfo and "hostaddr" not in kwargs:
            try:
                parsed = urlsplit(conninfo)
                host = parsed.hostname or ""
                if host.endswith(".neon.tech"):
                    port = parsed.port or 5432
                    ipv4 = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
                    if ipv4:
                        kwargs["hostaddr"] = ipv4[0][4][0]
            except Exception:
                pass
        return original(conninfo, *args, **kwargs)

    connect._sahjony_neon_ipv4 = True
    psycopg.connect = connect
