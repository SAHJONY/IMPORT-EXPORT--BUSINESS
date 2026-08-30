from __future__ import annotations

import hashlib
import io
import os
import re
import unicodedata
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, HTTPException
from pypdf import PdfReader

app = FastAPI(title="SAHJONY Cuba MINJUS Registry Ingestion", version="1.0.0", docs_url=None, redoc_url=None)

ORG_ID = "org_sahjony_global_trade"
TARGET_TOTAL = 15000
MINJUS_PRONTUARIO = "https://www.minjus.gob.cu/es/publicaciones/prontuario"
MINJUS_PDF_URL = (
    "https://www.minjus.gob.cu/sites/default/files/archivos/publicacion/2026-03/"
    "Febrero%203.2026%20Relaci%C3%B3n%20MIPYMES%20Y%20CNA%20%203.02.26%20.pdf"
)
SOURCE_NAME = "Febrero 3.2026 Relación MIPYMES Y CNA 3.02.26"

BAD_NAME_TOKENS = {
    "relacion cna mipymes",
    "registro mercantil",
    "denominacion",
    "datos de inscripcion",
    "actividad principal",
    "domicilio social",
    "representante",
    "telefono",
    "correo electronico",
    "tomo folio hoja fecha",
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip(" \t\r\n|;,-")


def _supabase_config() -> tuple[str, str]:
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base_url or not service_key:
        raise RuntimeError("Supabase server credentials are not configured")
    return base_url, service_key


async def _existing_rows() -> list[dict]:
    base_url, service_key = _supabase_config()
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
    }
    rows: list[dict] = []
    offset = 0
    page_size = 1000
    async with httpx.AsyncClient(timeout=35) as client:
        while True:
            response = await client.get(
                f"{base_url}/rest/v1/sahjony_trade_records",
                headers=headers,
                params={
                    "logical_table": "eq.external_trade_prospects",
                    "select": "data",
                    "order": "record_key.asc",
                    "limit": str(page_size),
                    "offset": str(offset),
                },
            )
            response.raise_for_status()
            payload = response.json() if response.content else []
            if not payload:
                break
            for item in payload:
                data = item.get("data") if isinstance(item, dict) else None
                if isinstance(data, dict):
                    rows.append(data)
            if len(payload) < page_size:
                break
            offset += len(payload)
    return rows


def _extract_contact(text: str) -> tuple[str | None, str | None]:
    emails = re.findall(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text, flags=re.I)
    phone_matches = re.findall(r"(?<!\d)(?:\+?53\s*)?(?:5\s*)?\d(?:[\s-]*\d){6,9}(?!\d)", text)
    email = emails[-1].strip().lower() if emails else None
    phone = None
    for raw in reversed(phone_matches):
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("53") and len(digits) >= 10:
            digits = digits[2:]
        if 7 <= len(digits) <= 10:
            phone = digits
            break
    return phone, email


