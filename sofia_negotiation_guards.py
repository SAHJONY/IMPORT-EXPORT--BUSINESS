"""Sofia 360° salesperson — negotiation guardrails.

Deterministic validation of anything Sofia is about to say or propose.
The model proposes; these guards dispose. Every check is pure and
synchronous so the sales loop can run them on every turn.

Hard rules enforced, per business:
- car_sales: never quote below a seller's floor; broker positioning + fee
  disclosure in the first substantive reply; never commit Juan to buy/pay/sign.
- import_export: never invent suppliers, prices, freight rates, availability,
  or compliance clearance; SAHJONY is a broker for a fee — never the end
  buyer, no buyer-LOI language. Trade claims need verified evidence.
- my_cuba_cash: never invent providers or rates; only the published fee
  schedule may be quoted (family 1.25% min $1 max $12, business 1.75%,
  marketplace 2.50% seller-pays); the concierge tier ($4) is not offered or
  mentioned until the first real sends validate demand; the 1.75% business
  tier is never framed as an outbound-payment solution; zero custody always;
  beta framing — no launched/full-service claims.
- All tracks: never make legal or customs determinations; never claim an
  external action happened (sent, booked, paid, shipped).

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

# Buyer-positioning language — forbidden for import_export and car_sales.
# SAHJONY is a business broker for a fee, never the end buyer.
BUYER_POSITIONING_PATTERNS = (
    r"\bas the buyer\b",
    r"\bwe('re| are) the buyer\b",
    r"\bend buyer\b",
    r"\bcomprador final\b",
    r"\bcomo comprador\b",
    r"\bsomos el comprador\b",
    r"\bactuamos como comprador\b",
    r"carta de intenci[oó]n de compra",
    r"\bb[ée]y[ée]r'?s loi\b",
)

# Definitive supplier/freight claims (import/export) — require verified
# evidence. Without it the playbook caps progression at RFQ_READY.
TRADE_EVIDENCE_PATTERNS = (
    r"nuestro proveedor",
    r"tenemos (un |el )?proveedor",
    r"el proveedor (cotiz[oó]|ofrece|confirm[oó])",
    r"supplier (quoted|confirmed|offered)",
    r"el flete cuesta",
    r"\bfreight costs?\b",
    r"costo de env[ií]o confirmado",
)

# MY CUBA CASH: published fee schedule (approved 2026-09-16) — the ONLY
# percentages Sofia may quote.
PUBLISHED_FEE_PCTS = {1.25, 1.75, 2.50}

# Known provider names for the invented-provider check.
KNOWN_PROVIDERS = (
    "western union", "cubamax", "sendvalu", "fonmoney",
    "correos españa", "ikualo", "íkualo",
)

# Offering language — a provider name next to one of these is an
# availability/recommendation claim that needs a verified provider record.
_PROVIDER_OFFER_PATTERNS = (
    r"\bofrecemos\b", r"\bwe offer\b", r"\bdisponible\b", r"\bavailable\b",
    r"\brecomendamos\b", r"\bwe recommend\b", r"\btrabajamos con\b",
    r"\bwe work with\b",
)

# Custody offers — forbidden under the zero-custody rule.
CUSTODY_OFFER_PATTERNS = (
    r"\bwe will hold\b",
    r"\bhold your money\b",
    r"\brecibiremos tu dinero\b",
    r"\bguardamos tu dinero\b",
    r"\bforward your money\b",
    r"\breenviaremos tu dinero\b",
    r"\bwe'?ll receive (it|your money)\b",
    r"\brecibimos el dinero por ti\b",
)

# Launch-status claims — forbidden under beta framing.
BETA_VIOLATION_PATTERNS = (
    r"\bfully launched\b",
    r"\blanzamiento oficial\b",
    r"\boperando al 100%\b",
    r"\bservicio completo y establecido\b",
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


def check_broker_positioning(reply_text: str, track: str) -> list[str]:
    """Fail when the reply frames SAHJONY/Juan as the end buyer.

    Applies to import_export and car_sales: SAHJONY is a business broker for
    a fee — never the end buyer, no buyer-LOI language.
    """
    if track not in ("import_export", "car_sales"):
        return []
    text = _lower(reply_text)
    return [
        f"buyer positioning (broker-only rule): {pattern!r}"
        for pattern in BUYER_POSITIONING_PATTERNS
        if re.search(pattern, text)
    ]


def check_trade_evidence(
    reply_text: str, track: str, has_verified_trade_evidence: bool | None
) -> list[str]:
    """Fail when an import/export reply makes definitive supplier/freight
    claims without verified evidence.

    ``has_verified_trade_evidence``: True = evidence exists (pass), False =
    definitive claims fail, None = unknown (check skipped, cannot judge).
    """
    if track != "import_export" or has_verified_trade_evidence is not False:
        return []
    text = _lower(reply_text)
    return [
        f"trade claim without verified evidence: {pattern!r}"
        for pattern in TRADE_EVIDENCE_PATTERNS
        if re.search(pattern, text)
    ]


def check_fee_schedule_honesty(
    reply_text: str, track: str, concierge_available: bool = False
) -> list[str]:
    """Fail when a MY CUBA CASH reply breaks fee-schedule honesty.

    - Only the published percentages (1.25 / 1.75 / 2.50) may be quoted.
    - The concierge tier is not offered or mentioned until the first real
      sends validate demand.
    - The 1.75% business tier is never framed as an outbound-payment
      solution (US-linked business payments are blocked pending qualified
      sanctions counsel).
    """
    if track != "my_cuba_cash":
        return []
    violations: list[str] = []
    text = _lower(reply_text)
    if "concierge" in text and not concierge_available:
        violations.append(
            "concierge tier mentioned before demand validation"
        )
    for match in re.finditer(r"(\d+[.,]\d+)\s*%", text):
        try:
            pct = float(match.group(1).replace(",", "."))
        except ValueError:
            continue
        if pct not in PUBLISHED_FEE_PCTS:
            violations.append(
                f"fee {match.group(1)}% is not on the published schedule"
            )
    if re.search(r"1[.,]75\s*%", text) and re.search(
        r"\b(puedes? pagar|you can pay|outbound|realizar el pago|hacer el pago)\b",
        text,
    ):
        violations.append(
            "1.75% business tier framed as an outbound-payment solution "
            "(blocked pending sanctions counsel)"
        )
    return violations


def check_zero_custody(reply_text: str, track: str) -> list[str]:
    """Fail when a MY CUBA CASH reply offers to hold/receive/forward money.

    The customer pays their provider/bank directly; MY CUBA CASH never
    touches the principal.
    """
    if track != "my_cuba_cash":
        return []
    text = _lower(reply_text)
    return [
        f"custody offer (zero-custody rule): {pattern!r}"
        for pattern in CUSTODY_OFFER_PATTERNS
        if re.search(pattern, text)
    ]


def check_no_invented_providers(
    reply_text: str, track: str, verified_providers: list[str] | None
) -> list[str]:
    """Fail when a MY CUBA CASH reply offers/recommends a provider that is
    not in the verified provider set.

    Mere mentions without offering language are not violations; only
    availability/recommendation claims need grounding.
    """
    if track != "my_cuba_cash":
        return []
    verified = {str(p).lower().strip() for p in (verified_providers or [])}
    text = _lower(reply_text)
    if not any(re.search(pattern, text) for pattern in _PROVIDER_OFFER_PATTERNS):
        return []
    return [
        f"provider {name!r} offered but not in verified providers"
        for name in KNOWN_PROVIDERS
        if name in text and name not in verified
    ]


def check_beta_framing(reply_text: str, track: str) -> list[str]:
    """Fail when a MY CUBA CASH reply claims launched/full-service status.

    MY CUBA CASH is in beta: a comparison + coordination layer, never a
    fully launched service.
    """
    if track != "my_cuba_cash":
        return []
    text = _lower(reply_text)
    return [
        f"launch-status claim (beta framing): {pattern!r}"
        for pattern in BETA_VIOLATION_PATTERNS
        if re.search(pattern, text)
    ]


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
    # import_export: True = verified supplier/freight/compliance evidence
    # exists; False = definitive trade claims fail; None = check skipped.
    has_verified_trade_evidence: bool | None = None,
    # my_cuba_cash: names of verified providers (lowercased compare).
    verified_providers: list[str] | None = None,
    # my_cuba_cash: True only after the first real sends validate demand.
    concierge_available: bool = False,
) -> dict[str, Any]:
    """Run every guardrail against a candidate reply.

    Returns {"ok": bool, "violations": [str, ...]}. ok=False means the reply
    must NOT go out — escalate to Juan with the violations listed.
    Track-scoped checks only run for their own track.
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
    # Per-business guardrails.
    violations.extend(check_broker_positioning(reply_text, track))
    violations.extend(
        check_trade_evidence(reply_text, track, has_verified_trade_evidence)
    )
    violations.extend(
        check_fee_schedule_honesty(reply_text, track, concierge_available)
    )
    violations.extend(check_zero_custody(reply_text, track))
    violations.extend(
        check_no_invented_providers(reply_text, track, verified_providers)
    )
    violations.extend(check_beta_framing(reply_text, track))
    return {"ok": not violations, "violations": violations}
