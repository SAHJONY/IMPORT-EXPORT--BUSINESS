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
from fastapi import FastAPI
from pypdf import PdfReader

from insforge_backend import get_backend

app = FastAPI(title="SAHJONY Cuba Private Sector CRM", version="2.0.0", docs_url=None, redoc_url=None)
ORG_ID = "org_sahjony_global_trade"
TARGET_TOTAL = 15000
ACCUMULATED_XLSX_URL = (
    "https://www.ipscuba.net/especial/nuevos-actores-economicos/assets/store/files/"
    "Listado-de-Nuevos-Actores-Econ%C3%B3micos-aprobados-mayo-2024.xlsx"
)
OFFICIAL_MEP_ARCHIVE = "https://t.me/actores_economicos_cuba"
MINJUS_PRONTUARIO = "https://www.minjus.gob.cu/es/publicaciones/prontuario"
MINJUS_2026_02_PDF = (
    "https://www.minjus.gob.cu/sites/default/files/archivos/publicacion/2026-03/"
    "Febrero%203.2026%20Relaci%C3%B3n%20MIPYMES%20Y%20CNA%20%203.02.26%20.pdf"
)

_PRIVATE_ACTOR_TYPES = {"MIPYME_PRIVADA", "CNA", "EMPRESA_PRIVADA", "OTHER_NON_STATE_VERIFIED"}


def _norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip(" \t\r\n,;:-")


