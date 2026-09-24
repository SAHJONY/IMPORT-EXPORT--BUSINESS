"""SAHJONY LLC — pipeline único de documentos de agencias.

REGLA: ninguna ruta escribe archivos de documentos directamente. Todo pasa por
aquí: render → sha256 → guardar → registrar fila en `documents`.
Regenerar crea una NUEVA versión; la anterior queda marcada `superseded=1`
(nunca se sobrescribe ni se borra).

Disco: <root>/<agency_id>/<doc_type>/<YYYY>/<MM>/<code>_v<n>.html
(para adjuntos: <code>_v<n>_<nombre-original>).

Nada se sirve por static: la descarga siempre verifica ownership por agency_id.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
import uuid

DOC_TYPES = ("recibo", "factura", "manifiesto", "etiqueta", "etiquetas",
             "terminos", "embarque", "adjunto", "escaneo", "documento")


def _db_path() -> str:
    return os.environ.get("DB_PATH", "/opt/sahjony-packages/data/sahjony_packages.db")


def docs_root() -> str:
    explicit = os.environ.get("AGENCY_DOCS_DIR")
    if explicit:
        path = explicit
    else:
        base = os.path.dirname(os.path.abspath(_db_path()))
        path = os.path.join(base, "agency_docs")
    os.makedirs(path, exist_ok=True)
    return path


_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_name(name: str) -> str:
    name = _SAFE.sub("_", (name or "").strip()).strip("._")[:80]
    return name or "archivo"


def _audit(conn, agency_id, actor, action, doc_id, detail):
    try:
        import agency_db as _adb
        _adb.audit(conn, agency_id, actor, action, entity="documents",
                   entity_id=doc_id, detail=detail)
    except Exception:
        pass


def write_doc(conn: sqlite3.Connection, agency_id: int, doc_type: str, code: str,
              content, ext: str = "html", ref_table: str = "",
              ref_id: int = 0, created_by: str = "owner", label: str = "") -> dict:
    """Escribe un documento versionado (html/pdf). Devuelve dict con id/sha256/version."""
    agency_id = int(agency_id)
    doc_type = _safe_name(doc_type or "documento")[:40]
    code = _safe_name(code or uuid.uuid4().hex[:8])[:80]
    ext = _safe_name(ext or "html")[:10].lower() or "html"
    if isinstance(content, str):
        content = content.encode("utf-8")
    row = conn.execute(
        "SELECT MAX(version) AS m FROM documents WHERE agency_id=? AND doc_type=? AND code=?",
        (agency_id, doc_type, code)).fetchone()
    version = (row["m"] or 0) + 1
    if version > 1:
        conn.execute(
            "UPDATE documents SET superseded=1 WHERE agency_id=? AND doc_type=? AND code=?"
            " AND version<?", (agency_id, doc_type, code, version))
    digest = hashlib.sha256(content).hexdigest()
    ym = time.strftime("%Y/%m")
    directory = os.path.join(docs_root(), str(agency_id), doc_type, ym)
    os.makedirs(directory, exist_ok=True)
    filename = "%s_v%d.%s" % (code, version, ext)
    path = os.path.join(directory, filename)
    with open(path, "wb") as f:
        f.write(content)
    os.chmod(path, 0o640)
    rel = os.path.relpath(path, docs_root())
    batch = uuid.uuid4().hex
    cur = conn.execute(
        """INSERT INTO documents
           (batch, agency_id, doc_type, ref_table, ref_id, code, version, superseded,
            doc_key, label, file_path, sha256, created_at, created_by, immutable)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?,1)""",
        (batch, agency_id, doc_type, ref_table or "", ref_id or 0, code, version, 0,
         doc_type, (label or code)[:200], rel, digest, created_by or "owner"))
    conn.commit()
    doc_id = cur.lastrowid
    _audit(conn, agency_id, created_by or "owner", "document_generated", doc_id,
           "%s %s v%d sha256=%s" % (doc_type, code, version, digest[:12]))
    return {"id": doc_id, "path": rel, "sha256": digest, "version": version,
            "filename": filename}


def store_upload(conn: sqlite3.Connection, agency_id: int, doc_type: str,
                 label: str, data: bytes, mime: str, ref_table: str = "",
                 ref_id: int = 0, created_by: str = "owner") -> dict:
    """Guarda un adjunto/escaneo (bytes ya validados) en el pipeline."""
    ext = "pdf" if (mime or "") == "application/pdf" else "bin"
    if isinstance(data, str):
        data = data.encode("utf-8")
    code = "upl_%s" % uuid.uuid4().hex[:10]
    agency_id = int(agency_id)
    doc_type = _safe_name(doc_type or "adjunto")[:40]
    digest = hashlib.sha256(data).hexdigest()
    ym = time.strftime("%Y/%m")
    directory = os.path.join(docs_root(), str(agency_id), doc_type, ym)
    os.makedirs(directory, exist_ok=True)
    filename = "%s_v1.%s" % (code, ext)
    path = os.path.join(directory, filename)
    with open(path, "wb") as f:
        f.write(data)
    os.chmod(path, 0o640)
    rel = os.path.relpath(path, docs_root())
    cur = conn.execute(
        """INSERT INTO documents
           (batch, agency_id, doc_type, ref_table, ref_id, code, version, superseded,
            doc_key, label, file_path, sha256, created_at, created_by, immutable)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'),?,1)""",
        (uuid.uuid4().hex, agency_id, doc_type, ref_table or "", ref_id or 0,
         code, 1, 0, doc_type, (label or code)[:200], rel, digest,
         created_by or "owner"))
    conn.commit()
    doc_id = cur.lastrowid
    _audit(conn, agency_id, created_by or "owner", "document_uploaded", doc_id,
           "%s %s sha256=%s" % (doc_type, label or code, digest[:12]))
    return {"id": doc_id, "path": rel, "sha256": digest, "version": 1,
            "filename": filename}


