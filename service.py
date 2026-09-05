"""Alur lengkap satu query: cek cache -> hit Telegram -> parse -> simpan.

Ini lapisan yang dipakai sehari-hari; connector.py tetap "bodoh" (cuma kirim
dan terima pesan), sementara keputusan cache/normalisasi/penyimpanan ada di
sini.

    async with TelegramConnector() as tg:
        conn = await db.connect()
        hasil = await query(tg, conn, "bot1", "/nik", "3201010101010001")
        print(hasil["from_cache"], hasil["status"], hasil["fields"])
"""
from __future__ import annotations

import asyncio
import logging
import re

import db
import parser

log = logging.getLogger("artemis.service")

# Telegram/bot menolak sementara karena terlalu cepat: "Please wait 19 second(s)".
RATE_LIMIT_RE = re.compile(r"wait\s+(\d+)\s*second", re.IGNORECASE)


def _rate_limit_seconds(texts: list[str]) -> int | None:
    for t in texts:
        m = RATE_LIMIT_RE.search(t or "")
        if m:
            return int(m.group(1))
    return None


# Field yang isinya identitas dan bisa dipakai mencocokkan balasan ke permintaan.
_ID_FIELDS = ("nik", "kk", "nomor", "msisdn", "id_pelanggan", "nopol")

# Nilai ter-mask (mis. "626••••••••••31") tidak bisa dibandingkan dengan input,
# jadi tidak boleh dipakai untuk menyimpulkan "milik permintaan lain".
_MASK_RE = re.compile(r"[•*x]", re.IGNORECASE)


def _identifier(value: str) -> str | None:
    """Ambil bagian identitas dari input, mis. 'Joko#1' -> None, '3275...' -> digit."""
    inti = value.split("#")[0].strip()
    digits = re.sub(r"\D", "", inti)
    return digits if len(digits) >= 8 else None


def relates_to_request(value: str, texts: list[str], fields) -> bool | None:
    """Apakah balasan ini benar-benar jawaban untuk `value`?

    True  = cocok, False = jelas milik permintaan lain, None = tak bisa dipastikan.

    Perlu karena bot membalas tanpa reply_to: jawaban permintaan sebelumnya
    yang telat datang bisa jatuh ke jendela tunggu permintaan berikutnya.
    """
    ident = _identifier(value)
    if not ident:
        return None                                   # input berupa nama/email

    if any(ident in (t or "") for t in texts):
        return True                                   # balasan menyebut input kita

    records = fields if isinstance(fields, list) else [fields] if fields else []
    lain = set()
    for rec in records:
        for f in _ID_FIELDS:
            v = rec.get(f)
            if not v:
                continue
            sv = str(v)
            if _MASK_RE.search(sv):        # ter-mask -> tak bisa dibandingkan, lewati
                continue
            d = re.sub(r"\D", "", sv)
            if d:
                lain.add(d)
    if lain and ident not in lain:
        return False                                  # identitas di balasan beda semua
    return None


async def query(tg, conn, bot: str, cmd: str, value: str, *,
                timeout: float | None = None, collect: int = 3,
                force: bool = False, retry_on_rate_limit: bool = True) -> dict:
    """Jawab satu query, dari cache kalau bisa, dari bot kalau perlu.

    Kembalikan {"status", "msg", "fields", "from_cache"}.
    `force=True` melewati cache (paksa hit Telegram).
    """
    if not force:
        cached = await db.lookup(conn, bot, cmd, value)
        if cached:
            log.info("cache hit %s %s %s", bot, cmd, value)
            return {
                "status": cached["status"],
                "msg": cached["msg"],
                "fields": cached["fields"],
                "from_cache": True,
            }

    result = await _ask_and_parse(tg, bot, cmd, value, timeout, collect)

    # Rate limit itu kondisi sementara — tunggu lalu coba sekali lagi, jangan
    # dicatat sebagai not_found (bisa mengunci hasil kosong ke cache).
    if retry_on_rate_limit:
        wait = _rate_limit_seconds(result["_texts"])
        if wait:
            log.warning("kena rate limit, tunggu %ss lalu ulangi", wait + 1)
            await asyncio.sleep(wait + 1)
            result = await _ask_and_parse(tg, bot, cmd, value, timeout, collect)

    texts = result.pop("_texts", [])

    # Jangan simpan balasan yang ternyata milik permintaan lain (lihat
    # relates_to_request). Ditandai queue_without_data supaya dicoba ulang,
    # bukan found — kalau tidak, data orang lain masuk ke profil kita.
    if result["status"] == "found" and relates_to_request(value, texts, result["fields"]) is False:
        log.warning("balasan tidak cocok dengan permintaan %s %s %s — diabaikan",
                    bot, cmd, value)
        result = {
            "status": "queue_without_data",
            "msg": "balasan yang diterima milik permintaan lain, hasil diabaikan",
            "fields": None,
        }

    await db.store_result(conn, bot, cmd, value, result["status"],
                          result["msg"], result["fields"])
    return {**result, "from_cache": False}


# Berapa lama menunggu JAWABAN ASLI (non-ack) dari bot data. Bot memproses
# lewat antrian internalnya sendiri; jawaban bisa datang menit-menitan setelah
# ack "Processing...". Karena antrian kita serial, menunggu lebih lama di sini
# aman — job berikutnya memang harus menunggu giliran.
FINAL_TIMEOUT = float(__import__("os").getenv("FINAL_TIMEOUT", "300"))  # 5 menit


async def _ask_and_parse(tg, bot: str, cmd: str, value: str,
                         timeout: float | None, collect: int) -> dict:
    def _accept(msg) -> bool:
        # Terima pesan non-ack ini sebagai jawaban kita, KECUALI terbukti milik
        # permintaan lain (identitas di dalamnya bentrok dengan `value`).
        txt = msg.text or ""
        records, _ = parser.parse_reply(txt)
        fields = records[0] if len(records) == 1 else (records or None)
        return relates_to_request(value, [txt], fields) is not False

    # Tunggu jawaban asli (non-ack) yang benar-benar milik permintaan ini;
    # jawaban nyasar dilewati sampai jawaban yang tepat datang / timeout.
    replies = await tg.ask(
        bot, f"{cmd} {value}".strip(),
        timeout=timeout if timeout is not None else FINAL_TIMEOUT,
        wait_final=True, ack_markers=parser.ACK_MARKERS, accept=_accept,
    )
    # buang pesan yang jelas milik permintaan lain sebelum diklasifikasi
    texts = [m.text for m in replies
             if parser.is_ack(m.text) or _accept(m)]
    out = parser.classify(texts)
    out["_texts"] = texts
    return out


async def query_many(tg, conn, bot: str, cmd: str, values: list[str],
                     delay: float = 10, **kwargs) -> dict[str, dict]:
    """Query banyak nilai berurutan. Yang sudah ada di cache tidak kena delay."""
    hasil = {}
    for i, value in enumerate(values):
        hasil[value] = await query(tg, conn, bot, cmd, value, **kwargs)
        if not hasil[value]["from_cache"] and i < len(values) - 1:
            await asyncio.sleep(delay)
    return hasil
