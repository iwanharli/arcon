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
_MASK_RE = re.compile(r"[•*]")


def _identifier(value: str) -> str | None:
    """Ambil bagian identitas dari input, mis. 'Joko#1' -> None, '3275...' -> digit."""
    inti = value.split("#")[0].strip()
    digits = re.sub(r"\D", "", inti)
    return digits if len(digits) >= 8 else None


# Command yang jawaban wajibnya adalah record nomor HP (bukan biodata).
PHONE_CMDS = {"/nohp", "/reg"}

# Command kartu keluarga: inputnya No.KK, tapi balasannya cuma NIK tiap anggota
# (No.KK tidak di-echo). relates_to_request tak bisa mencocokkan identitas ke
# No.KK, jadi untuk command ini balasan family card diterima tanpa ditolak.
KK_CMDS = {"/kk", "/biokk"}


def _has_phone_field(fields) -> bool:
    """True kalau fields (hasil parse) memuat kolom nomor/msisdn."""
    records = fields if isinstance(fields, list) else ([fields] if fields else [])
    for rec in records:
        if isinstance(rec, dict) and (rec.get("nomor") or rec.get("msisdn")):
            return True
    return False


def relates_to_request(value: str, texts: list[str], fields, cmd: str | None = None) -> bool | None:
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
    if not lain:
        return None
    if cmd in KK_CMDS:
        # Balasan /kk & /biokk = kartu keluarga (banyak NIK anggota), tidak
        # menyebut No.KK input — tak bisa diverifikasi ke No.KK, terima saja.
        return None
    if ident not in lain:
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
                "media": _media_urls(cached.get("media")),
                "from_cache": True,
            }

    # /nohp: relasi NIK -> nomor sudah tersimpan dari /reg di profile_phones.
    # Cek DB dulu supaya taktis tidak bergantung ke bot (yang bisa fallback
    # ke biodata saat NIK tidak punya nomor terdaftar di bot).
    if cmd == "/nohp" and not force:
        nik = _identifier(value)
        if nik:
            phones = await db.phones_by_nik(conn, nik)
            if phones:
                log.info("nohp dari profile_phones untuk %s (%d nomor)", nik, len(phones))
                return {
                    "status": "found",
                    "msg": None,
                    "fields": phones if len(phones) > 1 else phones[0],
                    "media": [],
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
    replies = result.pop("_replies", [])

    # Jangan simpan balasan yang ternyata milik permintaan lain (lihat
    # relates_to_request). Ditandai queue_without_data supaya dicoba ulang,
    # bukan found — kalau tidak, data orang lain masuk ke profil kita.
    if result["status"] == "found" and relates_to_request(value, texts, result["fields"], cmd) is False:
        log.warning("balasan tidak cocok dengan permintaan %s %s %s — diabaikan",
                    bot, cmd, value)
        result = {
            "status": "queue_without_data",
            "msg": "balasan yang diterima milik permintaan lain, hasil diabaikan",
            "fields": None,
        }
        replies = []

    # /nohp & /reg wajib balas record nomor. Bot kadang fallback ke biodata
    # (tanpa kolom nomor) kalau NIK tidak punya nomor terdaftar — itu bukan
    # hasil, tandai not_found supaya ArtemisID tidak menampilkan biodata.
    if result["status"] == "found" and cmd in PHONE_CMDS and not _has_phone_field(result["fields"]):
        log.warning("%s %s balas tanpa kolom nomor — anggap tidak ditemukan", bot, cmd)
        result = {"status": "not_found", "msg": "Nomor tidak ditemukan.", "fields": None}
        replies = []

    # Unduh foto yang menyertai jawaban. Untuk command foto (E-KTP dsb.) foto
    # itu sendiri adalah hasilnya — kumpulkan walau teks balasan kosong/tak
    # ter-parse (classify mengembalikan no_response/not_found untuk balasan
    # foto tanpa caption).
    media_blobs = []
    if replies:
        media_blobs = await _collect_media(tg, replies)
        if media_blobs and result["status"] != "found" and cmd in PHOTO_CMDS:
            result = {"status": "found",
                      "msg": result.get("msg") or "Foto ditemukan.",
                      "fields": result.get("fields")}

    await db.store_result(conn, bot, cmd, value, result["status"],
                          result["msg"], result["fields"],
                          media=media_blobs or None)
    import hashlib
    media_urls = _media_urls([hashlib.sha256(b).hexdigest() for b, _ in media_blobs])
    return {**result, "media": media_urls, "from_cache": False}


def _media_urls(ids) -> list[str]:
    if not ids:
        return []
    return [f"/media/{i}" for i in ids]


# Berapa lama menunggu JAWABAN ASLI (non-ack) dari bot data. Bot memproses
# lewat antrian internalnya sendiri; jawaban bisa datang menit-menitan setelah
# ack "Processing...". Karena antrian kita serial, menunggu lebih lama di sini
# aman — job berikutnya memang harus menunggu giliran.
FINAL_TIMEOUT = float(__import__("os").getenv("FINAL_TIMEOUT", "300"))  # 5 menit

# Command yang jawabannya bisa disertai foto (E-KTP dsb). Untuk ini kita
# menunggu sebentar setelah teks jawaban agar pesan foto yang menyusul ikut
# tertangkap.
PHOTO_CMDS = {"/foto", "/photo", "/nik", "/bionik", "/kk", "/biokk", "/fr", "/siswa"}
PHOTO_LINGER = 8.0


async def _ask_and_parse(tg, bot: str, cmd: str, value: str,
                         timeout: float | None, collect: int) -> dict:
    def _accept(msg) -> bool:
        # Terima pesan non-ack ini sebagai jawaban kita, KECUALI terbukti milik
        # permintaan lain (identitas di dalamnya bentrok dengan `value`).
        txt = msg.text or ""
        records, _ = parser.parse_reply(txt)
        fields = records[0] if len(records) == 1 else (records or None)
        return relates_to_request(value, [txt], fields, cmd) is not False

    linger = PHOTO_LINGER if cmd in PHOTO_CMDS else 0
    # Tunggu jawaban asli (non-ack) yang benar-benar milik permintaan ini;
    # jawaban nyasar dilewati sampai jawaban yang tepat datang / timeout.
    replies = await tg.ask(
        bot, f"{cmd} {value}".strip(),
        timeout=timeout if timeout is not None else FINAL_TIMEOUT,
        wait_final=True, ack_markers=parser.ACK_MARKERS, accept=_accept,
        linger=linger,
    )
    # buang pesan yang jelas milik permintaan lain sebelum diklasifikasi
    good = [m for m in replies if parser.is_ack(m.text) or _accept(m)]
    texts = [m.text for m in good]
    out = parser.classify(texts)
    out["_texts"] = texts
    out["_replies"] = good
    return out


async def _collect_media(tg, replies: list) -> list[tuple[bytes, str]]:
    media = []
    for m in replies:
        got = await tg.download_media(m)
        if got:
            media.append(got)
    return media


async def query_many(tg, conn, bot: str, cmd: str, values: list[str],
                     delay: float = 10, **kwargs) -> dict[str, dict]:
    """Query banyak nilai berurutan. Yang sudah ada di cache tidak kena delay."""
    hasil = {}
    for i, value in enumerate(values):
        hasil[value] = await query(tg, conn, bot, cmd, value, **kwargs)
        if not hasil[value]["from_cache"] and i < len(values) - 1:
            await asyncio.sleep(delay)
    return hasil
