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

import connector
import db
import parser
import routes

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
# Field identitas dikelompokkan per JENIS. Membandingkan lintas jenis salah:
# NIK BY PHONE dicari dengan nomor HP dan MEMANG menjawab dengan NIK yang
# berbeda — kalau NIK itu dianggap "identitas lain", seluruh laporannya
# (bagian A-F) ditolak sebagai balasan nyasar dan hanya potongan tanpa NIK
# yang tersimpan.
_ID_FIELDS_NIK = ("nik", "kk")
_ID_FIELDS_HP = ("nomor", "msisdn", "no_hp", "nomor_hp", "mobile_number")
_ID_FIELDS_LAIN = ("id_pelanggan", "nopol")
_ID_FIELDS = _ID_FIELDS_NIK + _ID_FIELDS_HP + _ID_FIELDS_LAIN


def _jenis_identitas(digits: str) -> tuple:
    """Field mana yang sejenis dengan input, jadi layak dibandingkan."""
    if len(digits) == 16:
        return _ID_FIELDS_NIK
    if 10 <= len(digits) <= 15 and (digits.startswith("62") or digits.startswith("0")
                                    or digits.startswith("8")):
        return _ID_FIELDS_HP
    return _ID_FIELDS

# Nilai ter-mask (mis. "626••••••••••31") tidak bisa dibandingkan dengan input,
# jadi tidak boleh dipakai untuk menyimpulkan "milik permintaan lain".
_MASK_RE = re.compile(r"[•*]")


def _inti_hp(digits: str) -> str:
    """Buang awalan negara/nol supaya format nomor bisa dibandingkan.

    Bot menjawab dengan format 62xxx sedangkan pengguna mengetik 08xxx. Tanpa
    penyamaan ini, bagian laporan yang memuat nomor kita SENDIRI justru
    dianggap "milik permintaan lain" lalu dibuang — pada NIK BY PHONE, bagian
    A (INFORMASI NOMOR TELEPON) dan D (MSISDN NIK) hilang karena ini.
    """
    d = re.sub(r"\D", "", digits or "")
    if d.startswith("62"):
        d = d[2:]
    return d.lstrip("0")


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

    inti = _inti_hp(ident)
    if any(ident in (t or "") for t in texts):
        return True                                   # balasan menyebut input kita
    # ...termasuk kalau format nomornya berbeda (08xxx vs 62xxx).
    if len(inti) >= 8 and any(inti in re.sub(r"\D", "", t or "") for t in texts):
        return True

    records = fields if isinstance(fields, list) else [fields] if fields else []
    sejenis = _jenis_identitas(ident)
    lain = set()
    for rec in records:
        for f in sejenis:
            v = rec.get(f)
            if not v:
                continue
            sv = str(v)
            if _MASK_RE.search(sv):        # ter-mask -> tak bisa dibandingkan, lewati
                continue
            d = re.sub(r"\D", "", sv)
            if d:
                # nomor HP dibandingkan pada intinya saja (08xxx == 62xxx)
                lain.add(_inti_hp(d) if sejenis is _ID_FIELDS_HP else d)
    if not lain:
        return None
    if cmd in KK_CMDS:
        # Balasan /kk & /biokk = kartu keluarga (banyak NIK anggota), tidak
        # menyebut No.KK input — tak bisa diverifikasi ke No.KK, terima saja.
        return None
    pembanding = _inti_hp(ident) if sejenis is _ID_FIELDS_HP else ident
    if pembanding not in lain:
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

    result = await _ask_and_parse(tg, bot, cmd, value, timeout, collect, conn)

    # Rate limit itu kondisi sementara — tunggu lalu coba sekali lagi, jangan
    # dicatat sebagai not_found (bisa mengunci hasil kosong ke cache).
    if retry_on_rate_limit:
        wait = _rate_limit_seconds(result["_texts"])
        if wait:
            log.warning("kena rate limit, tunggu %ss lalu ulangi", wait + 1)
            await asyncio.sleep(wait + 1)
            result = await _ask_and_parse(tg, bot, cmd, value, timeout, collect, conn)

    texts = result.pop("_texts", [])
    replies = result.pop("_replies", [])

    # Jangan simpan balasan yang ternyata milik permintaan lain (lihat
    # relates_to_request). Ditandai queue_without_data supaya dicoba ulang,
    # bukan found — kalau tidak, data orang lain masuk ke profil kita.
    # Job berbasis berkas memakai sha256 sebagai `value`. Digit di dalam hash
    # itu bukan identitas apa pun, tapi _identifier() menganggapnya nomor, lalu
    # SELURUH balasan ditolak sebagai "milik permintaan lain".
    berkas_job = routes.butuh_berkas(bot, cmd)
    if (not berkas_job and result["status"] == "found"
            and relates_to_request(value, texts, result["fields"], cmd) is False):
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

    log.info("verdict %s %s %s -> status=%s fields=%s teks=%d media=%d",
             bot, cmd, value, result["status"],
             "ada" if result.get("fields") else "null",
             len([t for t in texts if t]), len(media_blobs))

    await db.store_result(conn, bot, cmd, value, result["status"],
                          result["msg"], result["fields"],
                          media=media_blobs or None,
                          # teks mentah disimpan supaya perbaikan PARSER bisa
                          # diputar ulang lewat rebuild.py tanpa memotong kuota
                          raw_text="\n\n---\n\n".join(t for t in texts if t) or None)
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

