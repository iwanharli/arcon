"""Perilaku antrian — murni database, tidak menyentuh Telegram.

    pytest -q tests/test_antrian.py
"""
import uuid

import pytest

import jobs

pytestmark = pytest.mark.asyncio


@pytest.fixture()
def nilai():
    return f"UJI-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
async def bersihkan(conn):
    yield
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM search_jobs WHERE value LIKE 'UJI-%%'")


async def _antre(conn, nilai):
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT count(*) AS n FROM search_jobs WHERE value = %s AND state='queued'",
            (nilai,))
        return (await cur.fetchone())["n"]


async def test_permintaan_kembar_digabung(conn, nilai):
    """Dua permintaan identik tidak boleh menembak bot dua kali — kuota harian
    per fitur adalah pembatas paling mahal di sistem ini."""
    a = await jobs.enqueue(conn, "bot1", "/nik", nilai, requested_by="a")
    b = await jobs.enqueue(conn, "bot1", "/nik", nilai, requested_by="b")
    assert str(a["job_id"]) == str(b["job_id"]), "job kembar tidak digabung"
    assert await _antre(conn, nilai) == 1


async def test_prioritas_dinaikkan_bukan_ditimpa(conn, nilai):
    """Permintaan kedua dengan prioritas lebih tinggi harus menaikkan job yang
    sudah antre, bukan membuat job baru dan bukan menurunkan prioritas."""
    await jobs.enqueue(conn, "bot1", "/nik", nilai, priority=1)
    b = await jobs.enqueue(conn, "bot1", "/nik", nilai, priority=5)
    assert b["priority"] == 5
    c = await jobs.enqueue(conn, "bot1", "/nik", nilai, priority=0)
    assert c["priority"] == 5, "prioritas tidak boleh turun"
    assert await _antre(conn, nilai) == 1


async def test_force_tidak_digabung_dengan_biasa(conn, nilai):
    """Job paksa menembak bot walau ada cache, jadi tidak boleh disatukan
    dengan job biasa yang mungkin dijawab dari cache."""
    a = await jobs.enqueue(conn, "bot1", "/nik", nilai, force=False)
    b = await jobs.enqueue(conn, "bot1", "/nik", nilai, force=True)
    assert str(a["job_id"]) != str(b["job_id"])
    assert await _antre(conn, nilai) == 2


async def test_bot_berbeda_tidak_digabung(conn, nilai):
    a = await jobs.enqueue(conn, "bot1", "/nik", nilai)
    b = await jobs.enqueue(conn, "bot2", "/getphone", nilai)
    assert str(a["job_id"]) != str(b["job_id"])
