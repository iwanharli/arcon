"""Batas waktu di dalam satu job: jaringan Telegram macet & rate limit panjang.

Latar: worker antrian serial. Dua hal dulu bisa menahannya tanpa akhir:
- panggilan Telethon (get_entity, send_message, click, get_messages, ...)
  tanpa timeout — kalau koneksi MTProto macet diam-diam, await selamanya;
- "Please wait N second(s)" dari bot ditunggu mentah-mentah berapa pun N.

Uji ini OFFLINE: klien Telegram, db, dan _ask_and_parse dipalsukan. Tidak ada
koneksi ke Telegram/bot maupun database.

Jalankan: pytest -q tests/test_batas_tunggu.py
"""

import asyncio
import time

import pytest

import connector
import service
from connector import JaringanTelegramMacet, TelegramConnector

BATAS_TES = 0.05          # NET_TIMEOUT mini supaya tes cepat


async def _selamanya(*_a, **_k):
    """Meniru request MTProto yang macet: tidak pernah selesai."""
    await asyncio.Event().wait()


class Entitas:
    id = 1


class KlienPalsu:
    """Klien Telethon palsu; tiap metode bisa diganti jadi 'macet'."""

    def __init__(self, macet=()):
        self.macet = set(macet)
        self.handler = []
        self.terkirim = []

    async def get_entity(self, _target):
        if "get_entity" in self.macet:
            await _selamanya()
        return Entitas()

    async def send_message(self, target, text, **_k):
        if "send_message" in self.macet:
            await _selamanya()
        self.terkirim.append((target, text))

    async def get_messages(self, _target, limit=20):
        if "get_messages" in self.macet:
            await _selamanya()
        return []

    async def download_media(self, _msg, file=None):
        if "download_media" in self.macet:
            await _selamanya()
        return b"foto"

    async def start(self, phone=None):
        pass                               # login sukses; yang macet get_me

    async def get_me(self):
        if "get_me" in self.macet:
            await _selamanya()

    def add_event_handler(self, h, ev=None):
        self.handler.append(h)

    def remove_event_handler(self, h, ev=None):
        self.handler.remove(h)


def _tg(klien):
    # __init__ asli membuat TelegramClient (file session) — dilewati.
    tg = object.__new__(TelegramConnector)
    tg.client = klien
    return tg


@pytest.fixture(autouse=True)
def _batas_mini(monkeypatch):
    monkeypatch.setattr(connector, "NET_TIMEOUT", BATAS_TES)
    monkeypatch.setattr(connector, "NET_TIMEOUT_BERKAS", BATAS_TES)


# ------------------------------------------------------------- connector

async def test_batas_mengangkat_error_jelas_bukan_timeouterror():
    with pytest.raises(JaringanTelegramMacet, match="jaringan Telegram macet"):
        await connector._batas(_selamanya(), "uji")
    # Kalau turunan TimeoutError, except di ask()/_tunggu() akan menelannya.
    assert not issubclass(JaringanTelegramMacet, asyncio.TimeoutError)


async def test_ask_get_entity_macet_gagal_cepat():
    tg = _tg(KlienPalsu(macet={"get_entity"}))
    t0 = time.monotonic()
    with pytest.raises(JaringanTelegramMacet):
        await tg.ask("bot1", "/nik 1", timeout=30)
    assert time.monotonic() - t0 < 2


async def test_ask_send_message_macet_tembus_dan_handler_dilepas():
    klien = KlienPalsu(macet={"send_message"})
    tg = _tg(klien)
    t0 = time.monotonic()
    with pytest.raises(JaringanTelegramMacet):
        # timeout tunggu-balasan 30s TIDAK boleh sempat berjalan
        await tg.ask("bot1", "/nik 1", timeout=30, wait_final=True)
    assert time.monotonic() - t0 < 2
    assert klien.handler == [], "handler event harus dilepas walau gagal"


async def test_send_macet_gagal_cepat():
    tg = _tg(KlienPalsu(macet={"send_message"}))
    with pytest.raises(JaringanTelegramMacet):
        await tg.send("bot1", "halo")


async def test_history_macet_gagal_cepat():
    tg = _tg(KlienPalsu(macet={"get_messages"}))
    with pytest.raises(JaringanTelegramMacet):
        await tg.history("bot1")


async def test_get_me_macet_gagal_cepat():
    tg = _tg(KlienPalsu(macet={"get_me"}))
    with pytest.raises(JaringanTelegramMacet):
        await tg.start()


class Tombol:
    def __init__(self, text, data):
        self.text, self.data = text, data


