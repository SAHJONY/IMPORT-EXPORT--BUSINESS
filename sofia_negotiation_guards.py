"""Sofia 360° salesperson — negotiation guardrails.

Deterministic validation of anything Sofia is about to say or propose.
The model proposes; these guards dispose. Every check is pure and
synchronous so the sales loop can run them on every turn.

Hard rules enforced:
- NEVER quote below a seller's floor price.
- NEVER invent prices, inventory, availability, sellers, or buyers.
- Car deals: broker positioning + fee disclosure in the first substantive
  reply; never commit Juan to buy/pay/sign.
- NEVER make legal or customs determinations (Cuba matters especially).
- NEVER claim an external action happened (sent, booked, paid, shipped).

``validate_outbound`` returns {"ok": bool, "violations": [str, ...]}.
A failed validation means: do not send — escalate to Juan instead.
"""

from __future__ import annotations

import re
from typing import Any

# Phrases the salesperson must NEVER emit. Mirrors the car machine's
# FORBIDDEN_COMMITMENT_PHRASES and extends to general commitments.
FORBIDDEN_COMMITMENT_PHRASES = (
    "we will buy",
    "we accept your car",
    "we'll buy it",
    "vamos a comprar",
    "aceptamos tu auto",
    "lo compramos",
    "i have sent",
    "he enviado",
    "ya lo envié",
    "i booked",
    "reservado",
    "i paid",
    "he pagado",
    "ya pagué",
    "payment completed",
    "pago completado",
    "contract signed",
    "contrato firmado",
)

# Phrases that constitute a legal/customs determination — forbidden.
# General guidance is allowed; transaction-specific clearance is Juan's.
LEGAL_DETERMINATION_PATTERNS = (
    r"you are cleared to",
    r"está autorizado para importar",
    r"esta autorizado para importar",
    r"legal to import",
    r"es legal importar",
    r"no hay problema legal",
    r"no legal issue",
    r"customs approved",
    r"aduana aprobada",
    r"sanctions do not apply",
    r"las sanciones no aplican",
)

# Broker disclosure markers (car deals). One of these must appear in the
# first substantive car-sales reply.
BROKER_DISCLOSURE_MARKERS = (
    "broker",
    "intermediación",
    "intermediacion",
    "comisión",
    "comision",
)

_MONEY_RE = re.compile(r"\$\s?[\d,]+(?:\.\d+)?")


def _clean(text: Any) -> str:
    return str(text or "").strip()


def _lower(text: Any) -> str:
    return _clean(text).lower()


def check_no_purchase_commitment(reply_text: str) -> list[str]:
    """Fail when the reply commits Juan to buy/pay/sign/ship."""
    text = _lower(reply_text)
    return [
        f"forbidden commitment phrase: {phrase!r}"
        for phrase in FORBIDDEN_COMMITMENT_PHRASES
        if phrase in text
    ]


def check_no_legal_determination(reply_text: str) -> list[str]:
    """Fail when the reply makes a legal/customs determination."""
    text = _lower(reply_text)
    violations = []
    for pattern in LEGAL_DETERMINATION_PATTERNS:
        if re.search(pattern, text):
            violations.append(f"legal/customs determination: {pattern!r}")
    return violations


def check_floor_price(reply_text: str, listing: dict[str, Any] | None) -> list[str]:
    """Fail when the reply quotes below the listing's seller floor.

    ``listing`` may carry ``seller_floor`` (minimum acceptable price).
    Only explicit $ amounts in the reply are checked; a reply with no
    quoted price cannot violate the floor.
    """
    if not listing:
        return []
    floor = listing.get("seller_floor")
    if floor is None:
        return []
    try:
        floor_value = float(floor)
    except (TypeError, ValueError):
        return []
    violations = []
    for match in _MONEY_RE.finditer(_clean(reply_text)):
        raw = match.group(0).replace("$", "").replace(",", "").strip()
        try:
            quoted = float(raw)
        except ValueError:
            continue
        if quoted < floor_value:
            violations.append(
                f"quoted ${quoted:g} below seller floor ${floor_value:g}"
            )
    return violations


def check_no_invented_amounts(
    reply_text: str, verified_amounts: list[Any] | None
) -> list[str]:
    """Fail when the reply states a $ amount not present in verified amounts.

    ``verified_amounts`` are numbers from real records (listings, intakes,
    fee config). Amounts in the reply must match one of them. An empty
    verified list with amounts in the reply is a violation (nothing to
    ground them).
    """
    quoted = []
    for match in _MONEY_RE.finditer(_clean(reply_text)):
        raw = match.group(0).replace("$", "").replace(",", "").strip()
        try:
            quoted.append(float(raw))
        except ValueError:
            continue
    if not quoted:
        return []
    verified: set[float] = set()
    for amount in verified_amounts or []:
        try:
            verified.add(float(amount))
        except (TypeError, ValueError):
            continue
    return [
        f"unverified amount quoted: ${amount:g}"
        for amount in quoted
        if amount not in verified
    ]


def check_broker_disclosure(
    reply_text: str, track: str, is_first_substantive: bool
) -> list[str]:
    """Fail when a first substantive car-sales reply lacks broker disclosure."""
    if track != "car_sales" or not is_first_substantive:
        return []
    text = _lower(reply_text)
    if any(marker in text for marker in BROKER_DISCLOSURE_MARKERS):
        return []
    return ["car-sales reply missing broker positioning/fee disclosure"]


def check_no_action_claims(reply_text: str) -> list[str]:
    """Fail when the reply claims an external action already happened."""
    text = _lower(reply_text)
    claim_patterns = (
        r"\b(i|we) (sent|booked|paid|shipped|filed|submitted|signed)\b",
        r"\b(he|hemos) (enviado|reservado|pagado|firmado|presentado)\b",
        r"\bya (lo |la )?(envié|enviamos|pagué|pagamos|reservé)\b",
    )
    return [
        f"unverified external-action claim: {pattern!r}"
        for pattern in claim_patterns
        if re.search(pattern, text)
    ]


def validate_outbound(
    *,
    reply_text: str,
    track: str,
    listing: dict[str, Any] | None = None,
    verified_amounts: list[Any] | None = None,
    is_first_substantive: bool = False,
) -> dict[str, Any]:
    """Run every guardrail against a candidate reply.

    Returns {"ok": bool, "violations": [str, ...]}. ok=False means the reply
    must NOT go out — escalate to Juan with the violations listed.
    """
    violations: list[str] = []
    violations.extend(check_no_purchase_commitment(reply_text))
    violations.extend(check_no_legal_determination(reply_text))
    violations.extend(check_no_action_claims(reply_text))
    violations.extend(check_floor_price(reply_text, listing))
    violations.extend(
        check_no_invented_amounts(reply_text, verified_amounts)
    )
    violations.extend(
        check_broker_disclosure(reply_text, track, is_first_substantive)
    )
    return {"ok": not violations, "violations": violations}