def _is_mipyme(row: dict) -> bool:
    src = " ".join(str(row.get(k) or "") for k in (
        "source_platform", "source_type", "source_name", "source_provenance", "external_reference", "evidence_summary"
    )).lower()
    name = str(row.get("buyer_company") or row.get("company_name") or row.get("business_name") or "").strip()
    actor_type = str(row.get("actor_type") or "").upper().strip()
    if not name:
        return False
    lowered = name.lower()
    if lowered.startswith("minjus registro mercantil") or lowered.startswith("public mipyme/cna registry"):
        return False
    if actor_type in _PRIVATE_ACTOR_TYPES:
        return True
    return (
        "minjus" in src or "registro mercantil" in src or "ministerio de economía y planificación" in src
        or "ministerio de economia y planificacion" in src or "mep public" in src
        or "actores económicos" in src or "actores economicos" in src
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

    has_explicit_owner = bool(
        normalized.get("legal_owners") or normalized.get("legal_owner")
        or normalized.get("beneficial_owners") or normalized.get("beneficial_owner")
        or normalized.get("ubo") or normalized.get("shareholders") or normalized.get("partners")
    )
    normalized.setdefault(
        "ownership_verification_status",
        "PUBLIC_SOURCE_VERIFIED" if has_explicit_owner else "NOT_PUBLICLY_VERIFIED",
    )
    if not has_explicit_owner:
        normalized.setdefault(
            "ownership_note",
            "No public source currently linked to this CRM record establishes legal or beneficial ownership. A public representative is not treated as an owner unless the source explicitly establishes ownership.",
        )

    allowed = [
        "id", "prospect_id", "external_reference", "buyer_company", "buyer_name", "buyer_country", "buyer_contact",
        "public_email", "public_phone", "website", "whatsapp", "whatsapp_status", "facebook", "instagram", "linkedin",
        "telegram", "social_media", "social_media_status", "actor_type", "province", "municipality", "opportunity_title",
        "product_category", "product_description", "destination", "source_type", "source_platform", "source_name",
        "source_provenance", "source_url", "verification_status", "registry_status", "verification_date",
        "qualification_stage", "risk_level", "import_export_relevance", "evidence_summary", "next_action",
        "legal_owner", "legal_owners", "beneficial_owner", "beneficial_owners", "ubo", "partners", "shareholders",
        "ownership_percentage", "public_representative", "representative_role", "ownership_source_url",
        "ownership_source_reference", "ownership_verification_status", "ownership_note", "ownership_verified_at",
        "created_at", "updated_at"
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
    headers = {"apikey": service_key, "Authorization": f"Bearer {service_key}", "Accept": "application/json"}
    rows: list[dict] = []
    page_size = 1000
    offset = 0
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            response = await client.get(
                f"{base_url}/rest/v1/sahjony_trade_records",
                headers=headers,
                params={
                    "logical_table": "eq.external_trade_prospects", "select": "record_key,data", "order": "record_key.asc",
                    "limit": str(page_size), "offset": str(offset),
                },
            )
            response.raise_for_status()
            payload = response.json() if response.content else []
            if not payload:
                break
            for item in payload:
                data = item.get("data") if isinstance(item, dict) else None
                if isinstance(data, dict):
                    row = dict(data)
                    row["_record_key"] = item.get("record_key")
                    rows.append(row)
            if len(payload) < page_size:
                break
            offset += len(payload)
    return rows


async def _bulk_upsert(records: list[dict]) -> int:
    if not records:
        return 0
    base_url, service_key = _supabase_config()
    headers = {
        "apikey": service_key, "Authorization": f"Bearer {service_key}", "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    written = 0
    async with httpx.AsyncClient(timeout=60) as client:
        for start in range(0, len(records), 200):
            chunk = records[start:start + 200]
            response = await client.post(
                f"{base_url}/rest/v1/sahjony_trade_records",
                params={"on_conflict": "logical_table,record_key"}, headers=headers, json=chunk,
            )
            response.raise_for_status()
            written += len(chunk)
    return written


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
            candidates = sorted(n for n in zf.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
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
                value = ""
                cell_type = cell.attrib.get("t")
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
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        return rows


def _find_columns(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    aliases = {
        "name": ("denominacion", "nombre"), "province": ("provincia",), "municipality": ("municipio",),
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


def _province_from_page(text: str) -> str | None:
    match = re.search(r"REGISTRO\s+MERCANTIL\s+([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ .'-]{2,40}?)\s+\d{1,2}[./]\d{1,2}[./]\d{2,4}", text, re.I)
    return _clean(match.group(1)).title() if match else None


def _extract_minjus_name(block: str) -> str | None:
    compact = _clean(block)
    patterns = [
        r"denominad[ao]\s+(.+?)(?=\s+[IVXLCDM]{1,10}\s+\d{1,4}\s+\d{1,6}\s+\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        r"^\d{1,5}\s+(.+?)(?=\s+[IVXLCDM]{1,10}\s+\d{1,4}\s+\d{1,6}\s+\d{1,2}[./]\d{1,2}[./]\d{2,4})",
    ]
    for pattern in patterns:
        m = re.search(pattern, compact, re.I)
        if not m:
            continue
        name = _clean(m.group(1))
        name = re.sub(r"^(?:Sociedad Mercantil\s+)?(?:Estatal,?\s+)?(?:bajo la forma de\s+)?(?:Sociedad\s+)?(?:Unipersonal\s+)?(?:de\s+Responsabilidad\s+Limitada,?\s+)?(?:de nacionalidad cubana,?\s+)?(?:en su forma abreviada\s+)?", "", name, flags=re.I)
        name = _clean(name)
        if 2 <= len(name) <= 160 and re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]", name):
            return name
    return None


def _extract_minjus_activity(block: str) -> str | None:
    compact = _clean(block)
    m = re.search(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}\s+(.+?)(?=\s+Domicilio(?:\s+Social)?\b|\s+DOMICILIO\s+SOCIAL\b)", compact, re.I)
    if not m:
        return None
    activity = _clean(m.group(1))
    return activity[:1400] if activity else None


def _extract_minjus_representative(block: str) -> str | None:
    compact = _clean(block)
    patterns = [
        r"Representante(?:\s+Legal)?\s*[:.-]?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑáéíóúüñ .'-]{4,100}?)(?=\s+(?:Tel[eé]fono|M[oó]vil|Correo|Email|E-mail|Domicilio|Actividad|Objeto|$))",
        r"REPRESENTANTE(?:\s+LEGAL)?\s*[:.-]?\s*([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ .'-]{4,100}?)(?=\s+(?:TEL[EÉ]FONO|M[ÓO]VIL|CORREO|EMAIL|DOMICILIO|ACTIVIDAD|OBJETO|$))",
    ]
    for pattern in patterns:
        match = re.search(pattern, compact, re.I)
        if not match:
            continue
        candidate = _clean(match.group(1))
        words = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ'-]+", candidate)
        if 2 <= len(words) <= 8 and len(candidate) <= 100:
            return candidate
    return None


def _extract_minjus_candidates(content: bytes) -> tuple[list[dict], int]:
    reader = PdfReader(io.BytesIO(content))
    candidates: list[dict] = []
    seen: set[str] = set()
    for page_no, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text(extraction_mode="layout") or page.extract_text() or ""
        except TypeError:
            text = page.extract_text() or ""
        province = _province_from_page(text)
        starts = list(re.finditer(r"(?m)^\s*(\d{1,5})\s+(?=\S)", text))
        for idx, match in enumerate(starts):
            block = text[match.start(): starts[idx + 1].start() if idx + 1 < len(starts) else len(text)]
            lowered = _norm(block[:500])
            if not any(token in lowered for token in ("s r l", "s u r l", "srl", "surl", "sociedad mercantil", "cna", "cooperativa")):
                continue
            if "estatal" in lowered and "privada" not in lowered:
                continue
            name = _extract_minjus_name(block)
            if not name:
                continue
            key = _norm(name)
            if not key or key in seen:
                continue
            seen.add(key)
            email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", block, re.I)
            phones = re.findall(r"(?<!\d)(?:\+?53\s*)?(\d{8,10})(?!\d)", block)
            actor_type = "CNA" if ("cna" in lowered or "cooperativa no agropecuaria" in lowered) else "MIPYME_PRIVADA"
            candidates.append({
                "registry_number": match.group(1), "name": name, "province": province, "page": page_no,
                "actor_type": actor_type, "activity": _extract_minjus_activity(block),
                "public_email": email_match.group(0) if email_match else None,
                "public_phone": phones[-1] if phones else None,
                "public_representative": _extract_minjus_representative(block),
            })
    return candidates, len(reader.pages)


async def _download(url: str, timeout: int = 90) -> bytes:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": "SAHJONY-CRM-Ingestion/2.0"})
        response.raise_for_status()
        return response.content


async def _records() -> list[dict]:
    rows: list[dict] = []
    try:
        rows = await _supabase_rows()
    except Exception:
        rows = []
    if not rows:
        backend = get_backend()
        rows = await backend.select("external_trade_prospects", params={"organization_id": f"eq.{ORG_ID}", "order": "created_at.desc", "limit": "20000"}) or []
    filtered: list[dict] = []
    seen: set[str] = set()
    for r in rows:
        row = dict(r)
        if str(row.get("organization_id") or ORG_ID) != ORG_ID or not _is_mipyme(row):
            continue
        name_key = _norm(row.get("buyer_company") or row.get("company_name") or row.get("business_name"))
        if not name_key or name_key in seen:
            continue
        seen.add(name_key)
        filtered.append(_public_record(row))
    filtered.sort(key=lambda r: (str(r.get("buyer_company") or "").casefold(), str(r.get("external_reference") or "")))
    return filtered


@app.get("/crm/internal/ingest-cuba-actors-3000")
async def ingest_cuba_actors_3000():
    existing_rows = await _supabase_rows()
    existing_names = {_norm(r.get("buyer_company") or r.get("company_name") or r.get("business_name")) for r in existing_rows}
    existing_names.discard("")
    current_count = len(existing_names)
    if current_count >= TARGET_TOTAL:
        return {"status": "already_complete", "current_unique": current_count, "target": TARGET_TOTAL, "inserted": 0}
    rows = _xlsx_rows(await _download(ACCUMULATED_XLSX_URL, 60))
    header_idx, cols = _find_columns(rows)
    now = datetime.now(timezone.utc).isoformat()
    today = datetime.now(timezone.utc).date().isoformat()
    pending: list[dict] = []
    seen = set(existing_names)
    skipped_state = skipped_duplicate = skipped_invalid = 0
    for row in rows[header_idx + 1:]:
        name = _cell(row, cols.get("name")); actor_type_raw = _cell(row, cols.get("type")); activity = _cell(row, cols.get("activity"))
        province = _cell(row, cols.get("province")); municipality = _cell(row, cols.get("municipality"))
        is_private, actor_type = _private_actor(actor_type_raw)
        if not is_private:
            if "estatal" in _norm(actor_type_raw): skipped_state += 1
            continue
        name_key = _norm(name)
        if not name_key or len(name_key) < 2:
            skipped_invalid += 1; continue
        if name_key in seen:
            skipped_duplicate += 1; continue
        seen.add(name_key)
        record_hash = hashlib.sha1(f"{name_key}|{_norm(province)}".encode()).hexdigest()[:20]
        destination = ", ".join(part for part in (municipality, province, "Cuba") if part)
        data = {
            "organization_id": ORG_ID, "buyer_company": name, "company_name": name, "business_name": name,
            "buyer_country": "CU", "country": "Cuba", "province": province or None, "municipality": municipality or None,
            "destination": destination, "actor_type": actor_type, "primary_activity": activity or None,
            "activity": activity or None, "product_category": activity or None, "product_description": activity or None,
            "source_type": "OFFICIAL_ACTOR_LIST_EXTRACTION", "source_platform": "MEP official actor-list archive",
            "source_name": "Listado acumulado de Nuevos Actores Económicos aprobados desde 2021 hasta mayo 2024",
            "source_url": OFFICIAL_MEP_ARCHIVE, "extraction_url": ACCUMULATED_XLSX_URL,
            "source_provenance": "Name-level extraction from the downloadable accumulated approved-actors Excel.",
            "verification_status": "RESEARCH", "registry_status": "VERIFY", "verification_date": today,
            "ownership_verification_status": "NOT_PUBLICLY_VERIFIED",
            "ownership_note": "The MEP accumulated actor list does not establish legal or beneficial ownership for this record.",
            "outreach_status": "DO_NOT_AUTO_SEND", "qualification_stage": "RESEARCH",
            "evidence_summary": "Public approved-actor listing provides business name, actor type, activity and territorial fields.",
            "next_action": "Corroborate current status in MINJUS/INAENE and enrich public business contacts and ownership evidence",
            "created_at": now, "updated_at": now,
        }
        pending.append({"logical_table": "external_trade_prospects", "record_key": f"mep_accumulated_may2024:{record_hash}", "data": data, "created_at": now, "updated_at": now})
        if current_count + len(pending) >= TARGET_TOTAL:
            break
    written = await _bulk_upsert(pending)
    return {
        "status": "ok", "source_rows": len(rows), "current_before": current_count, "target": TARGET_TOTAL,
        "inserted": written, "current_after": current_count + written, "duplicates_skipped": skipped_duplicate,
        "state_entities_skipped": skipped_state, "invalid_skipped": skipped_invalid, "source": ACCUMULATED_XLSX_URL,
    }


@app.get("/crm/cuba-mipymes/internal/preview-minjus-2026")
async def preview_minjus_2026():
    candidates, pages = _extract_minjus_candidates(await _download(MINJUS_2026_02_PDF))
    existing = {_norm(r.get("buyer_company") or r.get("company_name") or r.get("business_name")) for r in await _supabase_rows()}
    new_candidates = [c for c in candidates if _norm(c["name"]) not in existing]
    return {
        "status": "ok", "source": MINJUS_2026_02_PDF, "official_index": MINJUS_PRONTUARIO,
        "pages": pages, "parsed_unique": len(candidates), "new_vs_crm": len(new_candidates),
        "representatives_found": sum(1 for c in candidates if c.get("public_representative")),
        "sample": new_candidates[:25],
    }


@app.get("/crm/cuba-mipymes/internal/ingest-minjus-2026")
async def ingest_minjus_2026():
    existing_rows = await _supabase_rows()
    existing_names = {_norm(r.get("buyer_company") or r.get("company_name") or r.get("business_name")) for r in existing_rows}
    existing_names.discard("")
    current_count = len(existing_names)
    if current_count >= TARGET_TOTAL:
        return {"status": "already_complete", "current_unique": current_count, "target": TARGET_TOTAL, "inserted": 0}
    candidates, pages = _extract_minjus_candidates(await _download(MINJUS_2026_02_PDF))
    now = datetime.now(timezone.utc).isoformat(); today = datetime.now(timezone.utc).date().isoformat()
    pending: list[dict] = []
    seen = set(existing_names)
    duplicates = 0
    for c in candidates:
        key = _norm(c["name"])
        if not key or key in seen:
            duplicates += 1; continue
        seen.add(key)
        record_hash = hashlib.sha1(f"{key}|{c.get('registry_number')}|{c.get('province')}".encode()).hexdigest()[:20]
        activity = c.get("activity")
        representative = c.get("public_representative")
        data = {
            "organization_id": ORG_ID, "buyer_company": c["name"], "company_name": c["name"], "business_name": c["name"],
            "buyer_country": "CU", "country": "Cuba", "province": c.get("province"), "destination": ", ".join(x for x in (c.get("province"), "Cuba") if x),
            "actor_type": c.get("actor_type") or "MIPYME_PRIVADA", "primary_activity": activity, "activity": activity,
            "product_category": activity, "product_description": activity, "public_email": c.get("public_email"),
            "public_phone": c.get("public_phone"), "buyer_contact": c.get("public_phone") or c.get("public_email"),
            "public_representative": representative, "representative_role": "PUBLIC_REGISTRY_REPRESENTATIVE" if representative else None,
            "ownership_verification_status": "NOT_PUBLICLY_VERIFIED",
            "ownership_note": "MINJUS may identify a public representative, but this does not establish legal or beneficial ownership unless ownership is explicitly stated by the source.",
            "ownership_source_url": MINJUS_2026_02_PDF if representative else None,
            "ownership_source_reference": f"page {c.get('page')}" if representative else None,
            "external_reference": f"RM-{c.get('province') or 'CU'}-{c.get('registry_number')}",
            "source_type": "OFFICIAL_REGISTRY_EXTRACTION", "source_platform": "MINJUS Registro Mercantil",
            "source_name": "Relación CNA-MIPYMES Registro Mercantil 03.02.2026", "source_url": MINJUS_2026_02_PDF,
            "source_provenance": f"Name-level extraction from official MINJUS Registro Mercantil PDF, page {c.get('page')}.",
            "verification_status": "PUBLIC_REGISTRY", "registry_status": "REGISTERED", "verification_date": today,
            "outreach_status": "DO_NOT_AUTO_SEND", "qualification_stage": "RESEARCH",
            "evidence_summary": "Official Registro Mercantil listing provides company identity and may provide a public representative, contact and business activity. Registration does not prove current buyer demand or ownership.",
            "next_action": "Enrich and qualify for import-export relevance; verify ownership separately before treating any person as owner/UBO", "created_at": now, "updated_at": now,
        }
        pending.append({"logical_table": "external_trade_prospects", "record_key": f"minjus_rm_20260203:{record_hash}", "data": data, "created_at": now, "updated_at": now})
        if current_count + len(pending) >= TARGET_TOTAL:
            break
    written = await _bulk_upsert(pending)
    return {
        "status": "ok", "source_pages": pages, "parsed_unique": len(candidates), "current_before": current_count,
        "target": TARGET_TOTAL, "inserted": written, "current_after": current_count + written,
        "duplicates_skipped": duplicates, "source": MINJUS_2026_02_PDF,
    }


@app.get("/crm/cuba-mipymes/internal/enrich-minjus-ownership-2026")
async def enrich_minjus_ownership_2026():
    existing_rows = await _supabase_rows()
    existing_by_name = {
        _norm(r.get("buyer_company") or r.get("company_name") or r.get("business_name")): r
        for r in existing_rows
        if _norm(r.get("buyer_company") or r.get("company_name") or r.get("business_name"))
    }
    candidates, pages = _extract_minjus_candidates(await _download(MINJUS_2026_02_PDF))
    now = datetime.now(timezone.utc).isoformat()
    pending: list[dict] = []
    matched = representatives_found = already_enriched = 0
    for c in candidates:
        existing = existing_by_name.get(_norm(c.get("name")))
        if not existing:
            continue
        matched += 1
        representative = c.get("public_representative")
        if not representative:
            continue
        representatives_found += 1
        if _norm(existing.get("public_representative")) == _norm(representative):
            already_enriched += 1
            continue
        record_key = existing.get("_record_key")
        if not record_key:
            continue
        merged = {k: v for k, v in existing.items() if k != "_record_key"}
        merged.update({
            "public_representative": representative,
            "representative_role": "PUBLIC_REGISTRY_REPRESENTATIVE",
            "ownership_verification_status": merged.get("ownership_verification_status") or "NOT_PUBLICLY_VERIFIED",
            "ownership_note": merged.get("ownership_note") or "A public representative is not treated as an owner unless an authoritative source explicitly establishes ownership.",
            "ownership_source_url": MINJUS_2026_02_PDF,
            "ownership_source_reference": f"page {c.get('page')}",
            "updated_at": now,
        })
        pending.append({"logical_table": "external_trade_prospects", "record_key": record_key, "data": merged, "created_at": merged.get("created_at") or now, "updated_at": now})
    written = await _bulk_upsert(pending)
    return {
        "status": "ok", "source": MINJUS_2026_02_PDF, "source_pages": pages,
        "registry_candidates": len(candidates), "matched_existing": matched,
        "representatives_found": representatives_found, "already_enriched": already_enriched,
        "records_enriched": written,
        "ownership_policy": "Representative identity is stored separately and never promoted to legal/beneficial owner without explicit ownership evidence.",
    }


@app.get("/cuba-mipymes-api/health")
@app.get("/crm/cuba-mipymes/health")
async def health():
    records = await _records()
    return {"status": "ok", "service": "cuba-private-sector-read-only-crm", "version": "2.0.0", "record_count": len(records), "source_scope": "public_registry_and_official_actor_lists_research", "ownership_policy": "evidence_only", "binding_actions": False}


@app.get("/cuba-mipymes-api/list")
@app.get("/crm/cuba-mipymes")
@app.get("/crm/cuba-mipymes/list")
async def list_mipymes():
    records = await _records()
    return {"status": "ok", "count": len(records), "records": records, "classification": "RESEARCH / VERIFIED PUBLIC SOURCE", "notice": "A listed or registered private-sector actor is not a qualified buyer or current RFQ. Public representatives are not owners unless ownership is separately evidenced."}
