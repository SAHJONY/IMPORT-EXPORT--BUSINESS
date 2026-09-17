"""Sofia 360° salesperson — full-funnel sales playbooks, one per business track.

A playbook is the deterministic skeleton Sofia reasons with before the LLM
writes a single word: stages she runs, qualification questions she asks,
matching rules she applies, the follow-up cadence she keeps, dormant-revival
triggers, and the EXACT escalation triggers where she stops and briefs Juan.

Businesses stay strictly separate: every helper takes an explicit ``track``
and playbooks never share facts, stages, or state.

Tracks:
- ``import_export`` — SAHJONY Global Trade (sourcing, RFQ, freight)
- ``my_cuba_cash``   — MY CUBA CASH (money sends, divisas concierge)
- ``car_sales``      — SAHJONY car brokerage (FUTURE track). The signals and
  qualification below mirror agent/car_sales_agent.py from the
  ai-car-sales-machine repo (branch build/car-sales-v1). They are DEFINITIONS
  only: wiring car_sales into the live classifier/runtime needs Juan's
  explicit approval and is NOT done here.

Nothing here sends, quotes, or commits. Playbooks propose; the agentic sales
OS (sofia_agentic_sales_os.py) and the negotiation guards
(sofia_negotiation_guards.py) dispose.
"""

from __future__ import annotations

from typing import Any

# Fee schedule + announcements live in the authoritative track block —
# imported here so the playbook can never drift from the published figures.
# (sofia_my_cuba_cash_track.py is pure constants; no heavy imports.)
from sofia_my_cuba_cash_track import (
    FEE_BUSINESS,
    FEE_CONCIERGE,
    FEE_FAMILY,
    FEE_MARKETPLACE,
    FEE_PILOT,
    TRACK_ANNOUNCEMENT_IMPORT_EXPORT,
    TRACK_ANNOUNCEMENT_MY_CUBA_CASH,
    ZERO_CUSTODY_LINE,
)

TRACK_IMPORT_EXPORT = "import_export"
TRACK_MY_CUBA_CASH = "my_cuba_cash"
TRACK_CAR_SALES = "car_sales"

TRACKS = (TRACK_IMPORT_EXPORT, TRACK_MY_CUBA_CASH, TRACK_CAR_SALES)

# Standard follow-up cadence (days after last meaningful touch).
FOLLOWUP_CADENCE_DAYS = (1, 3, 7, 14)
# Silence longer than this after a qualified stage -> dormant-revival draft.
DORMANT_AFTER_DAYS = 14

# ---------------------------------------------------------------------------
# car_sales signals (FUTURE — for the classifier work, not activated here)
# ---------------------------------------------------------------------------

# Mirrors the classifier's phrase(2)/word(1) weighting convention so the
# future car_sales classifier work can import these directly.
CAR_SALES_PHRASES = (
    "quiero comprar un carro",
    "quiero comprar un auto",
    "busco un carro",
    "busco un auto",
    "carro en venta",
    "auto en venta",
    "vendo mi carro",
    "vendo mi auto",
    "cuanto cuesta el carro",
    "precio del carro",
    "test drive",
    "prueba de manejo",
    "i want to buy a car",
    "looking for a car",
    "car for sale",
    "selling my car",
)

CAR_SALES_WORDS = (
    "carro",
    "carros",
    "auto",
    "autos",
    "vehiculo",
    "vehiculos",
    "coche",
    "camioneta",
    "pickup",
    "toyota",
    "honda",
    "hyundai",
    "kia",
    "nissan",
    "ford",
    "chevrolet",
    "millaje",
    "millas",
    "titulo",
    "title",
    "trade-in",
    "tradein",
)

# ---------------------------------------------------------------------------
# car_sales qualification — mirrors ai-car-sales-machine agent/car_sales_agent.py
# ---------------------------------------------------------------------------

CAR_BUYER_FIELDS = ["budget", "payment_method", "trade_in", "timeline", "location"]
# Minimum viable qualification: not actionable until budget + timeline known.
CAR_BUYER_MINIMUM = ["budget", "timeline"]

CAR_BUYER_QUESTIONS = {
    "es": {
        "budget": "¿Cuál es tu presupuesto para el auto?",
        "payment_method": "¿Cómo pagarías: efectivo, financiamiento o transferencia?",
        "trade_in": "¿Tienes un auto para dar a cuenta (trade-in)?",
        "timeline": "¿Para cuándo quieres comprar?",
        "location": "¿En qué ciudad y país estás?",
    },
    "en": {
        "budget": "What is your budget for the car?",
        "payment_method": "How would you pay: cash, financing, or wire transfer?",
        "trade_in": "Do you have a car to trade in?",
        "timeline": "When are you looking to buy?",
        "location": "Which city and country are you in?",
    },
}

