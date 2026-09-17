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
        "status": "live",
        "stages": (
            "NEW", "ENGAGED", "QUALIFYING", "QUALIFIED", "RFQ_READY",
            "SOURCING", "QUOTED", "NEGOTIATING", "PENDING_JUAN",
            "WON", "LOST", "OPTED_OUT",
        ),
        "qualification_fields": [
            "product", "specification", "quantity", "origin",
            "destination", "delivery_timeline", "target_budget",
        ],
        "matching_rules": (
            "Recommendations require verified supplier evidence: supplier, "
            "freight, compliance and landed-cost evidence normalized. "
            "Without verified evidence, cap progression at RFQ_READY.",
        ),
        "followup_cadence_days": FOLLOWUP_CADENCE_DAYS,
        "dormant_after_days": DORMANT_AFTER_DAYS,
        "negotiation": (
            "Formal quotes, price commitments, credit terms, contracts and "
            "WON status require verified evidence and Juan's approval. "
            "Non-binding objection handling may continue.",
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
        ),
    },
    TRACK_MY_CUBA_CASH: {
        "track": TRACK_MY_CUBA_CASH,
        "business_name": "MY CUBA CASH",
        "status": "live",
        "stages": (
            "NEW", "ENGAGED", "QUALIFYING", "QUALIFIED",
            "INTAKE_STARTED", "PENDING_JUAN", "COMPLETED", "LOST", "OPTED_OUT",
        ),
        "qualification_fields": [
            "send_amount", "recipient_name", "recipient_location",
            "delivery_method", "timeline",
        ],
        "matching_rules": (
            "Use ONLY verified intake records from mycubacash.com for a "
            "sender's number. Never invent amounts, statuses, or timelines. "
            "Intake lookup failures are reported plainly, never papered over.",
        ),
        "followup_cadence_days": FOLLOWUP_CADENCE_DAYS,
        "dormant_after_days": DORMANT_AFTER_DAYS,
        "negotiation": (
            "No price negotiation: fees are the published schedule. "
            "Never promise transfer timelines beyond what verified records show.",
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
    for field in book["qualification_fields"]:
        if not state.get(field):
            # Generic, non-invented prompt for the missing field.
            label = field.replace("_", " ")
            if lang == "es":
                return f"¿Me confirmas {label}?"
            return f"Could you confirm the {label}?"
    return None


def is_minimum_qualified(track: str, state: dict[str, Any]) -> bool:
    """True when the track's minimum viable qualification is met."""
    book = get_playbook(track)
    if track == TRACK_CAR_SALES:
        role = state.get("role") or ("seller" if state.get("is_seller") else "buyer")
        if role == "seller":
            return bool(state.get("asking_price") and state.get("fee_agreement"))
        return all(state.get(f) for f in book["buyer_minimum"])
    fields = book["qualification_fields"]
    return all(state.get(f) for f in fields[:3])


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
