"""Koneksi DB yang mati diam-diam tidak boleh membuat kueri menggantung selamanya."""
import asyncio
import time

import psycopg
import pytest

import db


class _PgConn:
    def __init__(self):
        self.finished = False

    def finish(self):
        self.finished = True


class _Cur:
    def __init__(self, raw):
        self.raw = raw
        self.rowcount = 7

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def execute(self, q, p=None):
        if self.raw.macet:
            await asyncio.Event().wait()  # tak pernah selesai, seperti socket yang ditelan

    async def fetchone(self):
        return {"x": 1}

    async def fetchall(self):
        return [{"x": 1}]


class _Raw:
    def __init__(self, macet=False):
        self.macet = macet
        self.pgconn = _PgConn()
        self.closed = False
        self.broken = False

    def cursor(self, *a, **k):
        return _Cur(self)

    async def execute(self, q):
        if self.macet:
            await asyncio.Event().wait()

    async def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def _cepat(monkeypatch):
    monkeypatch.setattr(db, "OP_TIMEOUT", 0.2)


async def test_normal_lewat_apa_adanya():
    c = db.KoneksiBatas(_Raw())
    async with c.cursor() as cur:
        await cur.execute("select 1")
        assert await cur.fetchone() == {"x": 1}
        assert await cur.fetchall() == [{"x": 1}]
        assert cur.rowcount == 7


async def test_macet_dibatasi_dan_socket_diputus():
    raw = _Raw(macet=True)
    c = db.KoneksiBatas(raw)
    t = time.monotonic()
    with pytest.raises(psycopg.OperationalError):
        async with c.cursor() as cur:
            await cur.execute("select 1")
    assert time.monotonic() - t < 3
    assert raw.pgconn.finished


async def test_ping_macet_pakai_batas_sendiri():
    raw = _Raw(macet=True)
    t = time.monotonic()
    with pytest.raises(psycopg.OperationalError):
        await db.KoneksiBatas(raw).execute("SELECT 1", batas=0.1)
    assert time.monotonic() - t < 1


async def test_pemanggil_dibatalkan_tidak_meninggalkan_kueri_yatim():
    raw = _Raw(macet=True)
    c = db.KoneksiBatas(raw)

    async def jalan():
        async with c.cursor() as cur:
            await cur.execute("select 1")

    t = asyncio.create_task(jalan())
    await asyncio.sleep(0.05)
    t.cancel()
    with pytest.raises(asyncio.CancelledError):
        await t
    await asyncio.sleep(0)
    assert not [x for x in asyncio.all_tasks() if "execute" in repr(x.get_coro())]


async def test_koneksi_pulih_menyambung_ulang_setelah_ping_macet(monkeypatch):
    dibuat = []

    async def fake_connect():
        c = db.KoneksiBatas(_Raw())
        dibuat.append(c)
        return c

    monkeypatch.setattr(db, "connect", fake_connect)
    monkeypatch.setattr(db, "PING_TIMEOUT", 0.1)
    p = await db.connect_pulih()
    dibuat[0]._raw.macet = True  # mati diam-diam
    t = time.monotonic()
    async with p.cursor() as cur:
        await cur.execute("select 1")
    assert len(dibuat) == 2 and time.monotonic() - t < 3


async def test_audit_gagal_tidak_melempar():
    import tgbot, tgbot_simple

    class Mati:
        def cursor(self):
            raise psycopg.OperationalError("db mati")

    await tgbot.audit(Mati(), 1, "bot1", "/nik", "x", "found")
    await tgbot_simple.audit(Mati(), 1, "u", "n", "/nik", "x", "found")


async def test_penyambungan_gagal_antrian_ikut_gagal_cepat(monkeypatch):
    percobaan = []

    async def connect_mati():
        percobaan.append(1)
        await asyncio.sleep(0.2)
        raise psycopg.OperationalError("tak terjangkau")

    monkeypatch.setattr(db, "connect", connect_mati)
    p = db.KoneksiPulih()
    t = time.monotonic()
    hasil = await asyncio.gather(*(p._ambil() for _ in range(10)), return_exceptions=True)
    assert all(isinstance(h, psycopg.OperationalError) for h in hasil)
    assert len(percobaan) == 1 and time.monotonic() - t < 1
    with pytest.raises(psycopg.OperationalError):  # panggilan baru tetap mencoba lagi
        await p._ambil()
    assert len(percobaan) == 2
