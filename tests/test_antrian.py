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


async def test_job_tersangkut_dikembalikan(conn, nilai):
    """Job yang mati di tengah jalan harus bisa diulang.

    _claim_next() hanya mengambil 'queued', jadi baris yang tertinggal
    'running' setelah restart tidak pernah diulang maupun selesai.
    """
    job = await jobs.enqueue(conn, "bot1", "/nik", nilai)
    async with conn.cursor() as cur:
        await cur.execute("UPDATE search_jobs SET state='running' WHERE job_id=%s",
                          (job["job_id"],))
    assert await jobs.pulihkan_tersangkut(conn) >= 1
    async with conn.cursor() as cur:
        await cur.execute("SELECT state FROM search_jobs WHERE job_id=%s", (job["job_id"],))
        assert (await cur.fetchone())["state"] == "queued"


async def test_job_berkas_dedup_dan_validasi(conn, nilai):
    """Pencarian berbasis foto memakai id media sebagai `value`.

    search_jobs.value bertipe TEXT dan tidak bisa menampung gambar, jadi
    fotonya disimpan di media_blobs lebih dulu (dedup lewat sha256) dan
    id-nya yang masuk antrian.
    """
    import db
    import routes

    assert routes.butuh_berkas("bot1", "/fr") is True
    assert routes.butuh_berkas("bot1", "/nikbyphone") is False

    data = f"foto-palsu-{nilai}".encode()
    mid = await db.store_media(conn, data, "image/jpeg",
                               bot="bot1", cmd="/fr", value="(unggahan)")
    mid2 = await db.store_media(conn, data, "image/jpeg",
                                bot="bot1", cmd="/fr", value="(unggahan)")
    assert mid == mid2, "foto identik harus ter-dedup"

    blob = await db.get_media(conn, mid)
    assert bytes(blob["bytes"]) == data

    job = await jobs.enqueue(conn, "bot1", "/fr", mid)
    assert job["value"] == mid
    async with conn.cursor() as cur:
        await cur.execute("DELETE FROM search_jobs WHERE value = %s", (mid,))
        await cur.execute("DELETE FROM media_blobs WHERE id = %s", (mid,))


def test_gambar_dikenali_dari_isinya():
    """Content-type dari klien tidak bisa dipercaya.

    multipart.CreateFormFile di Go memberi "application/octet-stream" secara
    bawaan, sehingga unggahan foto dari ArtemisID ditolak "hanya menerima
    gambar" padahal isinya JPEG yang sah.
    """
    import api

    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    assert api._tipe_gambar(jpeg, "application/octet-stream") == "image/jpeg"
    assert api._tipe_gambar(png, None) == "image/png"
    assert api._tipe_gambar(b"bukan gambar", "application/octet-stream") is None