CAR_SELLER_FIELDS = [
    "make", "model", "year", "mileage", "condition",
    "asking_price", "title_status", "location", "fee_agreement",
]

CAR_SELLER_QUESTIONS = {
    "es": {
        "make": "¿Cuál es la marca del auto?",
        "model": "¿Cuál es el modelo?",
        "year": "¿De qué año es?",
        "mileage": "¿Cuántas millas tiene?",
        "condition": "¿En qué condición está (excelente/bueno/regular)?",
        "asking_price": "¿Qué precio pides?",
        "title_status": "¿El título está limpio o tiene algún problema?",
        "location": "¿En qué ciudad y país está el auto?",
        "fee_agreement": (
            "Una última cosa: SAHJONY trabaja como tu broker y aplica una "
            "comisión de intermediación (monto por definir). "
            "¿Aceptas los términos de la comisión?"
        ),
    },
    "en": {
        "make": "What is the car's make?",
        "model": "What is the model?",
        "year": "What year is it?",
        "mileage": "What is the mileage?",
        "condition": "What condition is it in (excellent/good/fair)?",
        "asking_price": "What is your asking price?",
        "title_status": "Is the title clean or does it have any issues?",
        "location": "Which city and country is the car in?",
        "fee_agreement": (
            "One last thing: SAHJONY works as your broker and a broker fee "
            "applies (amount set by Juan). Do you agree to the broker fee terms?"
        ),
    },
}

# ---------------------------------------------------------------------------
# import_export qualification — mirrors sofia_agentic_sales_os.py
# ---------------------------------------------------------------------------

# REQUIRED_TRADE_FIELDS in the sales OS. The RFQ minimum below mirrors the
# OS's rfq_fields (product, specification, quantity, destination,
# delivery_timeline): Sofia may not move to RFQ_READY without all five.
IMPORT_EXPORT_FIELDS = [
    "product", "specification", "quantity", "origin",
    "destination", "delivery_timeline", "target_budget",
]
IMPORT_EXPORT_RFQ_MINIMUM = [
    "product", "specification", "quantity", "destination", "delivery_timeline",
]

IMPORT_EXPORT_QUESTIONS = {
    "es": {
        "product": "¿Qué producto necesitas?",
        "specification": "¿Qué especificaciones debe cumplir el producto?",
        "quantity": "¿Qué cantidad o volumen necesitas?",
        "origin": "¿Desde qué país prefieres importar?",
        "destination": "¿A qué país o ciudad va la mercancía?",
        "delivery_timeline": "¿Para cuándo lo necesitas?",
        "target_budget": "¿Tienes un presupuesto objetivo?",
    },
    "en": {
        "product": "What product do you need?",
        "specification": "What specifications must the product meet?",
        "quantity": "What quantity or volume do you need?",
        "origin": "Which country would you like to import from?",
        "destination": "Which country or city is the cargo going to?",
        "delivery_timeline": "When do you need it delivered?",
        "target_budget": "Do you have a target budget?",
    },
}

# Authority lanes mirror sofia_agentic_sales_os.py (BINDING_ACTIONS,
# PROHIBITED_ACTIONS and the _next_actions lane mapping). The playbook names
# them; the OS enforces them.
IMPORT_EXPORT_AUTHORITY_LANES = {
    "autonomous": (
        "answer_and_qualify", "progressive_discovery", "prepare_rfq",
        "compare_verified_offers", "advance_negotiation",
    ),
    "owner_approval": (
        "release_quote", "accept_price", "grant_credit", "sign_contract",
        "change_beneficiary", "release_payment", "release_shipment",
        "clear_compliance", "mark_won",
    ),
    "prohibited": (
        "fabricate_evidence", "bypass_consent", "bypass_compliance",
        "bulk_unsolicited_outreach", "impersonate_human",
    ),
}

IMPORT_EXPORT_TOPIC_BOUNDARY = (
    "NEVER discuss remittances, money-send fees, divisas transfers, "
    "Western Union / Cubamax / Fonmoney, or the MIPYME divisas pilot. "
    "If the customer asks about sending money to Cuba, hand off once: "
    "'Te atiendo por MY CUBA CASH (envíos de dinero a Cuba).'"
)