def _plausible_name(name: str) -> bool:
    key = _norm(name)
    if len(key) < 3 or len(key) > 120:
        return False
    if key.isdigit():
        return False
    if any(token in key for token in BAD_NAME_TOKENS):
        return False
    if len(re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", name)) < 3:
        return False
    return True


def _name_from_block(block: str) -> str | None:
    # Strongest pattern for rows written as long-form incorporation descriptions.
    m = re.search(
        r"(?:denominada|denominado)\s+(.{2,120}?)(?=\s+(?:[IVXLCDM]{2,}|\d{1,3}\s+\d{1,3}\s+\d{1,5}|Objeto\s+Social|Actividad\s+Principal|Artículo|Articulo))",
        block,
        flags=re.I | re.S,
    )
    if m:
        candidate = _clean(m.group(1))
        if _plausible_name(candidate):
            return candidate

    first_line = block.splitlines()[0] if block.splitlines() else block
    first_line = re.sub(r"^\s*\d{1,5}\s+", "", first_line).strip()
    # Layout extraction generally separates table columns by 2+ spaces.
    candidate = re.split(r"\s{2,}", first_line, maxsplit=1)[0]
    candidate = _clean(candidate)
    if _plausible_name(candidate):
        return candidate

    # Fallback: consume the text following the row number up to registration metadata.
    flat = _clean(block)
    flat = re.sub(r"^\d{1,5}\s+", "", flat)
    candidate = re.split(
        r"\s+(?:[IVXLCDM]{2,}\s+\d|\d{1,3}\s+\d{1,3}\s+\d{1,5}\s+\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|Objeto\s+Social|Actividad\s+Principal)",
        flat,
        maxsplit=1,
        flags=re.I,
    )[0]
    candidate = _clean(candidate)
    if _plausible_name(candidate):
        return candidate
    return None


def _province_from_text(text: str) -> str | None:
    provinces = [
        "Pinar del Río", "Artemisa", "La Habana", "Mayabeque", "Matanzas",
        "Cienfuegos", "Villa Clara", "Sancti Spíritus", "Ciego de Ávila",
        "Camagüey", "Las Tunas", "Holguín", "Granma", "Santiago de Cuba",
        "Guantánamo", "Isla de la Juventud",
    ]
    normalized = _norm(text)
    for province in provinces:
        if _norm(province) in normalized:
            return province
    return None


def _activity_from_block(block: str) -> str | None:
    flat = _clean(block)
    patterns = [
        r"(?:Actividad Principal|actividad principal)[:.]?\s*(.{20,500}?)(?=\s+(?:Domicilio|DOMICILIO|Representante|REPRESENTANTE|\b[A-ZÁÉÍÓÚÜÑ]{2,}\s+[A-ZÁÉÍÓÚÜÑ]{2,}\b\s+\d{7,}))",
        r"(?:Objeto Social|objeto social)[:.]?\s*(.{20,500}?)(?=\s+(?:Domicilio|DOMICILIO|Representante|REPRESENTANTE))",
    ]
    for pattern in patterns:
        m = re.search(pattern, flat, flags=re.I)
        if m:
            return _clean(m.group(1))[:500]
    # For table-style rows, preserve a bounded evidence excerpt rather than hallucinating a category.
    return flat[:500] if len(flat) >= 20 else None


def _candidate_blocks(pdf_bytes: bytes) -> list[dict]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    candidates: list[dict] = []
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text(extraction_mode="layout") or page.extract_text() or ""
        except Exception:
            text = page.extract_text() or ""
        if not text.strip():
            continue
        lines = text.splitlines()
        starts: list[int] = []
        for idx, line in enumerate(lines):
            if re.match(r"^\s*\d{1,5}\s+\S", line):
                starts.append(idx)
        for pos, start in enumerate(starts):
            end = starts[pos + 1] if pos + 1 < len(starts) else min(len(lines), start + 18)
            block = "\n".join(lines[start:end]).strip()
            if not block:
                continue
            row_match = re.match(r"^\s*(\d{1,5})\s+", lines[start])
            if not row_match:
                continue
            registry_number = row_match.group(1)
            name = _name_from_block(block)
            if not name:
                continue
            phone, email = _extract_contact(block)
            # High-confidence gate: the registry publication is contact-bearing; require at least one contact.
            if not phone and not email:
                continue
            candidates.append({
                "registry_number": registry_number,
                "name": name,
                "phone": phone,
                "email": email,
                "province": _province_from_text(block),
                "activity": _activity_from_block(block),
                "page": page_no,
                "evidence_excerpt": _clean(block)[:900],
            })
    return candidates


async def _bulk_upsert(records: list[dict]) -> int:
    if not records:
        return 0
    base_url, service_key = _supabase_config()
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    written = 0
    async with httpx.AsyncClient(timeout=70) as client:
        for start in range(0, len(records), 300):
            chunk = records[start:start + 300]
            response = await client.post(
                f"{base_url}/rest/v1/sahjony_trade_records",
                params={"on_conflict": "logical_table,record_key"},
                headers=headers,
                json=chunk,
            )
            response.raise_for_status()
            written += len(chunk)
    return written


@app.get("/crm/internal/minjus-source-health")
async def source_health():
    try:
        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            response = await client.get(MINJUS_PDF_URL, headers={"User-Agent": "SAHJONY-CRM-Ingestion/1.0"})
            response.raise_for_status()
            pdf_bytes = response.content
        candidates = _candidate_blocks(pdf_bytes)
        return {
            "status": "ok",
            "source": MINJUS_PDF_URL,
            "source_name": SOURCE_NAME,
            "pdf_bytes": len(pdf_bytes),
            "candidate_rows_high_confidence": len(candidates),
            "pages_with_registry_data": len({c["page"] for c in candidates}),
        }
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MINJUS source health failed: {exc}")


@app.get("/crm/internal/ingest-cuba-minjus-2026")
async def ingest_cuba_minjus_2026():
    try:
        existing_rows = await _existing_rows()
        existing_names = {
            _norm(row.get("buyer_company") or row.get("company_name") or row.get("business_name"))
            for row in existing_rows
            if _norm(row.get("buyer_company") or row.get("company_name") or row.get("business_name"))
        }
        current_count = len(existing_names)
        if current_count >= TARGET_TOTAL:
            return {"status": "already_complete", "current_unique": current_count, "target": TARGET_TOTAL, "inserted": 0}

        async with httpx.AsyncClient(timeout=45, follow_redirects=True) as client:
            response = await client.get(MINJUS_PDF_URL, headers={"User-Agent": "SAHJONY-CRM-Ingestion/1.0"})
            response.raise_for_status()
            pdf_bytes = response.content

        candidates = _candidate_blocks(pdf_bytes)
        now = datetime.now(timezone.utc).isoformat()
        today = datetime.now(timezone.utc).date().isoformat()
        seen = set(existing_names)
        pending: list[dict] = []
        duplicates_skipped = 0
        invalid_skipped = 0

        for candidate in candidates:
            name = candidate["name"]
            name_key = _norm(name)
            if not name_key or not _plausible_name(name):
                invalid_skipped += 1
                continue
            if name_key in seen:
                duplicates_skipped += 1
                continue
            seen.add(name_key)
            province = candidate.get("province")
            registry_number = candidate.get("registry_number")
            record_hash = hashlib.sha1(f"{name_key}|{registry_number}|{_norm(province)}".encode("utf-8")).hexdigest()[:20]
            record_key = f"minjus_rm_20260203:{record_hash}"
            activity = candidate.get("activity")
            phone = candidate.get("phone")
            email = candidate.get("email")
            destination = ", ".join(part for part in (province, "Cuba") if part)
            data = {
                "organization_id": ORG_ID,
                "buyer_company": name,
                "company_name": name,
                "business_name": name,
                "buyer_country": "CU",
                "country": "Cuba",
                "province": province,
                "destination": destination,
                "actor_type": "OTHER_NON_STATE_VERIFIED",
                "primary_activity": activity,
                "activity": activity,
                "product_category": activity,
                "product_description": activity,
                "public_phone": phone,
                "phone": phone,
                "public_email": email,
                "buyer_contact": phone or email,
                "external_reference": f"MINJUS-RM-{registry_number}-P{candidate.get('page')}",
                "source_type": "OFFICIAL_REGISTRY_EXTRACTION",
                "source_platform": "MINJUS Registro Mercantil",
                "source_name": SOURCE_NAME,
                "source_url": MINJUS_PRONTUARIO,
                "extraction_url": MINJUS_PDF_URL,
                "source_provenance": "Name-level extraction from the official MINJUS Registro Mercantil MIPYMES/CNA relation dated 3 February 2026.",
                "verification_status": "PUBLIC_REGISTRY",
                "registry_status": "REGISTERED_AT_PUBLICATION",
                "verification_date": today,
                "outreach_status": "DO_NOT_AUTO_SEND",
                "qualification_stage": "RESEARCH",
                "evidence_summary": candidate.get("evidence_excerpt"),
                "next_action": "Verify current operating status and trade relevance before outreach",
                "created_at": now,
                "updated_at": now,
            }
            pending.append({
                "logical_table": "external_trade_prospects",
                "record_key": record_key,
                "data": data,
                "created_at": now,
                "updated_at": now,
            })
            if current_count + len(pending) >= TARGET_TOTAL:
                break

        written = await _bulk_upsert(pending)
        return {
            "status": "ok",
            "source": MINJUS_PDF_URL,
            "source_name": SOURCE_NAME,
            "current_before": current_count,
            "target": TARGET_TOTAL,
            "candidate_rows_high_confidence": len(candidates),
            "inserted": written,
            "current_after": current_count + written,
            "duplicates_skipped": duplicates_skipped,
            "invalid_skipped": invalid_skipped,
            "shortfall_after": max(0, TARGET_TOTAL - (current_count + written)),
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MINJUS ingestion failed: {exc}")