class Markup:
    def __init__(self, *tombol):
        self.rows = [type("Baris", (), {"buttons": list(tombol)})()]


class PesanKlikMacet:
    text = "hasil halaman 1"

    def __init__(self):
        self.reply_markup = Markup(Tombol("Next ➡️", b"x_page:2"))

    async def click(self, _b, _k):
        await _selamanya()


async def test_klik_macet_tembus_lewat_tunggu():
    """Klik dijalankan di dalam _tunggu(), yang menelan asyncio.TimeoutError.
    Klik yang macet harus tetap tembus, bukan dianggap 'bot belum menjawab'."""
    tg = _tg(KlienPalsu())
    t0 = time.monotonic()
    with pytest.raises(JaringanTelegramMacet, match="klik"):
        await tg.telusuri_halaman("bot1", [PesanKlikMacet()], 2, step_timeout=30)
    assert time.monotonic() - t0 < 2


async def test_download_media_macet_tetap_best_effort_tapi_terbatas():
    from telethon.tl.types import MessageMediaPhoto

    pesan = type("P", (), {"media": MessageMediaPhoto()})()
    tg = _tg(KlienPalsu(macet={"download_media"}))
    t0 = time.monotonic()
    assert await tg.download_media(pesan) is None
    assert time.monotonic() - t0 < 2


# ------------------------------------------------------------ rate limit

def _hasil_jeda(n):
    teks = f"Please wait {n} second(s)"
    return {"status": "queue_without_data", "msg": teks, "fields": None,
            "_texts": [teks], "_replies": []}


@pytest.fixture()
def palsu_service(monkeypatch):
    rekam = {"tanya": 0, "tidur": [], "simpan": [], "media": 0}
    urutan = []

    async def _ask(*_a, **_k):
        rekam["tanya"] += 1
        return urutan.pop(0)

    async def _tidur(detik, *a, **k):
        rekam["tidur"].append(detik)       # tidak benar-benar tidur

    async def _simpan(_conn, bot, cmd, value, status, msg, fields, **k):
        rekam["simpan"].append((status, msg, k.get("raw_text")))

    async def _media(_tg, _replies):
        rekam["media"] += 1
        return []

    async def _lookup(*_a, **_k):
        return None

    monkeypatch.setattr(service, "_ask_and_parse", _ask)
    monkeypatch.setattr(service.asyncio, "sleep", _tidur)
    monkeypatch.setattr(service.db, "store_result", _simpan)
    monkeypatch.setattr(service.db, "lookup", _lookup)
    monkeypatch.setattr(service, "_collect_media", _media)
    monkeypatch.setattr(service, "RATE_LIMIT_MAKS", 60.0)
    return rekam, urutan


async def test_rate_limit_panjang_tidak_ditunggu(palsu_service):
    rekam, urutan = palsu_service
    urutan.append(_hasil_jeda(500))

    hasil = await service.query(None, None, "bot1", "/uji", "Joko")

    assert rekam["tidur"] == [], "jeda 500s tidak boleh ditunggu di worker"
    assert rekam["tanya"] == 1, "tidak boleh mengulang tanya"
    assert hasil["status"] == "queue_without_data"
    assert "500" in hasil["msg"] and "coba lagi" in hasil["msg"]
    assert hasil["from_cache"] is False
    assert "_texts" not in hasil and "_replies" not in hasil
    status, msg, raw = rekam["simpan"][0]
    assert status == "queue_without_data"
    assert "Please wait 500" in raw, "teks asli bot tetap disimpan"
    assert rekam["media"] == 0


async def test_rate_limit_pendek_ditunggu_lalu_ulang_sekali(palsu_service):
    rekam, urutan = palsu_service
    urutan += [_hasil_jeda(10),
               {"status": "not_found", "msg": "Data tidak ditemukan", "fields": None,
                "_texts": ["Data tidak ditemukan"], "_replies": []}]

    hasil = await service.query(None, None, "bot1", "/uji", "Joko")

    assert rekam["tidur"] == [11]
    assert rekam["tanya"] == 2
    assert hasil["status"] == "not_found"


async def test_rate_limit_tepat_di_batas_masih_ditunggu(palsu_service):
    rekam, urutan = palsu_service
    urutan += [_hasil_jeda(60),
               {"status": "not_found", "msg": "x", "fields": None,
                "_texts": ["x"], "_replies": []}]

    await service.query(None, None, "bot1", "/uji", "Joko")

    assert rekam["tidur"] == [61]
    assert rekam["tanya"] == 2
