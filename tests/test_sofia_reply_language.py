"""Tests for Sofia's WhatsApp reply-language handling.

Regression: Sofia answered in English when the customer wrote in Spanish.
The reply path now prepends an explicit LANGUAGE RULE to the system prompt
so the model answers in the customer's language.
"""
from sofia_track_classifier import detect_language
from sofia_whatsapp_runtime import (
    detect_reply_language,
    language_rule,
    reply_language_name,
)


def test_detect_language_spanish():
    assert detect_language("Hola, quiero enviar dinero a mi familia en Cuba") == "es"
    assert detect_language("¿Cuánto cuesta enviar 100 dólares?") == "es"
    assert detect_language("Necesito cotizar arroz y diésel") == "es"


def test_detect_language_english():
    assert detect_language("Hello, I want to send money to Cuba") == "en"
    assert detect_language("What is the cost please?") == "en"


def test_detect_language_french_portuguese():
    assert detect_language("Bonjour, je veux envoyer de l'argent") == "fr"
    assert detect_language("Quero enviar dinheiro para Cuba") == "pt"


def test_detect_language_defaults_to_spanish():
    assert detect_language("...") == "es"
    assert detect_language("") == "es"


def test_reply_language_latest_message_wins():
    transcript = "customer: Hello, I need a quote\nsofia: Hello! How can I help?"
    assert detect_reply_language("¿Cuánto cuesta el flete?", transcript) == "es"
    assert detect_reply_language("What is the freight cost?", transcript) == "en"


def test_reply_language_short_message_inherits_transcript():
    transcript = (
        "customer: Hola, quiero importar arroz\n"
        "sofia: ¡Hola! Con gusto le ayudo con su importación de arroz."
    )
    assert detect_reply_language("ok", transcript) == "es"
    assert detect_reply_language("sí", transcript) == "es"
    assert detect_reply_language("gracias", transcript) == "es"


def test_reply_language_short_message_english_transcript():
    transcript = (
        "customer: Hello, I want to import rice\n"
        "sofia: Hello! I can help with your rice import."
    )
    assert detect_reply_language("ok", transcript) == "en"


def test_reply_language_defaults_spanish_without_history():
    assert detect_reply_language("ok") == "es"


def test_language_rule_spanish_is_explicit():
    rule = language_rule("Hola, necesito ayuda con un envío")
    assert "SPANISH" in rule
    assert "Write your ENTIRE reply in Spanish" in rule
    assert "Do NOT reply in English" in rule


def test_language_rule_english():
    rule = language_rule("Hello, I need help with a shipment")
    assert "ENGLISH" in rule
    assert "Write your ENTIRE reply in English" in rule


def test_reply_language_name():
    assert reply_language_name("Hola") == "Spanish"
    assert reply_language_name("Hello, I want to send money") == "English"
    assert reply_language_name("Bonjour") == "French"
    assert reply_language_name("Quero enviar") == "Portuguese"