def get_doc_for_download(conn: sqlite3.Connection, doc_id: int, agency_ids) -> dict | None:
    """Fila del documento solo si pertenece a una agencia autorizada (si no → None)."""
    ids = [int(a) for a in (agency_ids or [])]
    if not ids:
        return None
    ph = ",".join("?" for _ in ids)
    return conn.execute(
        f"SELECT * FROM documents WHERE id=? AND agency_id IN ({ph})",
        [doc_id] + ids).fetchone()


def read_doc_bytes(doc) -> bytes:
    """Lee los bytes del documento. ENDURECIDO: el path resuelto con
    realpath DEBE quedar dentro de docs_root; si no, ValueError.
    Nunca confíes solo en el chequeo de la ruta que llama."""
    root = os.path.realpath(docs_root())
    rel = (doc["file_path"] or "").strip()
    if not rel:
        raise ValueError("Documento sin archivo")
    full = os.path.realpath(os.path.join(root, rel))
    if full != root and not full.startswith(root + os.sep):
        raise ValueError("Ruta de documento fuera del archivo permitido")
    if not os.path.isfile(full):
        raise ValueError("Archivo no disponible")
    with open(full, "rb") as f:
        return f.read()


def list_agency_docs(conn: sqlite3.Connection, agency_id: int, doc_type: str = ""):
    sql = ("SELECT *, (CASE WHEN ref_table='' THEN doc_type "
           "ELSE ref_table || ' #' || ref_id END) AS entity FROM documents "
           "WHERE agency_id=?")
    params: list = [agency_id]
    if doc_type:
        sql += " AND doc_type=?"
        params.append(doc_type)
    return conn.execute(sql + " ORDER BY id DESC LIMIT 200", params).fetchall()


def list_entity_docs(conn: sqlite3.Connection, agency_id: int, ref_table: str,
                     ref_id: int):
    return conn.execute(
        "SELECT * FROM documents WHERE agency_id=? AND ref_table=? AND ref_id=?"
        " ORDER BY id DESC",
        (agency_id, ref_table, ref_id)).fetchall()


def verify_all(conn: sqlite3.Connection) -> dict:
    """Verificación de integridad global (staff). Solo lectura."""
    per: dict[int, dict] = {}
    orphans: list[str] = []
    seen: set[str] = set()
    brands = {r["id"]: (r["brand"] or ("#%d" % r["id"]))
              for r in conn.execute("SELECT id, brand FROM agencies").fetchall()}
    for d in conn.execute("SELECT * FROM documents").fetchall():
        aid = d["agency_id"] or 0
        slot = per.setdefault(aid, {"brand": brands.get(aid, "#%d" % aid),
                                    "ok": 0, "missing": 0, "mismatch": 0})
        rel = d["file_path"] or ""
        seen.add(rel)
        full = os.path.join(docs_root(), rel)
        if not rel or not os.path.exists(full):
            slot["missing"] += 1
            continue
        h = hashlib.sha256()
        with open(full, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        if h.hexdigest() == (d["sha256"] or ""):
            slot["ok"] += 1
        else:
            slot["mismatch"] += 1
    root = docs_root()
    if os.path.isdir(root):
        for dirpath, _dn, filenames in os.walk(root):
            for fn in filenames:
                rel = os.path.relpath(os.path.join(dirpath, fn), root)
                if rel not in seen:
                    orphans.append(rel)
    return {"per_agency": sorted(per.values(), key=lambda s: s["brand"]),
            "orphans": sorted(orphans)}
