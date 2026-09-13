"""Bot Telegram antarmuka RINGKAS — hanya 5 fitur dari teamkhususantibanditbot.

Versi sederhana dari tgbot.py: cuma NIK dari Nomor HP, Kartu Keluarga, Data NIK,
Lacak Nomor HP, dan Face Recognition (Quick Match). Semua lewat API connector
(POST /search/bot1[/file], GET /jobs/{id}, GET /media/{id}); tidak menyentuh
Telegram bot data langsung.

Akses dibatasi allowlist (tabel bot_users). Hasil ditampilkan apa adanya —
seluruh field yang dikembalikan — tanpa disclaimer/basa-basi (API sudah
membersihkannya).

Env (.env): TG_API_ID, TG_API_HASH, TG_BOT_TOKEN, BOT_ADMIN_IDS, API_BASE, API_KEY
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
import uuid

from telethon import Button, TelegramClient, events

import config
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("artemis.tgbot")

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8765")
API_KEY = os.getenv("API_KEY")
ADMIN_IDS = {int(x) for x in os.getenv("BOT_ADMIN_IDS", "").replace(" ", "").split(",") if x}

BOT = "bot1"  # teamkhususantibanditbot

# key -> (emoji, judul, contoh input, butuh_foto). cmd = "/" + key.
KATALOG = [
    ("nikbyphone", "📱", "NIK dari Nomor HP", "nomor HP — contoh 081234567890", False),
    ("kk",         "👨‍👩‍👧", "Kartu Keluarga",   "No. KK 16 digit", False),
    ("nik",        "🆔", "Data NIK",           "NIK 16 digit", False),
    ("track",      "🛰️", "Lacak Nomor HP",     "nomor HP — contoh 081234567890", False),
    ("fr",         "🧑‍💻", "Face Recognition", None, True),
]
INFO = {k: (emoji, judul, contoh, foto) for k, emoji, judul, contoh, foto in KATALOG}

# state per user
pending: dict[int, str] = {}   # user_id -> key fitur yang menunggu input
busy: set[int] = set()

POLL_DEADLINE = 330            # detik; FR + telusuri kandidat bisa lama


# --------------------------------------------------------------- allowlist

async def ensure_admins(conn) -> None:
    for aid in ADMIN_IDS:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO bot_users (telegram_id, role, name) VALUES (%s,'admin','admin') "
                "ON CONFLICT (telegram_id) DO UPDATE SET role='admin'", (aid,))


async def get_user(conn, tid: int) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM bot_users WHERE telegram_id=%s", (tid,))
        return await cur.fetchone()


async def add_user(conn, tid: int, by: int) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO bot_users (telegram_id,role,added_by) VALUES (%s,'user',%s) "
            "ON CONFLICT (telegram_id) DO NOTHING", (tid, by))


async def touch_seen(conn, tid: int) -> None:
    async with conn.cursor() as cur:
        await cur.execute("UPDATE bot_users SET last_seen_at=now() WHERE telegram_id=%s", (tid,))


async def audit(conn, tid, uname, name, cmd, value, status) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO bot_audit (telegram_id,username,name,bot,cmd,value,status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)", (tid, uname, name, BOT, cmd, value, status))


# --------------------------------------------------------------- panggil API

def _headers(extra: dict | None = None) -> dict:
    h = {"X-API-Key": API_KEY} if API_KEY else {}
    if extra:
        h.update(extra)
    return h


def _post_json(cmd: str, value: str, requested_by: str) -> dict:
    body = json.dumps({"cmd": cmd, "value": value, "requested_by": requested_by}).encode()
    req = urllib.request.Request(
        f"{API_BASE}/search/{BOT}", data=body, method="POST",
        headers=_headers({"Content-Type": "application/json"}))
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _post_file(cmd: str, blob: bytes, requested_by: str) -> dict:
    """Kirim foto ke /search/{bot}/file (multipart)."""
    b = uuid.uuid4().hex
    sep = f"--{b}".encode()

    def field(name, val):
        return (sep + b"\r\nContent-Disposition: form-data; name=\"" + name.encode()
                + b"\"\r\n\r\n" + str(val).encode() + b"\r\n")

    body = field("cmd", cmd) + field("requested_by", requested_by)
    body += (sep + b"\r\nContent-Disposition: form-data; name=\"file\"; "
             b"filename=\"foto.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n" + blob + b"\r\n")
    body += sep + b"--\r\n"
    req = urllib.request.Request(
        f"{API_BASE}/search/{BOT}/file", data=body, method="POST",
        headers=_headers({"Content-Type": f"multipart/form-data; boundary={b}"}))
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def _get_job(job_id: str, wait: int = 8) -> dict:
    req = urllib.request.Request(f"{API_BASE}/jobs/{job_id}?wait={wait}", headers=_headers())
    with urllib.request.urlopen(req, timeout=wait + 15) as r:
        return json.load(r)


def _fetch_media(url_path: str) -> bytes | None:
    req = urllib.request.Request(f"{API_BASE}{url_path}", headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


async def jalankan(kirim, on_update=None) -> dict:
    """`kirim` = fungsi sync yang POST job (json/file) dan balas dict awal.
    Lalu poll /jobs sampai selesai, sambil melapor posisi antrian."""
    job = await asyncio.to_thread(kirim)
    if job.get("state") == "done":
        return job
    jid = job.get("job_id")
    if not jid:
        return job
    if on_update:
        await on_update(job.get("state"), job.get("queue_position"))
    loop = asyncio.get_event_loop()
    deadline = loop.time() + POLL_DEADLINE
    last = job
    while loop.time() < deadline:
        last = await asyncio.to_thread(_get_job, jid, 8)
        if last.get("state") in ("done", "failed"):
            return last
        if on_update:
            await on_update(last.get("state"), last.get("queue_position"))
    return last


# ------------------------------------------------------------ format hasil

def _fmt_record(rec: dict) -> str:
    baris = []
    if rec.get("nama"):
        baris.append(f"👤 **{rec['nama']}**")
    for k, v in rec.items():
        if k == "nama" or v in (None, "", "-"):
            continue
        if k == "lainnya" and isinstance(v, dict):
            for lk, lv in v.items():
                if lv not in (None, "", "-"):
                    baris.append(f"• {_label(lk)}: `{lv}`")
            continue
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        baris.append(f"• {_label(k)}: `{v}`")
    return "\n".join(baris)


def _label(k: str) -> str:
    return k.replace("_", " ").title()


def format_hasil(hasil: dict, judul: str) -> str:
    status = hasil.get("status")
    if status == "found":
        f = hasil.get("fields")
        if isinstance(f, list):
            blok = [f"┌ **{i}**\n{_fmt_record(r)}" for i, r in enumerate(f, 1)
                    if isinstance(r, dict)]
            body = "\n\n".join(blok) or (hasil.get("msg") or "(kosong)")
            head = f"✅ Ditemukan {len(blok)} data — {judul}"
        elif isinstance(f, dict):
            body, head = _fmt_record(f), f"✅ Ditemukan — {judul}"
        else:
            body, head = (hasil.get("msg") or "(kosong)"), f"✅ {judul}"
        return f"{head}\n\n{body}"
    if status == "not_found":
        return f"❌ Tidak ditemukan — {judul}"
    if status == "queue_without_data":
        return f"⏳ Masih diproses — {judul}\nCoba lagi sebentar."
    return f"⚠️ Tidak ada respons — {judul}\nCoba lagi nanti."


# ------------------------------------------------------------------- keyboard

def kb_menu():
    rows, row = [], []
    for k, emoji, judul, _c, _f in KATALOG:
        row.append(Button.inline(f"{emoji} {judul}", data=f"f:{k}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows


def kb_kembali():
    return [[Button.inline("🏠 Menu", data="home")]]


WELCOME = "Pilih data yang ingin dicari:"


# --------------------------------------------------------------------- main

async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("TG_BOT_TOKEN belum diisi di .env")
    conn = await db.connect()
    await ensure_admins(conn)

    client = TelegramClient("artemis_bot", config.API_ID, config.API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    log.info("bot ringkas jalan sebagai @%s", me.username)

    try:
        from telethon.tl.functions.bots import SetBotCommandsRequest
        from telethon.tl.types import BotCommand, BotCommandScopeDefault
        await client(SetBotCommandsRequest(
            scope=BotCommandScopeDefault(), lang_code="id",
            commands=[BotCommand("start", "Buka menu"),
                      BotCommand("whoami", "Lihat ID Telegram saya")]))
    except Exception as e:  # noqa: BLE001
        log.warning("gagal set commands: %s", e)

    async def boleh(uid):
        u = await get_user(conn, uid)
        if u:
            await touch_seen(conn, uid)
        return u

    async def identitas(ev):
        s = await ev.get_sender()
        uname = getattr(s, "username", None)
        nama = " ".join(filter(None, [getattr(s, "first_name", None),
                                      getattr(s, "last_name", None)])) or None
        return uname, nama

    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def _start(ev):
        if not await boleh(ev.sender_id):
            await ev.respond(f"🔒 Akses ditolak.\nID Telegram Anda: `{ev.sender_id}`\n"
                             "Kirim ID ini ke admin untuk didaftarkan.")
            return
        pending.pop(ev.sender_id, None)
        await ev.respond(WELCOME, buttons=kb_menu())

    @client.on(events.NewMessage(pattern=r"^/whoami$"))
    async def _whoami(ev):
        await ev.respond(f"🆔 ID Telegram Anda: `{ev.sender_id}`")

    @client.on(events.NewMessage(pattern=r"^/allow (\d+)$"))
    async def _allow(ev):
        u = await boleh(ev.sender_id)
        if not u or u["role"] != "admin":
            return
        await add_user(conn, int(ev.pattern_match.group(1)), ev.sender_id)
        await ev.respond(f"✅ User `{ev.pattern_match.group(1)}` ditambahkan.")

    @client.on(events.CallbackQuery)
    async def _cb(ev):
        uid = ev.sender_id
        if not await boleh(uid):
            await ev.answer("🔒 Akses ditolak.", alert=True)
            return
        data = ev.data.decode()
        if data == "home":
            pending.pop(uid, None)
            await ev.edit(WELCOME, buttons=kb_menu())
            return
        if data.startswith("f:"):
            if uid in busy:
                await ev.answer("⏳ Tunggu pencarian sebelumnya selesai.", alert=True)
                return
            key = data[2:]
            if key not in INFO:
                return
            emoji, judul, contoh, foto = INFO[key]
            pending[uid] = key
            if foto:
                await ev.edit(f"{emoji} **{judul}**\n\n📷 Kirim **foto wajah** yang ingin dicari.",
                              buttons=kb_kembali())
            else:
                await ev.edit(f"{emoji} **{judul}**\n\nKirim {contoh}.", buttons=kb_kembali())

    async def proses(ev, key, value_desc, kirim):
        uid = ev.sender_id
        emoji, judul, _c, _f = INFO[key]
        cmd = "/" + key
        busy.add(uid)
        tunggu = await ev.respond(f"🔍 Mencari {judul} ...")
        last = {"v": ""}

        async def progres(state, posisi):
            t = (f"⏳ Antre posisi {posisi} ..." if state == "queued" and posisi
                 else "🔄 Sedang diproses ...")
            if t != last["v"]:
                last["v"] = t
                try:
                    await tunggu.edit(t)
                except Exception:  # noqa: BLE001
                    pass

        try:
            hasil = await jalankan(kirim, on_update=progres)
        except (urllib.error.URLError, TimeoutError) as e:
            await tunggu.edit(f"⚠️ Gagal menghubungi server: `{e}`", buttons=kb_kembali())
            busy.discard(uid)
            return
        busy.discard(uid)

        uname, nama = await identitas(ev)
        await audit(conn, uid, uname, nama, cmd, value_desc, hasil.get("status", "?"))
        media = hasil.get("media") or []
        await tunggu.edit(format_hasil(hasil, judul),
                          buttons=None if media else kb_kembali(), link_preview=False)
        for i, murl in enumerate(media[:10]):
            try:
                blob = await asyncio.to_thread(_fetch_media, murl)
                if blob:
                    await client.send_file(uid, blob, force_document=False,
                                           buttons=kb_kembali() if i == len(media[:10]) - 1 else None)
            except Exception as e:  # noqa: BLE001
                log.warning("gagal kirim media: %s", e)

    @client.on(events.NewMessage)
    async def _msg(ev):
        if ev.raw_text.startswith("/"):
            return
        uid = ev.sender_id
        if not await boleh(uid):
            return
        key = pending.get(uid)
        if not key:
            if ev.photo:
                return
            await ev.respond("Ketik /start untuk membuka menu 📲")
            return
        if uid in busy:
            await ev.respond("⏳ Masih memproses pencarian sebelumnya.")
            return
        _emoji, _judul, _c, foto = INFO[key]
        cmd = "/" + key
        uname, nama = await identitas(ev)
        siapa = f"tgbot:@{uname}" if uname else f"tgbot:{uid}"

        if foto:
            if not ev.photo:
                await ev.respond("📷 Kirim **foto wajah**, bukan teks.")
                return
            pending.pop(uid, None)
            blob = await ev.download_media(file=bytes)
            await proses(ev, key, "foto", lambda: _post_file(cmd, blob, siapa))
        else:
            if ev.photo:
                await ev.respond("Fitur ini butuh teks, bukan foto.")
                return
            value = ev.raw_text.strip()
            pending.pop(uid, None)
            await proses(ev, key, value, lambda: _post_json(cmd, value, siapa))

    log.info("siap menerima pesan")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