# ---------------------------------------------------------------------------
# my_cuba_cash qualification — mirrors sofia_my_cuba_cash_track.py
# ---------------------------------------------------------------------------

MY_CUBA_CASH_FIELDS = [
    "send_amount", "recipient_name", "recipient_location",
    "delivery_method", "timeline",
]
# Minimum viable: Sofia cannot do anything useful without the amount and
# where it goes.
MY_CUBA_CASH_MINIMUM = ["send_amount", "recipient_location"]

MY_CUBA_CASH_QUESTIONS = {
    "es": {
        "send_amount": "¿Qué monto quieres enviar?",
        "recipient_name": "¿A nombre de quién es el envío?",
        "recipient_location": "¿En qué ciudad de Cuba recibe?",
        "delivery_method": "¿Cómo prefieres que le llegue el dinero?",
        "timeline": "¿Para cuándo lo necesitas?",
    },
    "en": {
        "send_amount": "How much do you want to send?",
        "recipient_name": "Who is the recipient?",
        "recipient_location": "Which city in Cuba will they receive in?",
        "delivery_method": "How should the money reach them?",
        "timeline": "When do you need it sent?",
    },
}

# Published fee schedule — the ONLY figures Sofia may quote. Imported from
# the track block (approved 2026-09-16); repeated here for playbook readers.
MY_CUBA_CASH_FEE_SCHEDULE = {
    "family": FEE_FAMILY,            # 1.25% (mínimo $1, máximo $12)
    "business": FEE_BUSINESS,        # 1.75% — NEVER framed as an
                                     # outbound-payment solution (US-linked
                                     # business payments blocked pending
                                     # qualified sanctions counsel)
    "marketplace": FEE_MARKETPLACE,  # 2.50% (la paga el vendedor)
    "concierge": FEE_CONCIERGE,      # $4 fijo — offer ONLY after the first
                                     # real sends validate demand; until
                                     # then, do NOT offer or mention it
    "mipyme_divisas_pilot": FEE_PILOT,  # $25 por pago coordinado; 3 cupos;
                                        # requisitos: licencia de importación
                                        # directa en mano o en trámite,
                                        # proveedor identificado, disposición
                                        # a documentar
}

# Tier 1/2/3 autonomy rules, mirroring MY_CUBA_CASH_SYSTEM_BLOCK.
MY_CUBA_CASH_TIERS = {
    "tier1_auto_reply": (
        "Greetings and how MY CUBA CASH works (a comparison + coordination "
        "layer for sending value to Cuba, currently in beta). The published "
        "fee schedule ONLY. Pointers to community group guides and rules. "
        "'We're looking into it' acknowledgments with a real follow-up time."
    ),
    "tier2_draft_only": (
        "'Which provider is best for my case' / corridor advice; transfer "
        "complaints; pricing beyond the published schedule or discounts; "
        "gestoría/accountant partnerships; anything mentioning regulators, "
        "lawyers, or legal interpretation. Draft for owner review; tell the "
        "customer their request is being reviewed with a real follow-up time."
    ),
    "tier3_escalate_immediately": (
        "Legal threats, fraud accusations, chargebacks/disputes; US-corridor "
        "or sanctions questions; custody requests (holding, receiving, or "
        "forwarding money) — decline with the zero-custody line; requests "
        "for credentials, IDs, or personal data; press/media inquiries. "
        "Do not answer substantively; escalate at once."
    ),
}

MY_CUBA_CASH_TOPIC_BOUNDARY = (
    "NEVER discuss sourcing, suppliers, freight, importing or exporting "
    "goods, customs brokerage for merchandise, or the SAHJONY "
    "partner/referral program. If the customer asks about those, hand off "
    "once: 'Te paso con el equipo de comercio internacional…'"
)

MY_CUBA_CASH_BETA_FRAMING = (
    "A comparison + coordination layer for sending value to Cuba, currently "
    "in beta. Never claim launched/full-service status, invented providers, "
    "rates, timelines, metrics, or capabilities."
)

# ---------------------------------------------------------------------------
# Playbook definitions
# ---------------------------------------------------------------------------

