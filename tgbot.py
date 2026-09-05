"""Bot Telegram antarmuka (frontend) untuk API arcon.

Bot terpisah (token BotFather sendiri), BUKAN session user yang menghubungi
3 bot data. Alur:

    Pengguna --chat--> bot ini --HTTP+API key--> API arcon --> (session user) --> bot data

Akses dibatasi allowlist (tabel bot_users). Antarmuka menu tombol.

Env (.env): TG_API_ID, TG_API_HASH, TG_BOT_TOKEN, BOT_ADMIN_IDS, API_BASE, API_KEY
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

# key -> (emoji, judul, [(emoji, label, bot, cmd, contoh)])
MENU = {
    "penduduk": ("🧾", "Kependudukan", [
        ("🔎", "Demografi (NIK)",       "bot1", "/nik",     "3201234567890001"),
        ("📋", "Biodata lengkap (NIK)", "bot1", "/bionik",  "3201234567890001"),
        ("👨‍👩‍👧", "Kartu Keluarga (KK)", "bot1", "/kk",    "3201234567890001"),
        ("🔤", "Cari dari Nama",        "bot1", "/nama",    "Budi Santoso"),
        ("🪪", "Foto E-KTP",            "bot1", "/foto",    "3201234567890001"),
    ]),
    "hp": ("📱", "Nomor HP", [
        ("📇", "Registrasi nomor",      "bot1", "/reg",        "6281234567890"),
        ("📲", "Nomor HP dari NIK",     "bot1", "/nohp",       "3201234567890001"),
        ("🔬", "Profiling nomor",       "bot1", "/profnumber", "6281234567890"),
        ("⏳", "Cek masa aktif",        "bot3", "/cekinfo",    "6281234567890"),
    ]),
    "kendaraan": ("🚗", "Kendaraan", [
        ("🔢", "Dari nopol",            "bot1", "/tnkb",     "B1234XYZ"),
        ("⚙️", "Dari nomor mesin",      "bot1", "/nosin",    "nomor mesin"),
        ("🧩", "Dari nomor rangka",     "bot1", "/noka",     "nomor rangka"),
        ("🪪", "Dari NIK",              "bot1", "/niknopol", "3201234567890001"),
    ]),
    "lokasi": ("📍", "Lokasi", [
        ("📡", "Lokasi Telkomsel",      "bot3", "/cptsel", "6281234567890"),
        ("🛰️", "Lacak nomor",           "bot3", "/track",  "6281234567890"),
        ("🗺️", "Linimasa lokasi",       "bot3", "/lm",     "6281234567890"),
    ]),
    "lainnya": ("🗂️", "Data Lain", [
        ("🏥", "BPJS (dari NIK)",       "bot1", "/bpjs",       "3201234567890001"),
        ("💡", "PLN",                   "bot1", "/pln",        "ID pelanggan"),
        ("🚨", "DPO",                   "bot1", "/dpo",        "nama"),
        ("🧑‍🏫", "Guru",                 "bot1", "/guru",       "nama"),
        ("🏢", "Perusahaan (PT)",       "bot3", "/pt",         "nama perusahaan"),
        ("💧", "Kebocoran data",        "bot3", "/leak",       "email / nomor / nik"),
        ("📧", "Email",                 "bot3", "/emailstalker", "nama@email.com"),
    ]),
}

# label field -> (emoji, nama tampil). Field lain otomatis Title Case.
FIELD_LABEL = {
    "nama": ("👤", "Nama"), "nik": ("🆔", "NIK"), "kk": ("👨‍👩‍👧", "No. KK"),
    "ttl": ("🎂", "TTL"), "tempat_lahir": ("📍", "Tempat Lahir"),
    "tanggal_lahir": ("🎂", "Tanggal Lahir"),
    "jenis_kelamin": ("⚧️", "Jenis Kelamin"), "status": ("💍", "Status"),
    "status_kawin": ("💍", "Status Kawin"), "pekerjaan": ("💼", "Pekerjaan"),
    "agama": ("🕌", "Agama"), "pendidikan": ("🎓", "Pendidikan"),
    "alamat": ("🏠", "Alamat"), "kel_desa": ("🏘️", "Kel/Desa"),
    "kel/desa": ("🏘️", "Kel/Desa"), "kecamatan": ("🏙️", "Kecamatan"),
    "kab_kota": ("🌆", "Kab/Kota"), "kab/kota": ("🌆", "Kab/Kota"),
    "provinsi": ("🗺️", "Provinsi"), "nama_ibu": ("👩", "Nama Ibu"),
    "nama_ayah": ("👨", "Nama Ayah"), "shdk": ("🔗", "Hub. Keluarga"),
    "nomor": ("📞", "Nomor"), "operator": ("📶", "Operator"),
    "register": ("📅", "Registrasi"), "msisdn": ("📞", "MSISDN"),
    "imei": ("📟", "IMEI"), "brand": ("📱", "Merek"), "model": ("📱", "Model"),
    "cluster": ("📍", "Area"), "district": ("🏙️", "Distrik"),
}

pending: dict[int, tuple] = {}   # user_id -> (bot, cmd) yang menunggu nilai
busy: set[int] = set()           # user_id yang pencariannya sedang jalan


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


async def add_user(conn, tid: int, by: int, name: str = "") -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO bot_users (telegram_id,name,role,added_by) VALUES (%s,%s,'user',%s) "
            "ON CONFLICT (telegram_id) DO NOTHING", (tid, name, by))


async def touch_seen(conn, tid: int) -> None:
    async with conn.cursor() as cur:
        await cur.execute("UPDATE bot_users SET last_seen_at=now() WHERE telegram_id=%s", (tid,))


async def audit(conn, tid: int, bot: str, cmd: str, value: str, status: str,
                username: str | None = None, name: str | None = None) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            "INSERT INTO bot_audit (telegram_id,username,name,bot,cmd,value,status) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (tid, username, name, bot, cmd, value, status))


# --------------------------------------------------------------- panggil API

def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    if API_KEY:
        h["X-API-Key"] = API_KEY
    return h


def _api_call(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{API_BASE}{path}", data=data, headers=_headers(), method=method)
    with urllib.request.urlopen(req, timeout=140) as r:
        return json.load(r)


def _fetch_media(url_path: str) -> bytes | None:
    """Ambil byte gambar dari API (dipanggil lewat asyncio.to_thread)."""
    req = urllib.request.Request(f"{API_BASE}{url_path}", headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


async def cari(bot: str, cmd: str, value: str, on_update=None,
               requested_by: str = "tgbot") -> dict:
    """Kirim job ke API lalu tunggu hasil.

    Antrian bersifat GLOBAL & serial di sisi API (satu worker, satu-satu).
    `on_update(state, posisi)` dipanggil berkala untuk memperlihatkan posisi
    antrian ke user selama menunggu.
    """
    job = await asyncio.to_thread(_api_call, "POST", f"/search/{bot}",
                                  {"cmd": cmd, "value": value, "requested_by": requested_by})
    if job.get("state") == "done":
        return job
    jid = job.get("job_id")
    if not jid:
        return job

    if on_update:
        await on_update(job.get("state"), job.get("queue_position"))

    loop = asyncio.get_event_loop()
    deadline = loop.time() + 330   # sedikit di atas FINAL_TIMEOUT worker (300s)
    last = job
    while loop.time() < deadline:
        # long-poll 8 detik per putaran; kembali lebih cepat kalau sudah selesai
        last = await asyncio.to_thread(_api_call, "GET", f"/jobs/{jid}?wait=8")
        if last.get("state") in ("done", "failed"):
            return last
        if on_update:
            await on_update(last.get("state"), last.get("queue_position"))
    return last


# ------------------------------------------------------------ format balasan

def _icon_label(key: str) -> tuple[str, str]:
    if key in FIELD_LABEL:
        return FIELD_LABEL[key]
    return "•", key.replace("_", " ").title()


def _fmt_record(rec: dict) -> str:
    baris = []
    # nama di atas kalau ada
    if rec.get("nama"):
        baris.append(f"👤 **{rec['nama']}**")
    for k, v in rec.items():
        if k == "nama" or v in (None, "", "-", "0"):
            continue
        icon, label = _icon_label(k)
        if k in ("coordinate",) or (k == "maps"):
            baris.append(f"🗺️ [Lihat di peta]({v})")
        else:
            baris.append(f"{icon} {label}: `{v}`")
    return "\n".join(baris)


def format_hasil(hasil: dict, judul: str) -> str:
    status = hasil.get("status")
    if status == "found":
        f = hasil.get("fields")
        if isinstance(f, list):
            blok = []
            for i, r in enumerate(f, 1):
                blok.append(f"┌ **Data {i}**\n{_fmt_record(r)}")
            body = "\n\n".join(blok)
            head = f"✅ **Ditemukan {len(f)} data** — {judul}"
        elif isinstance(f, dict):
            body = _fmt_record(f)
            head = f"✅ **Ditemukan** — {judul}"
        else:
            body, head = (hasil.get("msg") or "(kosong)"), f"✅ {judul}"
        return f"{head}\n\n{body}"
    if status == "not_found":
        return (f"❌ **Tidak ditemukan** — {judul}\n\n"
                "Data tidak ada di sumber, atau format input kurang tepat. "
                "Coba periksa lagi nilainya.")
    if status == "queue_without_data":
        return (f"⏳ **Masih diproses** — {judul}\n\n"
                "Sumber data memproses lebih lama dari biasa. Tekan "
                "🔁 Cari lagi untuk melanjutkan.")
    return (f"⚠️ **Tidak ada respons** — {judul}\n\n"
            "Sumber data tidak menjawab. Coba lagi nanti.")


# ------------------------------------------------------------------- keyboard

def kb_home():
    rows, row = [], []
    for key, (emoji, judul, _) in MENU.items():
        row.append(Button.inline(f"{emoji} {judul}", data=f"cat:{key}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    return rows


def kb_command(catkey: str):
    _, _, items = MENU[catkey]
    rows = [[Button.inline(f"{em} {lbl}", data=f"cmd:{bot}:{cmd}")]
            for em, lbl, bot, cmd, _ in items]
    rows.append([Button.inline("⬅️ Menu Utama", data="home")])
    return rows


def kb_after(bot: str, cmd: str):
    return [
        [Button.inline("🔁 Cari lagi", data=f"cmd:{bot}:{cmd}")],
        [Button.inline("🏠 Menu Utama", data="home")],
    ]


def kb_cancel():
    return [[Button.inline("✖️ Batal", data="home")]]


WELCOME = (
    "👋 **Selamat datang di Artemis Bot**\n\n"
    "Bot pencarian data terpadu. Pilih kategori di bawah, lalu ikuti "
    "petunjuknya.\n\n"
    "⚠️ __Gunakan hanya untuk keperluan yang sah dan terotorisasi. "
    "Setiap pencarian tercatat.__"
)


def _contoh(bot: str, cmd: str) -> str:
    for _, _, items in MENU.values():
        for em, lbl, b, cm, ex in items:
            if b == bot and cm == cmd:
                return ex
    return ""


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

    # set daftar command di menu Telegram (tombol "/" & menu hamburger)
    try:
        from telethon.tl.functions.bots import SetBotCommandsRequest
        from telethon.tl.types import BotCommand, BotCommandScopeDefault
        await client(SetBotCommandsRequest(
            scope=BotCommandScopeDefault(), lang_code="id",
            commands=[
                BotCommand("start", "Buka menu pencarian"),
                BotCommand("whoami", "Lihat ID Telegram saya"),
            ]))
    except Exception as e:  # noqa: BLE001
        log.warning("gagal set bot commands: %s", e)

    async def boleh(uid: int) -> dict | None:
        u = await get_user(conn, uid)
        if u:
            await touch_seen(conn, uid)
        return u

    @client.on(events.NewMessage(pattern=r"^/start$"))
    async def _start(ev):
        uid = ev.sender_id
        if not await boleh(uid):
            await ev.respond(
                "🔒 **Akses ditolak**\n\n"
                f"ID Telegram Anda: `{uid}`\n"
                "Kirim ID ini ke admin untuk didaftarkan.")
            return
        await ev.respond(WELCOME, buttons=kb_home())

    @client.on(events.NewMessage(pattern=r"^/allow (\d+)$"))
    async def _allow(ev):
        u = await boleh(ev.sender_id)
        if not u or u["role"] != "admin":
            return
        target = int(ev.pattern_match.group(1))
        await add_user(conn, target, by=ev.sender_id)
        await ev.respond(f"✅ User `{target}` berhasil ditambahkan.")

    @client.on(events.NewMessage(pattern=r"^/whoami$"))
    async def _whoami(ev):
        await ev.respond(f"🆔 ID Telegram Anda: `{ev.sender_id}`")

    @client.on(events.CallbackQuery)
    async def _cb(ev):
        uid = ev.sender_id
        if not await boleh(uid):
            await ev.answer("🔒 Akses ditolak.", alert=True)
            return
        data = ev.data.decode()

        if data == "home":
            pending.pop(uid, None)
            await ev.edit(WELCOME, buttons=kb_home())
            return
        if data.startswith("cat:"):
            catkey = data[4:]
            emoji, judul, _ = MENU[catkey]
            await ev.edit(f"{emoji} **{judul}**\n\nPilih jenis data:",
                          buttons=kb_command(catkey))
            return
        if data.startswith("cmd:"):
            if uid in busy:
                await ev.answer("⏳ Tunggu pencarian sebelumnya selesai dulu.", alert=True)
                return
            _, bot, cmd = data.split(":", 2)
            contoh = _contoh(bot, cmd)
            pending[uid] = (bot, cmd)
            await ev.edit(
                f"✍️ Kirim nilai untuk **{cmd}**\n\n"
                f"Contoh: `{contoh}`\n\n"
                "__Ketik nilainya lalu kirim.__",
                buttons=kb_cancel())
            return

    @client.on(events.NewMessage)
    async def _msg(ev):
        if ev.raw_text.startswith("/"):
            return
        uid = ev.sender_id
        if not await boleh(uid):
            return
        if uid in busy:
            await ev.respond("⏳ Masih memproses pencarian sebelumnya. "
                             "Mohon tunggu sampai selesai dulu.")
            return
        if uid not in pending:
            await ev.respond("Ketik /start untuk membuka menu 📲")
            return

        bot, cmd = pending.pop(uid)
        value = ev.raw_text.strip()
        judul = f"{cmd} `{value}`"
        # identitas pencari (untuk audit & requested_by)
        sender = await ev.get_sender()
        uname = getattr(sender, "username", None)
        fullname = " ".join(filter(None, [getattr(sender, "first_name", None),
                                          getattr(sender, "last_name", None)])) or None
        siapa = f"tgbot:@{uname}" if uname else f"tgbot:{uid}"
        busy.add(uid)
        tunggu = await ev.respond(f"🔍 Mencari {judul} ...\n__mohon tunggu__")

        last_text = {"v": ""}

        async def progres(state, posisi):
            if state == "queued" and posisi:
                teks = (f"⏳ Antre di posisi **{posisi}** ...\n"
                        f"__pencarian {judul} menunggu giliran__")
            else:
                teks = f"🔄 Sedang diproses ...\n__{judul}__"
            if teks != last_text["v"]:          # hindari edit identik (error Telegram)
                last_text["v"] = teks
                try:
                    await tunggu.edit(teks)
                except Exception:               # noqa: BLE001
                    pass

        try:
            hasil = await cari(bot, cmd, value, on_update=progres, requested_by=siapa)
        except (urllib.error.URLError, TimeoutError) as e:
            await tunggu.edit(f"⚠️ Gagal menghubungi server: `{e}`",
                              buttons=kb_after(bot, cmd))
            return
        finally:
            busy.discard(uid)
        await audit(conn, uid, bot, cmd, value, hasil.get("status", "?"),
                    username=uname, name=fullname)
        media = hasil.get("media") or []
        await tunggu.edit(format_hasil(hasil, judul),
                          buttons=kb_after(bot, cmd) if not media else None,
                          link_preview=False)
        # kirim foto (E-KTP dll) kalau ada
        for i, murl in enumerate(media[:10]):
            try:
                blob = await asyncio.to_thread(_fetch_media, murl)
                if blob:
                    last = (i == len(media[:10]) - 1)
                    await client.send_file(
                        uid, blob, force_document=False,
                        buttons=kb_after(bot, cmd) if last else None)
            except Exception as e:  # noqa: BLE001
                log.warning("gagal kirim media: %s", e)

    log.info("siap menerima pesan")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
