"""Bot Telegram antarmuka (frontend) untuk API arcon.

Ini bot terpisah (token BotFather sendiri), BUKAN session user yang menghubungi
3 bot data. Alur:

    Pengguna --chat--> bot ini --HTTP+API key--> API arcon --> (session user) --> bot data

Bot Telegram tidak bisa mengirim pesan ke bot lain, jadi bot ini tidak
menghubungi bot data langsung; ia memanggil API arcon yang menanganinya.

Akses dibatasi allowlist (tabel bot_users). Antarmuka berupa menu tombol.

Env yang dibutuhkan (.env):
    TG_API_ID, TG_API_HASH   - sudah ada (kredensial aplikasi)
    TG_BOT_TOKEN             - token dari @BotFather
    BOT_ADMIN_IDS            - ID Telegram admin (pisah koma), auto jadi admin
    API_BASE                 - default http://127.0.0.1:8765
    API_KEY                  - sudah ada
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request

from telethon import Button, TelegramClient, events

import config
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("artemis.tgbot")

BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8765")
API_KEY = os.getenv("API_KEY")
ADMIN_IDS = {int(x) for x in os.getenv("BOT_ADMIN_IDS", "").replace(" ", "").split(",") if x}

# ------------------------------------------------------------ menu & command

# Kategori -> daftar (label, bot, cmd, contoh input). Command yang ada di dua
# bot dipilih salah satu yang paling relevan.
MENU = {
    "penduduk": ("Kependudukan", [
        ("Demografi (NIK)",      "bot1", "/nik",     "NIK 16 digit"),
        ("Biodata lengkap (NIK)", "bot1", "/bionik", "NIK 16 digit"),
        ("Kartu Keluarga (KK)",  "bot1", "/kk",      "No. KK 16 digit"),
        ("Cari dari Nama",       "bot1", "/nama",    "nama lengkap"),
        ("Foto E-KTP",           "bot1", "/foto",    "NIK 16 digit"),
    ]),
    "hp": ("Nomor HP", [
        ("Registrasi nomor",     "bot1", "/reg",        "628xxxxxxxxxx"),
        ("Nomor HP dari NIK",    "bot1", "/nohp",       "NIK 16 digit"),
        ("Profiling nomor",      "bot1", "/profnumber", "628xxxxxxxxxx"),
        ("Cek masa aktif",       "bot3", "/cekinfo",    "628xxxxxxxxxx"),
    ]),
    "kendaraan": ("Kendaraan", [
        ("Dari nopol",           "bot1", "/tnkb",     "mis. B1234XYZ"),
        ("Dari nomor mesin",     "bot1", "/nosin",    "nomor mesin"),
        ("Dari nomor rangka",    "bot1", "/noka",     "nomor rangka"),
        ("Dari NIK",             "bot1", "/niknopol", "NIK 16 digit"),
    ]),
    "lokasi": ("Lokasi", [
        ("Lokasi Telkomsel",     "bot3", "/cptsel", "628xxxxxxxxxx"),
        ("Lacak nomor",          "bot3", "/track",  "628xxxxxxxxxx"),
        ("Linimasa lokasi",      "bot3", "/lm",     "628xxxxxxxxxx"),
    ]),
    "lainnya": ("Data Lain", [
        ("BPJS (dari NIK)",      "bot1", "/bpjs",      "NIK 16 digit"),
        ("PLN",                  "bot1", "/pln",       "ID pelanggan"),
        ("DPO",                  "bot1", "/dpo",       "nama"),
        ("Guru",                 "bot1", "/guru",      "nama"),
        ("Perusahaan (PT)",      "bot3", "/pt",        "nama perusahaan"),
        ("Kebocoran data",       "bot3", "/leak",      "email/nomor/nik"),
        ("Email",                "bot3", "/emailstalker", "alamat email"),
    ]),
}

# state sederhana: user_id -> (bot, cmd, label, contoh) yang sedang ditunggu nilainya
pending: dict[int, tuple] = {}


# --------------------------------------------------------------- allowlist

async def ensure_admins(conn) -> None:
    for aid in ADMIN_IDS:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                INSERT INTO bot_users (telegram_id, role, name)
                VALUES (%s, 'admin', 'admin')
                ON CONFLICT (telegram_id) DO UPDATE SET role = 'admin'
                """,
                (aid,),
            )


async def get_user(conn, telegram_id: int) -> dict | None:
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM bot_users WHERE telegram_id = %s", (telegram_id,))
        return await cur.fetchone()