PLAYBOOKS: dict[str, dict[str, Any]] = {
    TRACK_CAR_SALES: {
        "track": TRACK_CAR_SALES,
        "business_name": "SAHJONY Car Brokerage",
        "status": "future",  # not wired into the live classifier/runtime
        "stages": (
            "NEW", "ENGAGED", "QUALIFYING_BUYER", "QUALIFYING_SELLER",
            "QUALIFIED", "MATCHED", "NEGOTIATING", "PENDING_JUAN",
            "WON", "LOST", "OPTED_OUT",
        ),
        "roles": ("buyer", "seller"),
        "buyer_fields": CAR_BUYER_FIELDS,
        "buyer_minimum": CAR_BUYER_MINIMUM,
        "buyer_questions": CAR_BUYER_QUESTIONS,
        "seller_fields": CAR_SELLER_FIELDS,
        "seller_questions": CAR_SELLER_QUESTIONS,
        "matching_rules": (
            "Match ONLY against listings from the verified inventory file; "
            "never invent a car. Budget must cover asking price. Market tag "
            "(cuba/usa/worldwide) must fit the buyer's location lane. "
            "No match -> say plainly the car is not in inventory and keep "
            "the buyer's criteria on file.",
        ),
        "followup_cadence_days": FOLLOWUP_CADENCE_DAYS,
        "dormant_after_days": DORMANT_AFTER_DAYS,
        "negotiation": (
            "Never quote below the listing's seller_floor. A below-floor "
            "offer is presented to the seller (Juan) — never accepted on the "
            "seller's behalf. Always disclose broker status and the fee in "
            "the first substantive reply.",
        ),
        "escalation_triggers": (
            {
                "trigger": "hot_lead",
                "when": "Buyer meets the minimum (budget + timeline) AND a verified listing matches budget and market.",
                "brief": "Qualified buyer + matching car. Needs Juan to confirm availability/price before Sofia proposes the match.",
            },
            {
                "trigger": "below_floor_offer",
                "when": "Buyer offers below the listing's seller_floor.",
                "brief": "Below-floor offer received. Sofia must NOT accept or counter below floor; Juan decides.",
            },
            {
                "trigger": "seller_ready_to_list",
                "when": "Seller intake complete including fee_agreement.",
                "brief": "Seller agreed to broker terms. Listing needs Juan's review before going live.",
            },
            {
                "trigger": "legality_question",
                "when": "Customer asks whether a car can be imported/exported somewhere, or about titles/registration legality.",
                "brief": "Import/legality question. Sofia must NOT make legal or customs determinations; Juan answers.",
            },
            {
                "trigger": "cross_border_shipping",
                "when": "Customer asks about shipping/transporting a car across borders (e.g. to Cuba).",
                "brief": "Cross-border shipping question. The car machine brokers the car deal only; freight belongs to the separate import/export business. Juan coordinates.",
            },
            {
                "trigger": "fee_dispute",
                "when": "Customer pushes back on the broker fee or asks for an amount Sofia cannot state.",
                "brief": "Fee objection. The fee amount is Juan's to set; Sofia must not invent or negotiate it.",
            },
        ),
    },
    TRACK_IMPORT_EXPORT: {
        "track": TRACK_IMPORT_EXPORT,
        "business_name": "SAHJONY Global Trade",
        "identity": "Sofia · SAHJONY Global Trade",
        "status": "live",
        "stages": (
            "NEW", "ENGAGED", "QUALIFYING", "QUALIFIED", "RFQ_READY",
            "SOURCING", "QUOTED", "NEGOTIATING", "PENDING_JUAN",
            "WON", "LOST", "OPTED_OUT",
        ),
        "qualification_fields": IMPORT_EXPORT_FIELDS,
        # Minimum viable = the sales OS's RFQ completeness bar. Sofia may not
        # move a deal to RFQ_READY without all five.
        "minimum": IMPORT_EXPORT_RFQ_MINIMUM,
        "qualification_questions": IMPORT_EXPORT_QUESTIONS,
        # Authority lanes mirror sofia_agentic_sales_os.py; the OS enforces.
        "authority_lanes": IMPORT_EXPORT_AUTHORITY_LANES,
        "topic_boundary": IMPORT_EXPORT_TOPIC_BOUNDARY,
        "track_announcement": TRACK_ANNOUNCEMENT_IMPORT_EXPORT,
        "matching_rules": (
            "Recommendations require verified supplier evidence: supplier, "
            "freight, compliance and landed-cost evidence normalized. "
            "Without verified evidence, cap progression at RFQ_READY. "
            "Never invent suppliers, prices, freight rates, availability, "
            "or compliance clearance."
        ),
        "broker_positioning": (
            "SAHJONY is a business broker for a fee — never the end buyer. "
            "No buyer-LOI language, no purchase commitments, no holding "
            "title or principal funds. Seller paper carries "
            "fee-protection/non-circumvention framing."
        ),
        "followup_cadence_days": FOLLOWUP_CADENCE_DAYS,
        "dormant_after_days": DORMANT_AFTER_DAYS,
        "negotiation": (
            "Formal quotes, price commitments, credit terms, contracts and "
            "WON status require verified evidence and Juan's approval. "
            "Non-binding objection handling may continue. Never invent a "
            "price, supplier, freight rate, or compliance clearance to keep "
            "a negotiation moving."
        ),
        "escalation_triggers": (
            {
                "trigger": "rfq_complete",
                "when": "Buyer requirement is complete (product, specification, quantity, destination, delivery timeline).",
                "brief": "Complete RFQ. Needs Juan's approval before sourcing/quoting moves forward.",
            },
            {
                "trigger": "price_acceptance",
                "when": "Customer accepts a price or asks Sofia to lock terms.",
                "brief": "Price acceptance. Binding commitment — Juan must approve verified terms.",
            },
            {
                "trigger": "compliance_flag",
                "when": "Sanctions, customs, or restricted-goods signals appear.",
                "brief": "Compliance flag. Sofia must not clear compliance; Juan decides with evidence.",
            },
            {
                "trigger": "cuba_legality",
                "when": "Customer asks about Cuba sanctions/customs legality for a specific shipment.",
                "brief": "Cuba legality question. General guidance only; transaction-specific clearance is Juan's.",
            },
            {
                "trigger": "partner_program_interest",
                "when": "Customer asks about the SAHJONY partner/referral program.",
                "brief": "Partner-program interest. Route to the Partner Center; Juan owns the relationship.",
            },
        ),
    },
    TRACK_MY_CUBA_CASH: {
        "track": TRACK_MY_CUBA_CASH,
        "business_name": "MY CUBA CASH",
        "identity": "Sofia · MY CUBA CASH",
        "status": "live",
        "stages": (
            "NEW", "ENGAGED", "QUALIFYING", "QUALIFIED",
            "INTAKE_STARTED", "PENDING_JUAN", "COMPLETED", "LOST", "OPTED_OUT",
        ),
        "qualification_fields": MY_CUBA_CASH_FIELDS,
        # Minimum viable: Sofia cannot do anything useful without the amount
        # and where it goes.
        "minimum": MY_CUBA_CASH_MINIMUM,
        "qualification_questions": MY_CUBA_CASH_QUESTIONS,
        # Tier 1/2/3 autonomy, mirroring MY_CUBA_CASH_SYSTEM_BLOCK.
        "tiers": MY_CUBA_CASH_TIERS,
        "topic_boundary": MY_CUBA_CASH_TOPIC_BOUNDARY,
        "track_announcement": TRACK_ANNOUNCEMENT_MY_CUBA_CASH,
        # The ONLY figures Sofia may quote (approved 2026-09-16).
        "fee_schedule": MY_CUBA_CASH_FEE_SCHEDULE,
        "beta_framing": MY_CUBA_CASH_BETA_FRAMING,
        "zero_custody_line": ZERO_CUSTODY_LINE,
        "matching_rules": (
            "Use ONLY verified intake records from mycubacash.com for a "
            "sender's number. Never invent amounts, statuses, timelines, "
            "providers, or rates. Intake lookup failures are reported "
            "plainly, never papered over. Update intents must resolve to a "
            "single intake; ambiguity escalates."
        ),
        "followup_cadence_days": FOLLOWUP_CADENCE_DAYS,
        "dormant_after_days": DORMANT_AFTER_DAYS,
        "negotiation": (
            "No price negotiation: fees are the published schedule. "
            "Never promise transfer timelines beyond what verified records "
            "show. Never present the 1.75% business tier as an "
            "outbound-payment solution. Never offer or mention the "
            "concierge tier until the first real sends validate demand."
        ),
        "escalation_triggers": (
            {
                "trigger": "intake_lookup_failed",
                "when": "Customer asks about a request but the intake lookup fails or finds nothing.",
                "brief": "Intake lookup failed/empty. Juan follows up manually; Sofia must not invent a record.",
            },
            {
                "trigger": "ambiguous_update_target",
                "when": "Customer wants to update a request and multiple intakes exist.",
                "brief": "Ambiguous update target. Juan disambiguates with the customer.",
            },
            {
                "trigger": "fraud_signal",
                "when": "Chargeback, impersonation, or coercion signals appear.",
                "brief": "Possible fraud signal. Freeze the flow and brief Juan immediately.",
            },
            {
                "trigger": "custody_request",
                "when": "Customer asks Sofia to hold, receive, or forward money.",
                "brief": "Custody request. Decline with the zero-custody line and escalate; MY CUBA CASH never touches money.",
            },
            {
                "trigger": "sanctions_question",
                "when": "Customer asks about the US corridor, sanctions, or legal interpretation of a transfer.",
                "brief": "Sanctions/legal question. Sofia must not interpret; Juan decides with qualified counsel.",
            },
            {
                "trigger": "concierge_inquiry",
                "when": "Customer asks about the concierge tier before the first real sends validate demand.",
                "brief": "Concierge inquiry. Do NOT offer or mention it; Juan decides whether demand is validated.",
            },
        ),
    },
}


