"""Governance contract — Python port of the GEV workforce core
(~/workspace/gods-eye-view/src/agents/workforceCore.js).

The same authority model speaks in both the browser (GEV) and this runtime:
same tiers, same track classifier, same sanctions hard stop, same draft
review, same audit expectations. Any drift between the two is a bug.

HARD RULES
- AGENT_TIERS has no execute tier. READ / DRAFT / PROPOSE only. Why: no
  agent may touch the wire. External effects (sends, posts, purchases,
  commitments) happen only through the existing governed outbox workflow,
  which is dispatched explicitly by Juan, one message at a time. This is
  structural: this package has no credentials, no transport client, and
  no code path that can enqueue anything.
- SANCTIONS_HARD_STOP: sanctions/customs/embargo questions ALWAYS escalate
  to Juan. The agent NEVER answers, advises, or routes around it.
- One conversation, one track. Tracks never blend: separate queues, separate
  CRM notes, separate deal-desk context.
- Sofia stays the single voice: every customer-facing word sounds like
  Sofia (Spanish-first on Cuba tracks). The swarm works behind her.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Agent tiers — intentionally no execute tier
# ---------------------------------------------------------------------------
#
# READ:    observe and classify only.
# DRAFT:   write drafts into the approval queue; nothing leaves the queue
#          without the compliance gate AND Juan's explicit per-message approval.
# PROPOSE: put a fully-formed proposal in front of Juan, one tap from done —
#          still requires his explicit word; silence is never consent.
#
# There is no 'execute' tier because execution (anything that reaches the
# wire or creates an external commitment) is not a capability agents are
# granted in degrees — it is a separate, human-dispatched act. Adding an
# execute tier would turn "who may act" into a config knob; the design
# keeps it structurally impossible: no credentials, no client, no send
# path in this package.

AGENT_TIERS = {
    "READ": "read",
    "DRAFT": "draft",
    "PROPOSE": "propose",
}

_TIER_VALUES = frozenset(AGENT_TIERS.values())

#: Cap for per-module workforce action logs (newest entries kept).
LOG_CAP = 500

#: Escalation queue key — items here wait on Juan and are NEVER dropped.
ESCALATION_QUEUE_KEY = "sahjony.workforce.escalations.v1"


def _workforce_log_key(module_id: str) -> str:
    return f"sahjony.workforce.{module_id}.log.v1"


# Module-level registries (runtime state; resettable for tests).
_workforce_registry: dict[str, list[dict]] = {}
_action_logs: dict[str, list[dict]] = {}
_escalations: list[dict] = []


def _require_non_empty(value: str, name: str) -> str:
    if not value or not str(value).strip():
        raise ValueError(f"hermes_swarm: {name} requires a non-empty value.")
    return str(value).strip()


def register_workforce(module_id: str, agents: list[dict]) -> list[dict]:
    """Register the agent roster for a module.

    Each agent: { id, role, tier, lang }. tier must be a known AGENT_TIERS
    value — an 'execute' tier (or any unknown tier) raises.
    """
    module_id = _require_non_empty(module_id, "register_workforce(module_id)")
    if not agents:
        raise ValueError(
            f"hermes_swarm: register_workforce('{module_id}') requires a "
            "non-empty agents list."
        )
    seen_ids: set[str] = set()
    registered: list[dict] = []
    for agent in agents:
        agent_id = _require_non_empty(agent.get("id", ""), "agent id")
        if agent_id in seen_ids:
            raise ValueError(
                f"hermes_swarm: duplicate agent id '{agent_id}' in module "
                f"'{module_id}'."
            )
        seen_ids.add(agent_id)
        tier = agent.get("tier")
        if tier not in _TIER_VALUES:
            raise ValueError(
                f"hermes_swarm: agent '{agent_id}' has invalid tier "
                f"'{tier}'. Allowed tiers: {sorted(_TIER_VALUES)}. There is "
                "no execute tier — nothing in this package may act on the "
                "wire."
            )
        registered.append(
            {
                "id": agent_id,
                "module": module_id,
                "role": _require_non_empty(agent.get("role", ""), "agent role"),
                "tier": tier,
                "lang": agent.get("lang", "es-first"),
            }
        )
    _workforce_registry[module_id] = registered
    return registered


def log_action(module_id: str, agent_id: str, action: dict) -> dict:
    """Append a bounded, per-module action record (newest LOG_CAP kept)."""
    module_id = _require_non_empty(module_id, "log_action(module_id)")
    agent_id = _require_non_empty(agent_id, "log_action(agent_id)")
    if not isinstance(action, dict) or not action:
        raise ValueError("hermes_swarm: log_action requires a non-empty action dict.")
    entry = {
        "module": module_id,
        "agent": agent_id,
        "action": dict(action),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    log = _action_logs.setdefault(_workforce_log_key(module_id), [])
    log.append(entry)
    del log[: max(0, len(log) - LOG_CAP)]
    return entry


def escalate(module_id: str, reason: str, payload: dict | None = None) -> dict:
    """Escalate to Juan. Escalations are NEVER dropped and never
    self-resolved: the only consumer is Juan's review.

    reason 'sanctions' is reserved for SANCTIONS_HARD_STOP.
    """
    module_id = _require_non_empty(module_id, "escalate(module_id)")
    reason = _require_non_empty(reason, "escalate(reason)")
    item = {
        "module": module_id,
        "reason": reason,
        "payload": dict(payload or {}),
        "at": datetime.now(timezone.utc).isoformat(),
        "status": "waiting-on-juan",
    }
    _escalations.append(item)
    return item


def pending_escalations() -> list[dict]:
    """Read-only view of the escalation queue (never auto-cleared)."""
    return list(_escalations)


# ---------------------------------------------------------------------------
# Track classification — Sofia single-front-door routing
# ---------------------------------------------------------------------------


def _normalize(text: str) -> str:
    """Lowercase + strip diacritics for keyword matching
    ('diésel' -> 'diesel', 'cotización' -> 'cotizacion')."""
    return "".join(
        ch
        for ch in unicodedata.normalize("NFD", str(text).lower())
        if not unicodedata.combining(ch)
    )


def _keyword_pattern(keyword: str) -> re.Pattern:
    escaped = re.escape(_normalize(keyword))
    # Word boundaries on single-word keywords so short tokens ('fob',
    # 'oil', 'wti', 'car') don't match inside longer words.
    if " " not in keyword.strip():
        return re.compile(rf"\b{escaped}\b")
    return re.compile(escaped)


#: [keyword, weight, lang]. 'es' marks a Spanish keyword, 'en' an English one.
TRACK_KEYWORDS: dict[str, list[tuple[str, int, str]]] = {
    "mycubacash": [
        ("remesa", 4, "es"),
        ("remesas", 4, "es"),
        ("remittance", 4, "en"),
        ("send money", 4, "en"),
        ("envio de dinero", 4, "es"),
        ("cuba cash", 4, "en"),
        ("mycubacash", 4, "en"),
        ("recarga", 3, "es"),
        ("top up", 3, "en"),
        ("cash app", 2, "en"),
        ("envio", 1, "es"),
    ],
    "cars": [
        ("carro", 3, "es"),
        ("coche", 3, "es"),
        ("automovil", 3, "es"),
        ("vehiculo", 3, "es"),
        ("vehicle", 3, "en"),
        ("gestoria", 3, "es"),
        ("auto", 2, "es"),
        ("car", 2, "en"),
        ("sedan", 2, "en"),
    ],
    "crude": [
        ("crude", 3, "en"),
        ("crudo", 3, "es"),
        ("petroleo", 3, "es"),
        ("barril", 3, "es"),
        ("barrel", 3, "en"),
        ("wti", 3, "en"),
        ("brent", 3, "en"),
        ("tanker", 3, "en"),
        ("buque tanque", 3, "es"),
        ("laycan", 3, "en"),
        ("sts", 3, "en"),
        ("refineria", 2, "es"),
        ("refinery", 2, "en"),
        ("cargo", 2, "en"),
        ("oil", 2, "en"),
    ],
    "energy": [
        ("diesel", 3, "en"),
        ("gasolina", 3, "es"),
        ("gasoline", 3, "en"),
        ("combustible", 3, "es"),
        ("glp", 3, "es"),
        ("lpg", 3, "en"),
        ("en 590", 3, "en"),
        ("planta electrica", 2, "es"),
        ("generador", 2, "es"),
        ("fuel", 2, "en"),
    ],
    "trade": [
        ("arroz", 3, "es"),
        ("rice", 3, "en"),
        ("soda ash", 3, "en"),
        ("sosa", 3, "es"),
        ("rfq", 3, "en"),
        ("cotizacion", 3, "es"),
        ("quotation", 3, "en"),
        ("proveedor", 2, "es"),
        ("supplier", 2, "en"),
        ("importador", 2, "es"),
        ("importer", 2, "en"),
        ("importacion", 2, "es"),
        ("exportacion", 2, "es"),
        ("mercancia", 2, "es"),
        ("flete", 2, "es"),
        ("freight", 2, "en"),
        ("contenedor", 2, "es"),
        ("container", 2, "en"),
        ("embarque", 2, "es"),
        ("shipment", 2, "en"),
        ("incoterm", 2, "en"),
        ("fob", 2, "en"),
        ("cif", 2, "en"),
    ],
    "cuba": [
        ("mipyme", 4, "es"),
        ("mipymes", 4, "es"),
        ("emprendedor", 3, "es"),
        ("habana", 2, "es"),
        ("havana", 2, "en"),
        ("mariel", 2, "es"),
        ("santiago de cuba", 2, "es"),
        ("cuba", 2, "es"),
    ],
}

#: Tracks whose Spanish keywords get a 1.5x weight boost (Cuba-facing).
ES_FIRST_TRACKS = frozenset({"cuba", "cars", "energy", "mycubacash"})
_ES_FIRST_BOOST = 1.5

#: Tie-break priority: highest-stakes, most-distinctive tracks first.
TRACK_PRIORITY = ("mycubacash", "cars", "crude", "energy", "trade", "cuba")

#: Compiled keyword patterns, built once.
_TRACK_PATTERNS: dict[str, list[tuple[re.Pattern, int, str]]] = {
    track: [(_keyword_pattern(kw), weight, lang) for kw, weight, lang in kws]
    for track, kws in TRACK_KEYWORDS.items()
}


def _track_score(normalized: str, track: str) -> float:
    score = 0.0
    for pattern, weight, lang in _TRACK_PATTERNS[track]:
        if not pattern.search(normalized):
            continue
        boost = _ES_FIRST_BOOST if (track in ES_FIRST_TRACKS and lang == "es") else 1.0
        score += weight * boost
    return score


def classify_track(text: str) -> str:
    """classify_track(text) -> 'trade' | 'cuba' | 'cars' | 'crude' |
    'energy' | 'mycubacash' | 'unknown'.

    Keyword-based, ES/EN, pure. Exactly one track per conversation.
    'trade' is the worldwide global desk; 'cuba' is its dedicated Cuba
    desk — same department, strictly separate pipelines. Commodity words
    alone (arroz, rice) do NOT pull a Cuba-desk message into 'trade';
    MIPYME/Cuba-buyer signals keep it on the Cuba desk, and worldwide
    sourcing without Cuba signals stays on 'trade'.
    Ties break by TRACK_PRIORITY (money-movement first). No keyword
    hits -> 'unknown'.
    """
    normalized = _normalize(text or "")
    best = "unknown"
    best_score = 0.0
    for track in TRACK_PRIORITY:
        score = _track_score(normalized, track)
        if score > best_score:
            best_score = score
            best = track
    return best


# ---------------------------------------------------------------------------
# Sanctions hard stop
# ---------------------------------------------------------------------------

#: SANCTIONS_HARD_STOP — any sanctions/customs/embargo question escalates
#: to Juan, ALWAYS. The agent NEVER answers, advises, or routes around it.
#: Module code calls check_sanctions(text) before any other processing and
#: calls escalate(module_id, 'sanctions', {'text': text}) on a hit.
SANCTIONS_HARD_STOP = {
    "gate": "sanctions",
    "action": "escalate-always",
}

_SANCTIONS_PATTERNS = [
    re.compile(p)
    for p in (
        r"\bsancion(es)?\b",
        r"\bsanction(s|ed)?\b",
        r"\bembargo(s)?\b",
        r"\bofac\b",
        r"\bsdn\b",
        r"lista negra",
        r"\bblacklist(ed|ing)?\b",
        r"denied part",
        r"restricted part",
        r"entity list",
        r"lista de sanciones",
    )
]

#: Customs terms only hard-stop when asked as a QUESTION ("¿cuánto tarda la
#: aduana?"), so routine logistics mentions ("aduana de Mariel") don't flood
#: Juan's escalation queue. Sanctions/embargo/OFAC terms always hard-stop.
_CUSTOMS_PATTERNS = [re.compile(r"\baduan\w*\b"), re.compile(r"\bcustoms?\b")]

_QUESTION_RE = re.compile(
    r"^\s*(que|cual|cuanto|como|donde|por que|what|how|which|when|why|is|are|do|does|can)\b"
)


def _looks_like_question(normalized: str) -> bool:
    if "?" in normalized or "¿" in normalized:
        return True
    return bool(_QUESTION_RE.match(normalized))


def check_sanctions(text: str) -> bool:
    """check_sanctions(text) -> bool. Pure.

    True when the text touches sanctions/embargo/OFAC/blacklist topics
    (always), or asks a customs/aduana question. Modules call this FIRST,
    before any other processing, then escalate(module_id, 'sanctions', …).
    """
    normalized = _normalize(text or "")
    if not normalized:
        return False
    if any(p.search(normalized) for p in _SANCTIONS_PATTERNS):
        return True
    return _looks_like_question(normalized) and any(
        p.search(normalized) for p in _CUSTOMS_PATTERNS
    )


# ---------------------------------------------------------------------------
# Language policy
# ---------------------------------------------------------------------------

#: LANG_POLICY — per-track language policy for all agent copy and drafts.
#: 'es-first': Spanish leads, English follows (Cuba-facing, WhatsApp-first).
#: 'bilingual': both languages, matched to the audience.
LANG_POLICY = {
    "cuba": "es-first",
    "cars": "es-first",
    "energy": "es-first",
    "mycubacash": "es-first",  # Cuba-facing convention (JS defaultRoster
    # treats any non-'bilingual' track as es-first)
    "trade": "bilingual",
    "crude": "bilingual",
    "unknown": "es-first",  # fail-safe: default to Spanish-first
}


def track_language(track: str) -> str:
    """Language policy for a track ('es-first' | 'bilingual')."""
    return LANG_POLICY.get(track, "es-first")


# ---------------------------------------------------------------------------
# Default per-module agent roster
# ---------------------------------------------------------------------------

_ROSTER_DEFS = (
    {
        "id": "inbox-triage",
        "role": "Inbox triage",
        "tier": AGENT_TIERS["READ"],
        "name": {"es": "Clasificación", "en": "Inbox triage"},
        "note": {
            "es": "Solo lectura: clasifica cada mensaje entrante (track, idioma, prioridad, intención) y lo deriva al especialista.",
            "en": "Read-only: classifies each inbound message (track, language, priority, intent) and routes it.",
        },
    },
    {
        "id": "customer-care",
        "role": "Customer care",
        "tier": AGENT_TIERS["DRAFT"],
        "name": {"es": "Atención al cliente", "en": "Customer care"},
        "note": {
            "es": "Redacta respuestas con la voz de Sofia, solo con hechos verificados.",
            "en": "Drafts replies in Sofia's voice, from verified facts only.",
        },
    },
    {
        "id": "lead-qualification",
        "role": "Lead qualification",
        "tier": AGENT_TIERS["DRAFT"],
        "name": {"es": "Calificación de leads", "en": "Lead qualification"},
        "note": {
            "es": "Califica y enriquece leads; nunca inventa datos de contacto.",
            "en": "Scores and enriches leads; never invents contact data.",
        },
    },
    {
        "id": "follow-up",
        "role": "Follow-up",
        "tier": AGENT_TIERS["DRAFT"],
        "name": {"es": "Seguimiento", "en": "Follow-up"},
        "note": {
            "es": "Redacta reactivaciones dentro de la ventana de 24h; respeta opt-out y límites.",
            "en": "Drafts re-engagement inside the 24h window; respects opt-out and rate limits.",
        },
    },
    {
        "id": "deal-desk",
        "role": "Deal desk",
        "tier": AGENT_TIERS["READ"],
        "name": {"es": "Mesa de operaciones", "en": "Deal desk"},
        "note": {
            "es": "Solo lectura: aporta contexto real del pipeline por track a los borradores.",
            "en": "Read-only: brings real per-track pipeline context into drafts.",
        },
    },
    {
        "id": "outreach-drafting",
        "role": "Outreach drafting",
        "tier": AGENT_TIERS["DRAFT"],
        "name": {"es": "Redacción de alcance", "en": "Outreach drafting"},
        "note": {
            "es": "Redacta alcance proactivo; cada borrador lleva nota de riesgo de bloqueo.",
            "en": "Drafts proactive outreach; every draft carries a ban-risk note.",
        },
    },
    {
        "id": "compliance-gate",
        "role": "Compliance gate",
        "tier": AGENT_TIERS["READ"],
        "name": {"es": "Puerta de cumplimiento", "en": "Compliance gate"},
        "note": {
            "es": "Solo lectura + escalamiento: revisa borradores con review_draft(); cualquier riesgo de sanciones dispara escalate() inmediato.",
            "en": "Read-only + escalation: reviews drafts with review_draft(); any sanctions risk triggers immediate escalate().",
        },
    },
)


def default_roster(module_id: str) -> list[dict]:
    """default_roster(module_id) -> [{ id, module, role, tier, lang, name, note }].

    Pure factory. Tiers: customer-care, lead-qualification, follow-up, and
    outreach-drafting are DRAFT only; inbox-triage, deal-desk, and
    compliance-gate are READ (+escalate for the gate). Nothing is above
    PROPOSE — there is no execute tier anywhere.
    """
    module_id = _require_non_empty(module_id, "default_roster(module_id)")
    lang = "bilingual" if LANG_POLICY.get(module_id) == "bilingual" else "es-first"
    return [
        {
            "id": d["id"],
            "module": module_id,
            "role": d["role"],
            "tier": d["tier"],
            "lang": lang,
            "name": dict(d["name"]),
            "note": dict(d["note"]),
        }
        for d in _ROSTER_DEFS
    ]


# ---------------------------------------------------------------------------
# Oversight: draft review
# ---------------------------------------------------------------------------


@dataclass
class Draft:
    """A single agent draft. Drafts are data — they can be reviewed, held,
    approved, or discarded, but a Draft object can never cause a send."""

    draft_id: str
    agent_id: str
    role: str
    tier: str
    track: str
    lang: str
    text: str
    kind: str = "reply"  # reply | followup | outreach | note | brief
    metadata: dict = field(default_factory=dict)


@dataclass
class ReviewFlag:
    code: str
    match: str
    es: str
    en: str


@dataclass
class ReviewResult:
    ok: bool
    flags: list[ReviewFlag] = field(default_factory=list)


#: review_draft flags invented facts / commitment patterns. The compliance
#: gate runs this on every draft before it reaches Juan:
#:   GUARANTEE    promise/commitment verbs (garantizar, comprometerse…)
#:   PRICE_COMMIT price stated as final/fixed/guaranteed
#:   AVAILABILITY availability stated as fact (en stock, inmediata…)
#:   TIMELINE     delivery/timing promised as fact
#:   COUNTERPARTY invented supplier/partner relationships claimed
#:   TRACK_RECORD invented sales history or client claims
#:   PRICE_AS_FACT a specific $ amount stated without a quote/estimate
#:                qualifier nearby (heuristic — the qualifier may just be
#:                farther away, so Juan still sees the flag and decides)
_DRAFT_FLAG_PATTERNS: list[tuple[str, re.Pattern, str, str]] = [
    (
        "GUARANTEE",
        re.compile(r"\b(garantiz\w*|te garantizo|nos compromet\w*|we guarantee|we commit|i promise|te lo prometo)\b"),
        "Promesa o compromiso: ningún agente puede garantizar resultados.",
        "Promise or commitment: no agent may guarantee outcomes.",
    ),
    (
        "AVAILABILITY",
        re.compile(r"\b(en stock|in stock|disponibilidad garantizada|disponible inmediatamente|immediate availability|entrega inmediata)\b"),
        "Disponibilidad afirmada como hecho: verificar con la fuente real antes de prometer.",
        "Availability stated as fact: verify with the real source before promising.",
    ),
    (
        "TIMELINE",
        re.compile(r"\b(entrega garantizada|guaranteed delivery|llega el \d|llegara el \d|delivery in \d+ days?|entrega en \d+ dias?)\b"),
        "Fecha o plazo de entrega prometido: los tiempos los confirma Juan, no el borrador.",
        "Delivery date or timeline promised: Juan confirms timing, not the draft.",
    ),
    (
        "COUNTERPARTY",
        re.compile(r"\b(nuestro proveedor|nuestra proveedora|nuestro socio|our supplier|our partner|proveedor confirmado|confirmed supplier)\b"),
        "Relación con contraparte afirmada: no inventar proveedores ni socios.",
        "Counterparty relationship claimed: never invent suppliers or partners.",
    ),
    (
        "PRICE_COMMIT",
        re.compile(r"\b(precio final|precio fijo|precio garantizado|precio confirmado|final price|fixed price|guaranteed price|locked[ -]in price)\b"),
        "Precio comprometido como definitivo: los precios finales los aprueba Juan.",
        "Price committed as final: Juan approves final prices.",
    ),
    (
        "TRACK_RECORD",
        re.compile(r"\b(hemos vendido|vendimos|we have sold|nuestros clientes|our clients|ya hemos entregado|we already delivered)\b"),
        "Historial de ventas/clientes afirmado: no inventar trayectoria.",
        "Sales history/clients claimed: never invent a track record.",
    ),
]

_PRICE_RE = re.compile(r"\$\s?\d[\d.,]*|\b\d[\d.,]*\s?(usd|mnt|cup|eur)\b")
_PRICE_QUALIFIER_RE = re.compile(
    r"\b(cotiz\w*|estim\w*|aprox\w*|quote|estimate|approx|referen\w*|reference|desde|from|hasta|up to)\b"
)


def _snippet_around(text: str, index: int, radius: int = 40) -> str:
    start = max(0, index - radius)
    end = min(len(text), index + radius)
    return text[start:end].strip()


def _draft_text(draft: Draft | dict | str) -> str:
    if isinstance(draft, Draft):
        return draft.text or ""
    if isinstance(draft, dict):
        return str(draft.get("text", "") or "")
    return str(draft or "")


def review_draft(draft: Draft | dict | str) -> ReviewResult:
    """review_draft(draft) -> ReviewResult(ok, flags). Pure.

    Flags invented facts / commitment patterns with bilingual explanations.
    ok=True means "no flags found", NOT "safe to send" — the draft still
    needs the compliance gate's session/opt-out/rate/sanctions checks and
    Juan's explicit approval.
    """
    text = _draft_text(draft)
    normalized = _normalize(text)
    flags: list[ReviewFlag] = []
    seen: set[str] = set()

    def push(code: str, es: str, en: str, match_index: int) -> None:
        key = f"{code}@{match_index}"
        if key in seen:
            return
        seen.add(key)
        flags.append(
            ReviewFlag(
                code=code,
                match=_snippet_around(text, match_index),
                es=es,
                en=en,
            )
        )

    for code, pattern, es, en in _DRAFT_FLAG_PATTERNS:
        for match in pattern.finditer(normalized):
            push(code, es, en, match.start())

    # PRICE_AS_FACT: a $ amount with no quote/estimate qualifier nearby.
    for match in _PRICE_RE.finditer(text):
        window_start = max(0, match.start() - 80)
        window_end = min(len(text), match.end() + 80)
        window = _normalize(text[window_start:window_end])
        if not _PRICE_QUALIFIER_RE.search(window):
            push(
                "PRICE_AS_FACT",
                "Precio específico sin calificador de cotización/estimado: podría ser un precio inventado.",
                "Specific price without a quote/estimate qualifier: could be an invented price.",
                match.start(),
            )

    return ReviewResult(ok=not flags, flags=flags)


def _reset_for_tests() -> None:
    """Clear module registries. Test-only; never called in production paths."""
    _workforce_registry.clear()
    _action_logs.clear()
    _escalations.clear()