# Berapa halaman TAMBAHAN yang diikuti pada daftar hasil berpaginasi.
#
# Bot memotong daftar ("Menampilkan 1-5" dari 1.412 hasil, tombol "📄 1/283"),
# jadi tanpa ini hanya halaman pertama yang tersimpan. Default 0 = perilaku
# lama, karena belum diketahui apakah menekan Next ikut memotong kuota harian
# per fitur — naikkan lewat env kalau kelengkapan data lebih penting.
HALAMAN_MAKS = int(__import__("os").getenv("HALAMAN_MAKS", "0"))

# Command yang jawabannya bisa disertai foto (E-KTP, foto paspor, dsb).
# Untuk ini kita menunggu sebentar SETELAH teks jawaban, supaya pesan foto
# yang menyusul sebagai pesan terpisah ikut tertangkap.
#
# Daftar lama masih berisi command bot lama (/bionik, /biokk, /photo, /fr,
# /siswa) yang sudah tidak ada, sementara /pasporkerja — satu-satunya command
# yang TERBUKTI mengirim foto (263 KB, image/jpeg) — justru tidak terdaftar.
#
# Catatan: `linger` hanya memengaruhi lama tunggu, bukan apakah foto diunduh;
# _collect_media() tetap mengunduh media apa pun yang menyertai jawaban. Jadi
# command di luar daftar ini masih bisa dapat foto, hanya berisiko terlewat
# kalau fotonya datang beberapa detik setelah teks.
#
# BELUM LENGKAP: sebagian besar command kependudukan belum pernah menghasilkan
# data (kuota harian habis saat pengujian), jadi daftar ini perlu ditinjau
# ulang setelah /nik, /kk, /foto berhasil dijalankan.
PHOTO_CMDS = {"/foto", "/nik", "/kk", "/paspor", "/pasporkerja", "/imigrasi"}
PHOTO_LINGER = 8.0

# Berapa kandidat hasil yang ditelusuri detailnya (lihat Route.kandidat).
KANDIDAT_MAKS = int(__import__("os").getenv("KANDIDAT_MAKS", "10"))

# Jeda senyap untuk alur menu biasa: jawaban dianggap selesai kalau tidak ada
# pesan baru selama sekian detik (lihat MAKS_SENYAP di connector.py).
LINGER_MENU = float(__import__("os").getenv("LINGER_MENU", "5"))


