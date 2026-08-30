from __future__ import annotations

import hashlib
import io
import os
import re
import unicodedata
import zipfile
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import httpx
from fastapi import FastAPI, HTTPException

from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Cuba Private Sector CRM", version="1.7.1", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"
TARGET_TOTAL = 5000
ACCUMULATED_XLSX_URL = (
    "https://www.ipscuba.net/especial/nuevos-actores-economicos/assets/store/files/"
    "Listado-de-Nuevos-Actores-Econ%C3%B3micos-aprobados-mayo-2024.xlsx"
)
OFFICIAL_MEP_ARCHIVE = "https://t.me/actores_economicos_cuba"

_PRIVATE_ACTOR_TYPES = {
    "MIPYME_PRIVADA",
    "CNA",
    "EMPRESA_PRIVADA",
    "OTHER_NON_STATE_VERIFIED",
}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _is_mipyme(row: dict) -> bool:
    src = " ".join([
        str(row.get("source_platform") or ""),
        str(row.get("source_type") or ""),
        str(row.get("source_name") or ""),
        str(row.get("source_provenance") or ""),
        str(row.get("external_reference") or ""),
        str(row.get("evidence_summary") or ""),
    ]).lower()
    name = str(row.get("buyer_company") or row.get("company_name") or row.get("business_name") or "").strip()
    actor_type = str(row.get("actor_type") or "").upper().strip()
    if not name:
        return False
    lowered_name = name.lower()
    if lowered_name.startswith("minjus registro mercantil") or lowered_name.startswith("public mipyme/cna registry"):
        return False
    if actor_type in _PRIVATE_ACTOR_TYPES:
        return True
    return (
        "minjus" in src
        or "registro mercantil" in src
        or "ministerio de economía y planificación" in src
        or "ministerio de economia y planificacion" in src
        or "mep public" in src
        or "actores económicos" in src
        or "actores economicos" in src
        or str(row.get("external_reference") or "").upper().startswith("RM-")
    )


def _public_record(row: dict) -> dict:
    normalized = dict(row)
    normalized.setdefault("buyer_company", row.get("company_name") or row.get("business_name"))
    normalized.setdefault("buyer_country", row.get("country") or "Cuba")
    normalized.setdefault("product_category", row.get("primary_activity") or row.get("activity"))
    normalized.setdefault("product_description", row.get("activity") or row.get("primary_activity"))
    if not normalized.get("destination"):
        municipality = str(row.get("municipality") or "").strip()
        province = str(row.get("province") or "").strip()
        normalized["destination"] = ", ".join(part for part in (municipality, province, "Cuba") if part)
    normalized.setdefault("buyer_contact", row.get("public_phone") or row.get("phone") or row.get("contact"))
    allowed = [
        "id", "prospect_id", "external_reference", "buyer_company", "buyer_name",
        "buyer_country", "buyer_contact", "public_email", "public_phone", "website",
        "whatsapp", "whatsapp_status", "facebook", "instagram", "linkedin", "telegram",
        "social_media", "social_media_status", "actor_type", "province", "municipality",
        "opportunity_title", "product_category", "product_description", "destination",
        "source_type", "source_platform", "source_name", "source_provenance", "source_url",
        "verification_status", "registry_status", "verification_date", "qualification_stage",
        "risk_level", "import_export_relevance", "evidence_summary", "next_action",
        "created_at", "updated_at",
    ]
    return {k: normalized.get(k) for k in allowed}


def _supabase_config() -> tuple[str, str]:
    base_url = os.getenv("SUPABASE_URL", "").rstrip("/")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    if not base_url or not service_key:
        raise RuntimeError("Supabase server credentials are not configured")
    return base_url, service_key


