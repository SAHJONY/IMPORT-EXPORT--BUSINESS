import importlib
import os
from pathlib import Path


def test_database_uses_tmp_on_vercel(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("LEGACY_SQLITE_PATH", raising=False)

    import database

    reloaded = importlib.reload(database)
    assert reloaded.DB_PATH == Path("/tmp/import-export-business.db")


def test_fastapi_app_imports_without_initializing_sqlite(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.delenv("OWNER_TOKEN", raising=False)
    monkeypatch.delenv("INSFORGE_BASE_URL", raising=False)
    monkeypatch.delenv("INSFORGE_API_KEY", raising=False)

    module = importlib.import_module("fastapi_server")
    assert module.app.title == "SAHJONY Global Trade Intelligence OS"