def get_playbook(track: str) -> dict[str, Any]:
    """Return the playbook for a track. Raises ValueError for unknown tracks —
    businesses never fall through to another track's playbook."""
    if track not in PLAYBOOKS:
        raise ValueError(f"Unknown sales track: {track!r}. Known: {TRACKS}")
    return PLAYBOOKS[track]


def playbook_stages(track: str) -> tuple[str, ...]:
    return tuple(get_playbook(track)["stages"])


def next_qualification_question(track: str, state: dict[str, Any], language: str = "es") -> str | None:
    """Next missing qualification question for a track, or None when the
    track's minimum viable qualification is complete.

    Car sales mirrors ai-car-sales-machine: buyer minimum = budget + timeline;
    seller intake is complete only with asking_price + fee_agreement.
    import_export mirrors the sales OS RFQ bar; my_cuba_cash mirrors the
    concierge intake. Every track has per-field questions in ES/EN (the
    MY CUBA CASH track additionally mirrors EN/FR/PT via the runtime's
    language layer).
    """
    book = get_playbook(track)
    lang = language if language in ("es", "en") else "es"
    if track == TRACK_CAR_SALES:
        role = state.get("role") or ("seller" if state.get("is_seller") else "buyer")
        if role == "seller":
            questions = book["seller_questions"][lang]
            for field in book["seller_fields"]:
                if not state.get(field):
                    return questions[field]
            return None
        questions = book["buyer_questions"][lang]
        for field in book["buyer_fields"]:
            if not state.get(field):
                return questions[field]
        return None
    questions = book.get("qualification_questions", {}).get(lang, {})
    for field in book["qualification_fields"]:
        if not state.get(field):
            if field in questions:
                return questions[field]
            # Generic, non-invented prompt for the missing field.
            label = field.replace("_", " ")
            if lang == "es":
                return f"¿Me confirmas {label}?"
            return f"Could you confirm the {label}?"
    return None


