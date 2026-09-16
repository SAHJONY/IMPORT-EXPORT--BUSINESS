"""Sofia business-track classifier.

Single WhatsApp front door (+1 281 662 8581) serves two separate businesses:
SAHJONY Import/Export and MY CUBA CASH. Every inbound message is classified
into exactly one track before Sofia replies:

- ``import_export`` — SAHJONY Global Trade (sourcing, suppliers, logistics)
- ``my_cuba_cash``   — MY CUBA CASH (money sends to Cuba, divisas pilot)
- ``ask``            — ambiguous; Sofia asks exactly ONE clarifying question
                       (Spanish unless the user wrote otherwise) and never
                       guesses.

Rules are keyword-signal based and deterministic. Minimum confidence 0.70;
below that the decision is ``ask``. Pure greetings are not classified —
they get the shared track-selection greeting.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

TRACK_IMPORT_EXPORT = "import_export"
TRACK_MY_CUBA_CASH = "my_cuba_cash"
TRACK_ASK = "ask"

MIN_CONFIDENCE = 0.70

# ---------------------------------------------------------------------------
# Signal tables (matched against accent-stripped, lowercased text)
# ---------------------------------------------------------------------------

# Multi-word phrases first (weight 2). Matched phrases are masked out before
# single-word matching so e.g. "pago a proveedor" does not also count as the
# bare import/export word "proveedor".
MY_CUBA_CASH_PHRASES = (
    "enviar dinero",
    "enviarle dinero",
    "envio de dinero",
    "mandar dinero",
    "dinero a cuba",
    "familia en cuba",
    "western union",
    "transferencia a cuba",
    "cuenta en el exterior",
    "comision de envio",
    "send money to cuba",
    "envoyer de l'argent",
    "envio de dinheiro",
    "dinheiro para cuba",
)

# Verb-flexible "pay a supplier" pattern (MIPYME divisas pilot): matches
# "pago a proveedor", "pagarle a un proveedor", "pago al proveedor",
# "pagar a mi proveedor", etc. Weight 2, like the literal phrases.
_PAYER_RE = re.compile(
    r"\bpag(?:o|a|an|ar|ando|ado|arle|amos|uen)\w*"
    r"\s+(?:a(?:l)?\s+|a\s+(?:un|mi|el)\s+)?proveedor(?:es)?\b"
)

MY_CUBA_CASH_WORDS = (
    "remesa",
    "remesas",
    "cubamax",
    "fonmoney",
    "recarga",
    "recargas",
    "piloto",
    "concierge",
    "divisas",
    "tasa",
    "tasas",
)

IMPORT_EXPORT_PHRASES = (
    "licencia de importacion",
    "quiero comprar",
    "sourcing request",
)

IMPORT_EXPORT_WORDS = (
    "cotizacion",
    "cotizaciones",
    "cotizar",
    "importar",
    "importacion",
    "importaciones",
    "exportar",
    "exportacion",
    "exportaciones",
    "proveedor",
    "proveedores",
    "sourcing",
    "mercancia",
    "mercancias",
    "contenedor",
    "contenedores",
    "flete",
    "fletes",
    "aduana",
    "aduanas",
    "arancel",
    "aranceles",
    "logistica",
    "abastecimiento",
    "mayorista",
    "mayoristas",
    "partner",
    "partners",
    "referido",
    "referidos",
    "referral",
    "referrals",
    "rfq",
)

# Context words that resolve the genuinely ambiguous signals below.
_MONEY_CONTEXT = (
    "envio", "enviar", "transferencia", "remesa", "remesas", "dinero",
    "recarga", "tasa", "divisas", "cuba",
)
_TRADE_CONTEXT = (
    "referido", "referidos", "referral", "partner", "proveedor",
    "proveedores", "importar", "exportar", "contenedor", "flete",
)
_PRICE_WORDS = (
    "cuanto cuesta", "cuánto cuesta", "cuanto vale", "qué precio",
    "que precio", "el precio", "what is the price", "how much",
    "combien", "quanto custa",
)
_GREETING_RE = re.compile(
    r"^(hola|buenos dias|buenas tardes|buenas noches|hello|hi|hey|bonjour|ola|oi)[!.…\s]*$"
)

# ---------------------------------------------------------------------------
# Clarifying questions (exactly one is asked when track == "ask")
# ---------------------------------------------------------------------------

_GENERIC_QUESTION = {
    "es": ("Hola, soy Sofia, la asistente de SAHJONY. Puedo ayudarte con "
           "comercio internacional (importar/exportar, proveedores) o con "
           "MY CUBA CASH (envíos de dinero a Cuba). ¿En qué te ayudo hoy?"),
    "en": ("Hi, I'm Sofia, SAHJONY's assistant. I can help with international "
           "trade (import/export, suppliers) or with MY CUBA CASH (sending "
           "money to Cuba). How can I help you today?"),
    "fr": ("Bonjour, je suis Sofia, l'assistante de SAHJONY. Je peux vous aider "
           "avec le commerce international (import/export, fournisseurs) ou avec "
           "MY CUBA CASH (envois d'argent à Cuba). Comment puis-je vous aider ?"),
    "pt": ("Olá, sou Sofia, assistente da SAHJONY. Posso ajudar com comércio "
           "internacional (importação/exportação, fornecedores) ou com "
           "MY CUBA CASH (envio de dinheiro para Cuba). Como posso ajudar?"),
}

_MIPYME_QUESTION = {
    "es": ("¿Buscas importar mercancía para tu MIPYME, o coordinar un pago "
           "en divisas para tu negocio?"),
    "en": ("Are you looking to import goods for your MIPYME, or to coordinate "
           "a foreign-currency payment for your business?"),
    "fr": ("Cherchez-vous à importer des marchandises pour votre MIPYME, ou à "
           "coordonner un paiement en devises pour votre entreprise ?"),
    "pt": ("Você quer importar mercadorias para sua MIPYME ou coordenar um "
           "pagamento em divisas para o seu negócio?"),
}

_PRICE_QUESTION = {
    "es": ("¿Me preguntas por el costo de un envío de dinero a Cuba, o por "
           "una cotización de importación/exportación?"),
    "en": ("Are you asking about the cost of sending money to Cuba, or about "
           "an import/export quote?"),
    "fr": ("Demandez-vous le coût d'un envoi d'argent à Cuba, ou un devis "
           "d'import/export ?"),
    "pt": ("Você está perguntando sobre o custo de um envio de dinheiro para "
           "Cuba ou sobre uma cotação de importação/exportação?"),
}


# Verbs + targets that together form a clear money-send intent even when no
# exact phrase matched (e.g. "enviar 100 dólares a Cuba").
_SEND_VERBS = {"enviar", "envio", "enviarle", "mandar", "mando", "envias"}
_SEND_TARGETS = {"cuba", "dinero", "dolares", "divisas"}


def _strip_accents(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFD", text)
        if unicodedata.category(ch) != "Mn"
    )


def normalize(text: str) -> str:
    """Lowercase, accent-strip, collapse whitespace."""
    text = _strip_accents(text or "").lower()
    return re.sub(r"\s+", " ", text).strip()


def _detect_language(normalized: str) -> str:
    """Crude language detection for the clarifying question. Defaults to es."""
    words = set(re.findall(r"[a-z]+", normalized))
    if words & {"the", "what", "how", "money", "send", "hello", "please", "want", "cost"}:
        return "en"
    if words & {"vous", "je", "comment", "argent", "bonjour", "merci", "envoyer", "cout"}:
        return "fr"
    if words & {"voce", "obrigado", "obrigada", "dinheiro", "quero", "custo"}:
        return "pt"
    return "es"


@dataclass
class TrackDecision:
    track: str  # import_export | my_cuba_cash | ask
    confidence: float
    signals: list[str] = field(default_factory=list)
    clarifying_question: str | None = None
    language: str = "es"


def _phrase_spans(normalized: str, phrases: tuple[str, ...]) -> list[tuple[int, int, str]]:
    spans: list[tuple[int, int, str]] = []
    for phrase in phrases:
        start = 0
        while True:
            idx = normalized.find(phrase, start)
            if idx == -1:
                break
            spans.append((idx, idx + len(phrase), phrase))
            start = idx + len(phrase)
    # Drop spans fully contained in a longer span.
    spans.sort(key=lambda s: (s[1] - s[0]), reverse=True)
    kept: list[tuple[int, int, str]] = []
    for span in spans:
        if not any(k[0] <= span[0] and span[1] <= k[1] for k in kept):
            kept.append(span)
    return kept


def _mask_spans(normalized: str, spans: list[tuple[int, int, str]]) -> str:
    chars = list(normalized)
    for start, end, _ in spans:
        for i in range(start, end):
            chars[i] = " "
    return "".join(chars)


def _word_hits(masked: str, words: tuple[str, ...]) -> list[str]:
    hits: list[str] = []
    for word in words:
        if re.search(rf"\b{re.escape(word)}\b", masked):
            hits.append(word)
    return hits


def classify_track(text: str) -> TrackDecision:
    """Classify one inbound message into a business track."""
    normalized = normalize(text)
    language = _detect_language(normalized)

    def question(kind: str) -> str:
        table = {"generic": _GENERIC_QUESTION, "mipyme": _MIPYME_QUESTION,
                 "price": _PRICE_QUESTION}[kind]
        return table.get(language, table["es"])

    def ask(confidence: float, kind: str) -> TrackDecision:
        return TrackDecision(
            track=TRACK_ASK,
            confidence=confidence,
            signals=[],
            clarifying_question=question(kind),
            language=language,
        )

    if not normalized:
        return ask(0.0, "generic")

    # Pure greeting → shared track-selection greeting, not a classification.
    if _GREETING_RE.match(normalized):
        return ask(0.0, "generic")

    has_mipyme = "mipyme" in normalized or "mipymes" in normalized

    # Score both tracks: phrases weight 2, single words weight 1. Matched
    # phrases are masked before word matching so they are not double-counted.
    cc_spans = _phrase_spans(normalized, MY_CUBA_CASH_PHRASES)
    for match in _PAYER_RE.finditer(normalized):
        cc_spans.append((match.start(), match.end(), "pago_a_proveedor"))
    ie_spans = _phrase_spans(normalized, IMPORT_EXPORT_PHRASES)
    masked = _mask_spans(normalized, cc_spans + ie_spans)
    cc_words = _word_hits(masked, MY_CUBA_CASH_WORDS)
    ie_words = _word_hits(masked, IMPORT_EXPORT_WORDS)

    cc_signals = [f"phrase:{p}" for _, _, p in cc_spans] + [f"word:{w}" for w in cc_words]
    ie_signals = [f"phrase:{p}" for _, _, p in ie_spans] + [f"word:{w}" for w in ie_words]
    cc_score = 2 * len(cc_spans) + len(cc_words)
    ie_score = 2 * len(ie_spans) + len(ie_words)

    # Composite send-money signal: "enviar 100 dólares a Cuba" carries clear
    # money-send intent even without the exact "enviar dinero" phrase.
    if cc_score == 0:
        tokens = set(re.findall(r"[a-z]+", normalized))
        if tokens & _SEND_VERBS and tokens & _SEND_TARGETS:
            cc_score += 2
            cc_signals.append("composite:send_money_cuba")

    # "comisión" alone (no money context, no trade context) is ambiguous.
    if "comision" in normalized:
        has_money = any(w in normalized for w in _MONEY_CONTEXT)
        has_trade = any(w in normalized for w in _TRADE_CONTEXT)
        if not has_money and not has_trade:
            return ask(0.0, "generic")

    # Price question with no track signal → ask which price.
    if any(p in normalized for p in _PRICE_WORDS) and cc_score == 0 and ie_score == 0:
        return ask(0.0, "price")

    # "MIPYME" alone (no decisive signal either way) → ask the MIPYME question.
    if has_mipyme and cc_score == 0 and ie_score == 0:
        return ask(0.0, "mipyme")

    if cc_score == 0 and ie_score == 0:
        kind = "mipyme" if has_mipyme else "generic"
        return ask(0.0, kind)

    if cc_score > 0 and ie_score == 0:
        return TrackDecision(TRACK_MY_CUBA_CASH, 0.90, cc_signals, None, language)
    if ie_score > 0 and cc_score == 0:
        return TrackDecision(TRACK_IMPORT_EXPORT, 0.90, ie_signals, None, language)

    total = cc_score + ie_score
    confidence = max(cc_score, ie_score) / total
    if confidence >= MIN_CONFIDENCE:
        if cc_score > ie_score:
            return TrackDecision(TRACK_MY_CUBA_CASH, round(confidence, 2), cc_signals, None, language)
        return TrackDecision(TRACK_IMPORT_EXPORT, round(confidence, 2), ie_signals, None, language)
    return ask(round(confidence, 2), "mipyme" if has_mipyme else "generic")