async def _ask_and_parse(tg, bot: str, cmd: str, value: str,
                         timeout: float | None, collect: int,
                         conn_berkas=None) -> dict:
    def _accept(msg) -> bool:
        # Terima pesan non-ack ini sebagai jawaban kita, KECUALI terbukti milik
        # permintaan lain (identitas di dalamnya bentrok dengan `value`) atau
        # cuma peringatan hukum pengantar yang mendahului hasil.
        txt = msg.text or ""
        if parser.is_preamble(txt):
            return False
        records, _ = parser.parse_reply(txt)
        fields = records[0] if len(records) == 1 else (records or None)
        return relates_to_request(value, [txt], fields, cmd) is not False

    # Bot baru sering memecah jawaban jadi beberapa pesan (bagian A-F pada
    # NIK BY PHONE, foto yang menyusul teks). Jadi SEMUA alur menu menunggu
    # senyap dulu, bukan hanya command berfoto.
    menu = routes.menu_label(bot, cmd)
    linger = PHOTO_LINGER if cmd in PHOTO_CMDS else (LINGER_MENU if menu else 0)
    batas = timeout if timeout is not None else FINAL_TIMEOUT
    # Tunggu jawaban asli (non-ack) yang benar-benar milik permintaan ini;
    # jawaban nyasar dilewati sampai jawaban yang tepat datang / timeout.
    choice = routes.submenu_choice(bot, cmd)
    try:
        if routes.butuh_berkas(bot, cmd):
            # `value` berisi id (sha256) berkas yang diunggah lewat
            # POST /search/{bot}/file, bukan teks pencarian.
            blob = await db.get_media(conn_berkas, value) if conn_berkas else None
            if not blob:
                return {"status": "no_response", "fields": None,
                        "msg": f"berkas {value} tidak ditemukan",
                        "_texts": [], "_replies": []}
            replies = await tg.ask_file(bot, menu, bytes(blob["bytes"]),
                                        choice=choice,
                                        timeout=batas, ack_markers=parser.ACK_MARKERS,
                                        accept=None, linger=linger or LINGER_MENU)
            # Hasilnya bisa berupa daftar kandidat yang detailnya baru muncul
            # setelah diklik satu per satu.
            pola = routes.pola_kandidat(bot, cmd)
            if pola and KANDIDAT_MAKS:
                try:
                    replies = replies + await tg.telusuri_kandidat(
                        bot, replies, pola, KANDIDAT_MAKS,
                        ack_markers=parser.ACK_MARKERS)
                except Exception as exc:               # noqa: BLE001
                    log.warning("%s %s: gagal menelusuri kandidat: %r", bot, cmd, exc)
            good = [m for m in replies if not parser.is_preamble(m.text)]
            out = parser.classify([m.text for m in good])
            out["_texts"] = [m.text for m in good]
            out["_replies"] = good
            return out
        replies = await _kirim(tg, bot, cmd, value, menu, choice, batas, _accept, linger)
    except connector.BatasHarian as exc:
        # Kuota fitur habis: kondisi sementara, harus bisa dicoba lagi besok.
        # Jangan dijadikan kegagalan job maupun not_found.
        log.warning("%s %s: batas harian fitur tercapai", bot, cmd)
        return {"status": "queue_without_data", "msg": str(exc), "fields": None,
                "_texts": [str(exc)], "_replies": []}

    # buang preamble hukum & pesan milik permintaan lain sebelum diklasifikasi
    # Ikuti paginasi kalau diminta: halaman berikutnya digabung sebagai
    # balasan tambahan, lalu diurai bersama halaman pertama.
    if HALAMAN_MAKS and replies:
        try:
            replies = replies + await tg.telusuri_halaman(
                bot, replies, HALAMAN_MAKS, ack_markers=parser.ACK_MARKERS)
        except Exception as exc:                       # noqa: BLE001
            log.warning("%s %s: gagal menelusuri halaman: %r", bot, cmd, exc)

    good = [m for m in replies
            if not parser.is_preamble(m.text) and (parser.is_ack(m.text) or _accept(m))]
    texts = [m.text for m in good]
    out = parser.classify(texts)
    out["_texts"] = texts
    out["_replies"] = good
    return out


async def _kirim(tg, bot, cmd, value, menu, choice, batas, _accept, linger):
    """Pilih alur pengiriman sesuai dialek route."""
    if menu and choice:
        # Tiga langkah: menu -> tombol submenu -> nilai.
        replies = await tg.ask_submenu(
            bot, menu, choice, value, timeout=batas,
            ack_markers=parser.ACK_MARKERS, accept=_accept, linger=linger,
        )
    elif menu:
        # Bot menu-driven: label menu dulu, baru nilainya (lihat routes.py).
        replies = await tg.ask_menu(
            bot, menu, value, timeout=batas,
            ack_markers=parser.ACK_MARKERS, accept=_accept, linger=linger,
        )
    else:
        replies = await tg.ask(
            bot, f"{cmd} {value}".strip(), timeout=batas,
            wait_final=True, ack_markers=parser.ACK_MARKERS, accept=_accept,
            linger=linger,
        )
    return replies


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
