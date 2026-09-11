"""Uji `/health` jujur dan exception handler — tanpa DB/Telegram/httpx.

Pendekatan langsung: panggil coroutine `health()` dan handler error secara
langsung (bukan lewat TestClient) supaya tidak butuh httpx/TestClient.

Motif: saat Postgres connector mati, dulu `/health` (dan semua endpoint sentuh-DB)
membalas 500 dengan teks polos "Internal Server Error" tanpa jejak. Setelah
perbaikan:
  - `/health` selalu 200, body `ok` menandakan DB terjangkau/tidak;
  - error tak tertangani jadi JSON 500 yang menyebut jenis errornya.

Jalankan: TG_API_ID=1 TG_API_HASH=x pytest tests/test_health.py
"""
import json
import types

import pytest

import api


@pytest.fixture(autouse=True)
def _state_siap():
    api.state["conn"] = object()  # dummy; queue_stats di-monkeypatch
    yield


async def test_health_sehat(monkeypatch):
    async def queue_stats(conn):
        return {"pending": 0, "running": 0}

    monkeypatch.setattr(api.jobs, "queue_stats", queue_stats)
    data = await api.health()
    assert data["ok"] is True
    assert data["db"] == "ok"
    assert data["antrian"] == {"pending": 0, "running": 0}


async def test_health_db_mati(monkeypatch):
    async def queue_stats(conn):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(api.jobs, "queue_stats", queue_stats)
    data = await api.health()
    assert data["ok"] is False
    assert data["db"].startswith("error:")
    assert data["antrian"] is None


async def test_error_tak_tertangani_jadi_json():
    req = types.SimpleNamespace(method="GET", url=types.SimpleNamespace(path="/x"))
    resp = await api._jebakan_error(req, RuntimeError("sengaja meledak"))
    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert body["ok"] is False
    assert body["detail"] == "internal error: RuntimeError"