def is_minimum_qualified(track: str, state: dict[str, Any]) -> bool:
    """True when the track's minimum viable qualification is met.

    import_export: the sales OS RFQ bar (product, specification, quantity,
    destination, delivery_timeline). my_cuba_cash: send_amount +
    recipient_location. car_sales: buyer budget + timeline; seller
    asking_price + fee_agreement.
    """
    book = get_playbook(track)
    if track == TRACK_CAR_SALES:
        role = state.get("role") or ("seller" if state.get("is_seller") else "buyer")
        if role == "seller":
            return bool(state.get("asking_price") and state.get("fee_agreement"))
        return all(state.get(f) for f in book["buyer_minimum"])
    minimum = book.get("minimum") or book["qualification_fields"][:3]
    return all(state.get(f) for f in minimum)


def escalation_triggers(track: str) -> tuple[dict[str, Any], ...]:
    return tuple(get_playbook(track)["escalation_triggers"])


def car_signal_score(text: str) -> float:
    """Prospective car_sales signal strength in [0, 1].

    DEFINITION ONLY — used by the 360° loop behind the feature flag and by
    the future classifier work. Does NOT change live classification.
    Phrases weight 2, single words weight 1 (classifier convention).
    """
    import re
    import unicodedata

    def _strip_accents(s: str) -> str:
        return "".join(
            c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
        )

    t = _strip_accents((text or "").lower())
    score = 0.0
    masked = t
    for phrase in CAR_SALES_PHRASES:
        if phrase in masked:
            score += 2.0
            masked = masked.replace(phrase, " ")
    for word in CAR_SALES_WORDS:
        if re.search(r"\b" + re.escape(word) + r"\b", masked):
            score += 1.0
    # Normalize: 3+ points of signal is a strong car-sales read.
    return min(1.0, score / 3.0)
