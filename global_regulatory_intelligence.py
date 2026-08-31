from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class RegulatoryCheck:
    jurisdiction: str
    topic: str
    status: str
    source_required: bool
    effective_date_required: bool
    evidence_required: list[str]
    notes: str


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


GLOBAL_REGULATORY_TOPICS = [
    "import_controls",
    "export_controls",
    "sanctions_and_restricted_parties",
    "customs_and_tariffs",
    "product_classification_hs_hts",
    "licenses_and_permits",
    "food_and_agriculture_rules",
    "phytosanitary_and_veterinary_rules",
    "labeling_and_packaging",
    "dangerous_goods_and_transport",
    "banking_and_payment_routes",
    "foreign_exchange_controls",
    "tax_vat_gst_duties",
    "incoterms_and_delivery_obligations",
    "anti_bribery_and_aml_kyc",
    "beneficial_ownership_and_counterparty_due_diligence",
    "data_privacy_and_communications",
    "contracts_and_local_commercial_rules",
]


AUTHORITATIVE_SOURCE_CLASSES = [
    "national customs authority",
    "trade/export control authority",
    "sanctions authority",
    "central bank or financial regulator",
    "food/agriculture/veterinary/phytosanitary authority",
    "tax authority",
    "port/transport authority",
    "official gazette or legislation portal",
    "treaty/international organization source when directly applicable",
]


def regulatory_policy() -> dict[str, Any]:
    return {
        "version": "1.0.0",
        "generated_at": _now(),
        "scope": "worldwide_import_export_and_business_operations",
        "topics": GLOBAL_REGULATORY_TOPICS,
        "authoritative_source_classes": AUTHORITATIVE_SOURCE_CLASSES,
        "operating_rules": [
            "Never treat model memory as current legal authority.",
            "Resolve origin, transit, destination, product, parties, payment route, banks, Incoterm and transaction date before making a compliance conclusion.",
            "Prefer primary government/regulatory sources and record source URL, jurisdiction, publication/effective date and retrieval date.",
            "Distinguish law/regulation, regulator guidance, bank policy, carrier policy and commercial preference.",
            "If sources conflict, are stale, or are unavailable, mark the issue unresolved and fail closed.",
            "Do not release binding pricing, payment instructions, contract acceptance, shipment release or a statement of legality without verified evidence for material regulatory issues.",
            "Re-check time-sensitive sanctions, export controls, banking restrictions and licensing rules immediately before transaction release.",
        ],
        "binding_release_requires_verified_regulatory_evidence": True,
        "unknown_or_stale_regulation": "governance_required",
    }


def build_regulatory_checklist(*, origin_country: str | None, transit_countries: list[str] | None, destination_country: str | None, product: str | None, payment_route: str | None = None) -> dict[str, Any]:
    jurisdictions = []
    for value in [origin_country, *(transit_countries or []), destination_country]:
        value = (value or "").strip()
        if value and value not in jurisdictions:
            jurisdictions.append(value)

    if not jurisdictions:
        jurisdictions = ["unresolved"]

    checks: list[RegulatoryCheck] = []
    for jurisdiction in jurisdictions:
        for topic in GLOBAL_REGULATORY_TOPICS:
            checks.append(RegulatoryCheck(
                jurisdiction=jurisdiction,
                topic=topic,
                status="verification_required",
                source_required=True,
                effective_date_required=True,
                evidence_required=[
                    "authoritative source",
                    "effective/publication date",
                    "retrieval timestamp",
                    "applicability note to this transaction",
                ],
                notes="No binding conclusion until evidence is current and transaction-specific.",
            ))

    return {
        "status": "verification_required",
        "origin_country": origin_country,
        "transit_countries": transit_countries or [],
        "destination_country": destination_country,
        "product": product,
        "payment_route": payment_route,
        "jurisdictions": jurisdictions,
        "checks": [asdict(c) for c in checks],
        "release_allowed": False,
        "next_action": "Retrieve and verify current authoritative regulatory evidence for every material jurisdiction/topic before binding release.",
    }


def can_release_transaction(*, verified_checks: list[dict[str, Any]]) -> dict[str, Any]:
    material_failures = []
    for check in verified_checks or []:
        if str(check.get("status") or "").lower() not in {"verified", "not_applicable"}:
            material_failures.append({
                "jurisdiction": check.get("jurisdiction"),
                "topic": check.get("topic"),
                "status": check.get("status"),
            })
    return {
        "release_allowed": len(material_failures) == 0 and bool(verified_checks),
        "unresolved": material_failures,
        "decision": "verified" if len(material_failures) == 0 and bool(verified_checks) else "governance_required",
    }