async def _supabase_rows() -> list[dict]:
    base_url, service_key = _supabase_config()
    headers = {
        "apikey": service_key,
        "Authorization": f"Bearer {service_key}",
        "Accept": "application/json",
    }
    params = {
        "logical_table": "eq.external_trade_prospects",
        "select": "data",
        "limit": "10000",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{base_url}/rest/v1/sahjony_trade_records", headers=headers, params=params)
        response.raise_for_status()
        payload = response.json() if response.content else []
    rows: list[dict] = []
    for item in payload:
        data = item.get("data") if isinstance(item, dict) else None
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _xlsx_rows(content: bytes) -> list[list[str]]:
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iterfind(".//m:t", ns)))
        sheet_path = "xl/worksheets/sheet1.xml"
        if sheet_path not in zf.namelist():
            candidates = sorted(name for name in zf.namelist() if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"))
            if not candidates:
                raise ValueError("No worksheet found in XLSX")
            sheet_path = candidates[0]
        root = ET.fromstring(zf.read(sheet_path))
        rows: list[list[str]] = []
        for row in root.findall(".//m:sheetData/m:row", ns):
            cells: dict[int, str] = {}
            for cell in row.findall("m:c", ns):
                ref = cell.attrib.get("r", "A1")
                letters = re.match(r"[A-Z]+", ref)
                if not letters:
                    continue
                col = 0
                for ch in letters.group(0):
                    col = col * 26 + (ord(ch) - 64)
                col -= 1
                cell_type = cell.attrib.get("t")
                value = ""
                if cell_type == "inlineStr":
                    value = "".join(t.text or "" for t in cell.iterfind(".//m:t", ns))
                else:
                    vnode = cell.find("m:v", ns)
                    if vnode is not None and vnode.text is not None:
                        raw = vnode.text
                        if cell_type == "s":
                            try:
                                value = shared[int(raw)]
                            except Exception:
                                value = raw
                        else:
                            value = raw
                cells[col] = value.strip()
            if cells:
                width = max(cells) + 1
                rows.append([cells.get(i, "") for i in range(width)])
        return rows


def _find_columns(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    aliases = {
        "name": ("denominacion", "nombre"),
        "province": ("provincia",),
        "municipality": ("municipio",),
        "type": ("tipo de sujeto", "tipo sujeto", "sujeto"),
        "activity": ("actividad principal", "actividad economica principal", "actividad"),
    }
    for idx, row in enumerate(rows[:80]):
        normalized = [_norm(v) for v in row]
        found: dict[str, int] = {}
        for key, needles in aliases.items():
            for cidx, value in enumerate(normalized):
                if any(needle in value for needle in needles):
                    found[key] = cidx
                    break
        if "name" in found and "type" in found and "activity" in found:
            return idx, found
    raise ValueError("Could not identify actor-list headers")


def _cell(row: list[str], index: int | None) -> str:
    return row[index].strip() if index is not None and index < len(row) else ""


def _private_actor(actor_type_raw: str) -> tuple[bool, str]:
    t = _norm(actor_type_raw)
    if "estatal" in t:
        return False, ""
    if "cna" in t or "cooperativa no agropecuaria" in t:
        return True, "CNA"
    if "privada" in t or "mipyme" in t:
        return True, "MIPYME_PRIVADA"
    return False, ""


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
    async with httpx.AsyncClient(timeout=60) as client:
        for start in range(0, len(records), 200):
            chunk = records[start:start + 200]
            response = await client.post(
                f"{base_url}/rest/v1/sahjony_trade_records",
                params={"on_conflict": "logical_table,record_key"},
                headers=headers,
                json=chunk,
            )
            response.raise_for_status()
            written += len(chunk)
    return written


async def _records() -> list[dict]:
    rows: list[dict] = []
    try:
        rows = await _supabase_rows()
    except Exception:
        rows = []
    if not rows:
        backend = get_backend()
        rows = await backend.select(
            "external_trade_prospects",
            params={"organization_id": f"eq.{ORG_ID}", "order": "created_at.desc", "limit": "10000"},
        ) or []
    filtered = []
    for r in rows:
        row = dict(r)
        if str(row.get("organization_id") or ORG_ID) != ORG_ID:
            continue
        if _is_mipyme(row):
            filtered.append(_public_record(row))
    filtered.sort(key=lambda r: (str(r.get("buyer_company") or "").casefold(), str(r.get("external_reference") or "")))
    return filtered


@app.get("/crm/internal/ingest-cuba-actors-3000")
async def ingest_cuba_actors_3000():
    existing_rows = await _supabase_rows()
    existing_names = {
        _norm(row.get("buyer_company") or row.get("company_name") or row.get("business_name"))
        for row in existing_rows
        if _norm(row.get("buyer_company") or row.get("company_name") or row.get("business_name"))
    }
    current_count = len(existing_names)
    if current_count >= TARGET_TOTAL:
        return {"status": "already_complete", "current_unique": current_count, "target": TARGET_TOTAL, "inserted": 0}

    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(ACCUMULATED_XLSX_URL, headers={"User-Agent": "SAHJONY-CRM-Ingestion/1.0"})
        response.raise_for_status()
        content = response.content
    rows = _xlsx_rows(content)
    header_idx, cols = _find_columns(rows)
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    pending: list[dict] = []
    seen = set(existing_names)
    skipped_state = 0
    skipped_duplicate = 0
    skipped_invalid = 0

    for row in rows[header_idx + 1:]:
        name = _cell(row, cols.get("name"))
        actor_type_raw = _cell(row, cols.get("type"))
        activity = _cell(row, cols.get("activity"))
        province = _cell(row, cols.get("province"))
        municipality = _cell(row, cols.get("municipality"))
        is_private, actor_type = _private_actor(actor_type_raw)
        if not is_private:
            if "estatal" in _norm(actor_type_raw):
                skipped_state += 1
            continue
        name_key = _norm(name)
        if not name_key or len(name_key) < 2:
            skipped_invalid += 1
            continue
        if name_key in seen:
            skipped_duplicate += 1
            continue
        seen.add(name_key)
        record_hash = hashlib.sha1(f"{name_key}|{_norm(province)}".encode("utf-8")).hexdigest()[:20]
        record_key = f"mep_accumulated_may2024:{record_hash}"
        destination = ", ".join(part for part in (municipality, province, "Cuba") if part)
        data = {
            "organization_id": ORG_ID,
            "buyer_company": name,
            "company_name": name,
            "business_name": name,
            "buyer_country": "CU",
            "country": "Cuba",
            "province": province or None,
            "municipality": municipality or None,
            "destination": destination,
            "actor_type": actor_type,
            "primary_activity": activity or None,
            "activity": activity or None,
            "product_category": activity or None,
            "product_description": activity or None,
            "source_type": "OFFICIAL_ACTOR_LIST_EXTRACTION",
            "source_platform": "MEP official actor-list archive",
            "source_name": "Listado acumulado de Nuevos Actores Económicos aprobados desde 2021 hasta mayo 2024",
            "source_url": OFFICIAL_MEP_ARCHIVE,
            "extraction_url": ACCUMULATED_XLSX_URL,
            "source_provenance": "Name-level extraction from the downloadable accumulated approved-actors Excel; official MEP actor-list archive is retained as canonical approval provenance.",
            "verification_status": "RESEARCH",
            "registry_status": "VERIFY",
            "verification_date": today,
            "outreach_status": "DO_NOT_AUTO_SEND",
            "qualification_stage": "RESEARCH",
            "evidence_summary": "Public approved-actor listing provides business name, actor type, activity and territorial fields. Approval/listing does not prove current ACTIVE status or buyer demand.",
            "next_action": "Corroborate current status in MINJUS/INAENE and enrich public business contacts",
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
    final_unique = current_count + written
    return {
        "status": "ok",
        "source_rows": len(rows),
        "current_before": current_count,
        "target": TARGET_TOTAL,
        "inserted": written,
        "current_after": final_unique,
        "duplicates_skipped": skipped_duplicate,
        "state_entities_skipped": skipped_state,
        "invalid_skipped": skipped_invalid,
        "source": ACCUMULATED_XLSX_URL,
    }


@app.get("/cuba-mipymes-api/health")
@app.get("/crm/cuba-mipymes/health")
async def health():
    records = await _records()
    return {
        "status": "ok",
        "service": "cuba-private-sector-read-only-crm",
        "record_count": len(records),
        "source_scope": "public_registry_and_official_actor_lists_research",
        "binding_actions": False,
    }


@app.get("/cuba-mipymes-api/list")
@app.get("/crm/cuba-mipymes")
@app.get("/crm/cuba-mipymes/list")
async def list_mipymes():
    records = await _records()
    return {
        "status": "ok",
        "count": len(records),
        "records": records,
        "classification": "RESEARCH / VERIFIED PUBLIC SOURCE",
        "notice": "A listed or registered private-sector actor is not a qualified buyer or current RFQ unless separately verified.",
    }