async def add_user(conn, telegram_id: int, by: int, name: str = "") -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO bot_users (telegram_id, name, role, added_by)
            VALUES (%s, %s, 'user', %s)
            ON CONFLICT (telegram_id) DO NOTHING
            """,
            (telegram_id, name, by),
        )


async def touch_seen(conn, telegram_id: int) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "UPDATE bot_users SET last_seen_at = now() WHERE telegram_id = %s",
            (telegram_id,),
        )


async def audit(conn, telegram_id: int, bot: str, cmd: str, value: str, status: str) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO bot_audit (telegram_id, bot, cmd, value, status) VALUES (%s,%s,%s,%s,%s)",
            (telegram_id, bot, cmd, value, status),
        )


# --------------------------------------------------------------- panggil API

def _api_call(method: str, path: str, body: dict | None = None) -> dict:
    """Panggil API arcon (blocking; dipanggil lewat asyncio.to_thread)."""
    data = json.dumps(body).encode() if body is not None else None
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["X-API-Key"] = API_KEY
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=140) as r:
        return json.load(r)


async def cari(bot: str, cmd: str, value: str) -> dict:
    job = await asyncio.to_thread(_api_call, "POST", f"/search/{bot}",
                                  {"cmd": cmd, "value": value, "requested_by": "tgbot"})
    if job.get("state") == "done":
        return job
    job_id = job.get("job_id")
    if not job_id:
        return job
    return await asyncio.to_thread(_api_call, "GET", f"/jobs/{job_id}?wait=120")


# ------------------------------------------------------------ format balasan

def _fmt_record(rec: dict) -> str:
    baris = []
    for k, v in rec.items():
        if v in (None, "", "-"):
            continue
        label = k.replace("_", " ").title()
        baris.append(f"**{label}:** {v}")
    return "\n".join(baris)


def format_hasil(hasil: dict, label: str) -> str:
    status = hasil.get("status")
    if status == "found":
        f = hasil.get("fields")
        if isinstance(f, list):
            blok = [f"**{i}.**\n{_fmt_record(r)}" for i, r in enumerate(f, 1)]
            body = "\n\n".join(blok)
        elif isinstance(f, dict):
            body = _fmt_record(f)
        else:
            body = hasil.get("msg") or "(data kosong)"
        return f"[OK] {label}\n\n{body}"
    if status == "not_found":
        return f"[X] {label}\nData tidak ditemukan.\n{hasil.get('msg') or ''}".strip()
    if status == "queue_without_data":
        return (f"[...] {label}\nBot penyedia sedang sibuk / belum membalas. "
                "Coba lagi beberapa saat.")
    return f"[!] {label}\nTidak ada respons dari penyedia. Coba lagi nanti."


# ------------------------------------------------------------------- keyboard

def menu_kategori():
    rows, row = [], []
    for key, (label, _) in MENU.items():
        row.append(Button.inline(label, data=f"cat:{key}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows


def menu_command(catkey: str):
    _, items = MENU[catkey]
    rows = [[Button.inline(lbl, data=f"cmd:{bot}:{cmd}")] for lbl, bot, cmd, _ in items]
    rows.append([Button.inline("<< Menu Utama", data="home")])
    return rows


# --------------------------------------------------------------------- main

async def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("TG_BOT_TOKEN belum diisi di .env")

    conn = await db.connect()
    await ensure_admins(conn)

    client = TelegramClient("artemis_bot", config.API_ID, config.API_HASH)
    await client.start(bot_token=BOT_TOKEN)
    me = await client.get_me()
    log.info("bot jalan sebagai @%s", me.username)

    async def boleh(uid: int) -> dict | None:
        u = await get_user(conn, uid)
        if u:
            await touch_seen(conn, uid)
        return u

    @client.on(events.NewMessage(pattern=r"/start"))
    async def _start(ev):
        uid = ev.sender_id
        u = await boleh(uid)
        if not u:
            await ev.respond(
                "Akses ditolak.\n\nID Telegram Anda: `%d`\n"
                "Minta admin menambahkan ID ini." % uid)
            return
        await ev.respond("Selamat datang di Artemis Bot.\nPilih kategori:",
                         buttons=menu_kategori())

    @client.on(events.NewMessage(pattern=r"/allow (\d+)"))
    async def _allow(ev):
        u = await boleh(ev.sender_id)
        if not u or u["role"] != "admin":
            return
        target = int(ev.pattern_match.group(1))
        await add_user(conn, target, by=ev.sender_id)
        await ev.respond(f"User `{target}` ditambahkan.")

    @client.on(events.NewMessage(pattern=r"/whoami"))
    async def _whoami(ev):
        await ev.respond(f"ID Telegram Anda: `{ev.sender_id}`")

    @client.on(events.CallbackQuery)
    async def _cb(ev):
        uid = ev.sender_id
        u = await boleh(uid)
        if not u:
            await ev.answer("Akses ditolak.", alert=True)
            return
        data = ev.data.decode()

        if data == "home":
            await ev.edit("Pilih kategori:", buttons=menu_kategori())
            return
        if data.startswith("cat:"):
            catkey = data[4:]
            label = MENU[catkey][0]
            await ev.edit(f"Kategori: {label}\nPilih data:",
                          buttons=menu_command(catkey))
            return
        if data.startswith("cmd:"):
            _, bot, cmd = data.split(":", 2)
            contoh = next((c for _, b, cm, c in sum((v[1] for v in MENU.values()), [])
                           if b == bot and cm == cmd), "")
            pending[uid] = (bot, cmd, cmd, contoh)
            await ev.edit(f"Kirim nilai untuk **{cmd}**\nContoh: {contoh}")
            return

    @client.on(events.NewMessage)
    async def _msg(ev):
        if ev.raw_text.startswith("/"):
            return  # command ditangani handler lain
        uid = ev.sender_id
        u = await boleh(uid)
        if not u:
            return
        if uid not in pending:
            await ev.respond("Ketik /start untuk membuka menu.")
            return

        bot, cmd, label, _ = pending.pop(uid)
        value = ev.raw_text.strip()
        tunggu = await ev.respond(f"Mencari {cmd} {value} ...")
        try:
            hasil = await cari(bot, cmd, value)
        except (urllib.error.URLError, TimeoutError) as e:
            await tunggu.edit(f"Gagal menghubungi API: {e}")
            return
        await audit(conn, uid, bot, cmd, value, hasil.get("status", "?"))
        await tunggu.edit(format_hasil(hasil, f"{cmd} {value}"),
                          buttons=[[Button.inline("<< Menu Utama", data="home")]])

    log.info("siap menerima pesan")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
