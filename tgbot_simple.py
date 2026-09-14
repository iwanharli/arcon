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
import re
import urllib.error
import urllib.parse
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

# Batas pencarian per user per hari (0 = tanpa batas). Melindungi kuota harian
# bot sumber supaya tidak dihabiskan satu user. Admin dikecualikan.
LIMIT_HARIAN = int(os.getenv("LIMIT_HARIAN_USER", "40"))

# state per user
pending: dict[int, str] = {}          # user_id -> key fitur yang menunggu input
busy: set[int] = set()
tebak: dict[int, str] = {}            # user_id -> nilai diketik langsung, tunggu pilih fitur
batal_ev: dict[int, asyncio.Event] = {}   # user_id -> sinyal Batal saat menunggu
admin_aksi: dict[int, str] = {}       # admin_id -> 'add'|'del', menunggu ID user

# Validasi input sebelum menembak bot (hemat kuota kalau salah ketik).
HP_RE = re.compile(r"^(?:\+?62|0)8\d{7,12}$")
D16_RE = re.compile(r"^\d{16}$")
# Ambil LAT/LON dari teks "LAT: -6.37 LON: 106.89" untuk bikin link Google Maps.
KOORD_RE = re.compile(r"LAT[:\s]*(-?\d+\.\d+).*?LON[:\s]*(-?\d+\.\d+)", re.I)


def _bersih_hp(v: str) -> str:
    return re.sub(r"[\s.\-()]", "", v)


def validasi(key: str, value: str) -> str | None:
    """Kembalikan pesan error kalau format salah, atau None kalau valid."""
    v = value.strip()
    if key in ("nikbyphone", "track"):
        if not HP_RE.match(_bersih_hp(v)):
            return ("❌ Nomor HP tidak valid.\nContoh benar: `081234567890` atau "
                    "`6281234567890`.")
    elif key in ("nik", "kk"):
        if not D16_RE.match(v):
            label = "NIK" if key == "nik" else "No. KK"
            return f"❌ {label} harus tepat **16 digit angka**."
    return None


def maps_link(rec: dict) -> str | None:
    """Link Google Maps dari record /track: pakai yang sudah ada, atau bangun
    dari koordinat LAT/LON."""
    for v in rec.values():
        if isinstance(v, str) and ("maps.google" in v or "google.com/maps" in v):
            return v.split()[0]
    for v in rec.values():
        if isinstance(v, str):
            m = KOORD_RE.search(v)
            if m:
                return f"https://maps.google.com/?q={m.group(1)},{m.group(2)}"
    return None

# Job yang menembak Telegram bisa lama: rata-rata terukur ~52 detik, maksimum
# ~460 detik (FR + telusuri kandidat). Deadline poll dibuat 600 detik supaya
# tampilan tidak menyerah sebelum hasil benar-benar datang.
POLL_DEADLINE = 600            # detik
# Perkiraan waktu per pencarian baru (avg ~52s + JEDA_ANTAR_JOB 10s), dipakai
# menghitung estimasi tunggu yang ditampilkan ke user.
PERKIRAAN_PER_JOB = 60         # detik
# Antrian lebih panjang dari ini ditolak halus: user diminta coba beberapa
# menit lagi, dan job-nya dibatalkan supaya tidak memboroskan kuota harian.
MAX_ANTRE = 8


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


# Status audit yang TIDAK dihitung sebagai pemakaian kuota (tidak menembak bot).
_TAK_HITUNG = ("ditolak_format", "antre_penuh", "limit_user", "akses_ditolak", "batal")


async def pakai_hari_ini(conn, tid: int) -> int:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT count(*) AS n FROM bot_audit WHERE telegram_id=%s "
            "AND created_at::date = current_date AND status <> ALL(%s)",
            (tid, list(_TAK_HITUNG)))
        return (await cur.fetchone())["n"]


async def list_users(conn) -> list[dict]:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT telegram_id, role, name, last_seen_at FROM bot_users "
            "ORDER BY role, telegram_id")
        return await cur.fetchall()


async def del_user(conn, tid: int) -> bool:
    """Hapus user dari allowlist. Admin tidak bisa dihapus lewat sini."""
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM bot_users WHERE telegram_id=%s AND role<>'admin' "
            "RETURNING telegram_id", (tid,))
        return await cur.fetchone() is not None


async def statistik(conn) -> dict:
    async with conn.cursor() as cur:
        await cur.execute("SELECT state, count(*) n FROM search_jobs GROUP BY state")
        antre = {r["state"]: r["n"] for r in await cur.fetchall()}
        await cur.execute(
            "SELECT count(*) n, count(*) FILTER (WHERE status='found') ok "
            "FROM bot_audit WHERE created_at::date=current_date")
        hari = await cur.fetchone()
        await cur.execute("SELECT count(*) n FROM bot_users")
        users = (await cur.fetchone())["n"]
    return {"antre": antre, "hari": hari, "users": users}


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


def _cancel_job(job_id: str) -> bool:
    req = urllib.request.Request(f"{API_BASE}/jobs/{job_id}", method="DELETE",
                                 headers=_headers())
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return bool(json.load(r).get("ok"))
    except Exception:  # noqa: BLE001
        return False


def _eta(detik: int) -> str:
    """Detik -> teks estimasi ringkas: '±40 detik' / '±3 menit'."""
    if detik < 90:
        return f"±{max(detik, 5)} detik"
    return f"±{round(detik / 60)} menit"


class AntrePenuh(Exception):
    """Antrian melebihi MAX_ANTRE — permintaan ditolak halus."""

    def __init__(self, posisi: int):
        self.posisi = posisi


async def jalankan(kirim, on_update=None, stop_event=None, on_job=None) -> dict:
    """`kirim` = fungsi sync yang POST job (json/file) dan balas dict awal.

    Setelah enqueue, poll /jobs sampai selesai sambil melapor posisi antrian
    dan estimasi tunggu. Kalau antrian sudah lebih panjang dari MAX_ANTRE, job
    dibatalkan dan AntrePenuh dilempar supaya pemanggil bisa memberi tahu user
    tanpa membuang kuota. `stop_event` yang di-set membatalkan job (tombol
    Batal); `on_job(jid)` dipanggil begitu job_id diketahui."""
    job = await asyncio.to_thread(kirim)
    if job.get("state") == "done":
        return job
    jid = job.get("job_id")
    if not jid:
        return job
    if on_job:
        on_job(jid)

    posisi = job.get("queue_position")
    if job.get("state") == "queued" and posisi and posisi > MAX_ANTRE:
        await asyncio.to_thread(_cancel_job, jid)
        raise AntrePenuh(posisi)

    if on_update:
        await on_update(job.get("state"), posisi)
    loop = asyncio.get_event_loop()
    deadline = loop.time() + POLL_DEADLINE
    last = job
    while loop.time() < deadline:
        if stop_event and stop_event.is_set():
            await asyncio.to_thread(_cancel_job, jid)
            return {"state": "cancelled"}
        last = await asyncio.to_thread(_get_job, jid, 8)
        if last.get("state") in ("done", "failed"):
            return last
        if on_update:
            await on_update(last.get("state"), last.get("queue_position"))
    return last     # habis deadline tapi belum selesai -> ditangani pemanggil


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


def potong_pesan(teks: str, maks: int = 4000) -> list[str]:
    """Pecah teks panjang jadi beberapa bagian <= maks char (batas Telegram
    ~4096). Diusahakan memotong di batas antar-record ("\\n\\n"), lalu per baris,
    supaya kartu data tidak terbelah di tengah."""
    if len(teks) <= maks:
        return [teks]
    bagian, buf = [], ""
    for blok in teks.split("\n\n"):
        if len(blok) > maks:                     # satu blok pun kepanjangan
            for baris in blok.split("\n"):
                if len(buf) + len(baris) + 1 > maks:
                    bagian.append(buf.rstrip()); buf = ""
                buf += baris + "\n"
            continue
        if len(buf) + len(blok) + 2 > maks:
            bagian.append(buf.rstrip()); buf = ""
        buf += blok + "\n\n"
    if buf.strip():
        bagian.append(buf.rstrip())
    return bagian


_LIMIT_KATA = ("batas penggunaan", "limit tercapai", "kuota", "quota", "coba lagi besok")


def format_hasil(hasil: dict, judul: str) -> str:
    if hasil.get("state") == "cancelled":
        return f"🛑 Pencarian **{judul}** dibatalkan."
    # Deadline poll habis tapi job belum selesai: hasilnya tetap diproses di
    # server dan tersimpan di cache, jadi user cukup mengulang sebentar lagi.
    if hasil.get("state") not in ("done", None) and not hasil.get("status"):
        return (f"⏳ **{judul}** masih diproses server.\n\n"
                "Antrian sedang panjang. Hasilnya akan tersimpan otomatis — "
                "coba lagi beberapa menit lagi lewat menu, hasilnya muncul instan.")
    status = hasil.get("status")
    # Kuota harian fitur di bot sumber habis — bukan "data tidak ada".
    if status == "queue_without_data":
        msg = (hasil.get("msg") or "").lower()
        if any(k in msg for k in _LIMIT_KATA):
            return (f"🔴 **Kuota harian fitur {judul} habis.**\n"
                    "Sudah mencapai batas pemakaian hari ini di sumber data. "
                    "Silakan coba lagi besok.")
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


def kb_batal():
    return [[Button.inline("🛑 Batal", data="batal")]]


def kb_hasil(maps_url: str | None = None):
    rows = []
    if maps_url:
        rows.append([Button.url("📍 Buka Google Maps", maps_url)])
    rows.append([Button.inline("🏠 Menu", data="home")])
    return rows


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
                      BotCommand("menu", "Buka menu"),
                      BotCommand("help", "Bantuan & daftar fitur"),
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

    async def minta_akses(ev):
        """Teruskan permintaan akses ke semua admin dengan tombol Izinkan."""
        uid = ev.sender_id
        uname, nama = await identitas(ev)
        siapa = f"@{uname}" if uname else (nama or "-")
        await audit(conn, uid, uname, nama, "/start", "", "akses_ditolak")
        for aid in ADMIN_IDS:
            try:
                await client.send_message(
                    aid, f"🔔 **Permintaan akses baru**\nNama: {nama or '-'}\n"
                    f"Username: {siapa}\nID: `{uid}`",
                    buttons=[[Button.inline("✅ Izinkan", data=f"izinkan:{uid}")]])
            except Exception:  # noqa: BLE001
                pass

    @client.on(events.NewMessage(pattern=r"^/(start|menu|help)$"))
    async def _start(ev):
        if not await boleh(ev.sender_id):
            await ev.respond(f"🔒 Akses ditolak.\nID Telegram Anda: `{ev.sender_id}`\n"
                             "Permintaan Anda sudah diteruskan ke admin. Mohon tunggu.")
            await minta_akses(ev)
            return
        pending.pop(ev.sender_id, None)
        await ev.respond(WELCOME, buttons=kb_menu())

    @client.on(events.NewMessage(pattern=r"^/users$"))
    async def _users(ev):
        u = await boleh(ev.sender_id)
        if not u or u["role"] != "admin":
            return
        rows = await list_users(conn)
        baris = []
        for r in rows:
            tag = "👑" if r["role"] == "admin" else "•"
            seen = r["last_seen_at"].strftime("%d/%m %H:%M") if r["last_seen_at"] else "-"
            baris.append(f"{tag} `{r['telegram_id']}` — {r['name'] or '-'} (aktif: {seen})")
        await ev.respond(f"👥 **{len(rows)} user terdaftar**\n\n" + "\n".join(baris) +
                         "\n\nHapus: `/deny <id>`  •  Tambah: `/allow <id>`")

    @client.on(events.NewMessage(pattern=r"^/deny (\d+)$"))
    async def _deny(ev):
        u = await boleh(ev.sender_id)
        if not u or u["role"] != "admin":
            return
        target = int(ev.pattern_match.group(1))
        ok = await del_user(conn, target)
        await ev.respond(f"🗑️ User `{target}` dihapus." if ok
                         else f"⚠️ `{target}` tidak ada / admin (tak bisa dihapus).")

    async def teks_stats() -> str:
        s = await statistik(conn)
        a = s["antre"]
        return ("📊 **Statistik**\n"
                f"• Antrian: {a.get('queued', 0)} antre, {a.get('running', 0)} jalan\n"
                f"• Hari ini: {s['hari']['n']} pencarian ({s['hari']['ok']} ketemu)\n"
                f"• Total user: {s['users']}\n"
                f"• Batas harian/user: {LIMIT_HARIAN or 'tanpa batas'}")

    async def teks_users() -> str:
        rows = await list_users(conn)
        baris = []
        for r in rows:
            tag = "👑" if r["role"] == "admin" else "•"
            seen = r["last_seen_at"].strftime("%d/%m %H:%M") if r["last_seen_at"] else "-"
            baris.append(f"{tag} `{r['telegram_id']}` — {r['name'] or '-'} (aktif: {seen})")
        return f"👥 **{len(rows)} user terdaftar**\n\n" + "\n".join(baris)

    def kb_admin():
        return [[Button.inline("👥 Daftar User", data="adm:users"),
                 Button.inline("📊 Statistik", data="adm:stats")],
                [Button.inline("➕ Tambah User", data="adm:add"),
                 Button.inline("🗑️ Hapus User", data="adm:del")],
                [Button.inline("🏠 Menu utama", data="home")]]

    @client.on(events.NewMessage(pattern=r"^/stats$"))
    async def _stats(ev):
        u = await boleh(ev.sender_id)
        if not u or u["role"] != "admin":
            return
        await ev.respond(await teks_stats())

    @client.on(events.NewMessage(pattern=r"^/admin$"))
    async def _admin(ev):
        u = await boleh(ev.sender_id)
        if not u or u["role"] != "admin":
            return
        admin_aksi.pop(ev.sender_id, None)
        await ev.respond("🛠️ **Panel Admin**\nPilih tindakan:", buttons=kb_admin())

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
            tebak.pop(uid, None)
            await ev.edit(WELCOME, buttons=kb_menu())
            return
        if data == "batal":
            evt = batal_ev.get(uid)
            if evt:
                evt.set()
                await ev.answer("Membatalkan ...")
            else:
                await ev.answer("Tidak ada pencarian berjalan.")
            return
        # Panel admin.
        if data.startswith("adm:"):
            u = await get_user(conn, uid)
            if not u or u["role"] != "admin":
                await ev.answer("Hanya admin.", alert=True)
                return
            aksi = data[4:]
            if aksi == "users":
                await ev.edit(await teks_users(), buttons=kb_admin())
            elif aksi == "stats":
                await ev.edit(await teks_stats(), buttons=kb_admin())
            elif aksi == "add":
                admin_aksi[uid] = "add"
                await ev.edit("➕ Kirim **ID Telegram** user yang mau ditambahkan.\n"
                              "(angka saja, atau /admin untuk batal)", buttons=kb_admin())
            elif aksi == "del":
                admin_aksi[uid] = "del"
                await ev.edit("🗑️ Kirim **ID Telegram** user yang mau dihapus.\n"
                              "(angka saja, atau /admin untuk batal)", buttons=kb_admin())
            return
        # Admin menekan "Izinkan" dari notifikasi permintaan akses.
        if data.startswith("izinkan:"):
            u = await get_user(conn, uid)
            if not u or u["role"] != "admin":
                await ev.answer("Hanya admin.", alert=True)
                return
            target = int(data.split(":", 1)[1])
            await add_user(conn, target, uid)
            await ev.edit(f"✅ User `{target}` diizinkan.")
            try:
                await client.send_message(target, "✅ Akses Anda disetujui admin. "
                                          "Ketik /start untuk mulai.")
            except Exception:  # noqa: BLE001
                pass
            return
        # Pilih fitur untuk nilai yang sudah diketik langsung (deteksi otomatis).
        if data.startswith("go:"):
            key = data[3:]
            nilai = tebak.get(uid)
            if key not in INFO or not nilai:
                await ev.answer("Ketik ulang nilainya ya.")
                return
            if uid in busy:
                await ev.answer("⏳ Tunggu pencarian sebelumnya selesai.", alert=True)
                return
            tolak = await cek_kuota(uid)
            if tolak:
                await ev.edit(tolak, buttons=kb_kembali())
                return
            tebak.pop(uid, None)
            pending.pop(uid, None)
            uname = (await identitas(ev))[0]
            siapa = f"tgbot:@{uname}" if uname else f"tgbot:{uid}"
            await ev.delete()
            await proses(ev, key, nilai, lambda: _post_json("/" + key, nilai, siapa))
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

    async def cek_kuota(uid) -> str | None:
        """None kalau boleh; pesan penolakan kalau kuota harian habis."""
        if LIMIT_HARIAN <= 0 or uid in ADMIN_IDS:
            return None
        u = await get_user(conn, uid)
        if u and u["role"] == "admin":
            return None
        n = await pakai_hari_ini(conn, uid)
        if n >= LIMIT_HARIAN:
            return (f"🔴 **Batas harian tercapai** ({LIMIT_HARIAN} pencarian/hari).\n"
                    "Jatah Anda akan kembali besok. Terima kasih.")
        return None

    async def proses(ev, key, value_desc, kirim):
        uid = ev.sender_id
        emoji, judul, _c, _f = INFO[key]
        cmd = "/" + key
        busy.add(uid)
        ev_batal = asyncio.Event()
        batal_ev[uid] = ev_batal
        tunggu = await ev.respond(f"🔍 Menyiapkan pencarian **{judul}** ...",
                                  buttons=kb_batal())
        last = {"v": ""}

        async def progres(state, posisi):
            if state == "queued" and posisi:
                bar = "▰" * min(posisi, 10) + "▱" * max(0, 10 - posisi)
                t = (f"⏳ **Antre** — posisi {posisi}\n`{bar}`\n"
                     f"Perkiraan tunggu: {_eta(posisi * PERKIRAAN_PER_JOB)}")
            else:
                t = f"🔄 **Memproses {judul}** ...\nSedang mengambil data, mohon tunggu."
            if t != last["v"]:
                last["v"] = t
                try:
                    await tunggu.edit(t, buttons=kb_batal())
                except Exception:  # noqa: BLE001
                    pass

        uname, nama = await identitas(ev)
        try:
            hasil = await jalankan(kirim, on_update=progres, stop_event=ev_batal,
                                   on_job=lambda jid: None)
        except AntrePenuh as e:
            await tunggu.edit(
                f"🚦 **Antrian sedang penuh** (posisi {e.posisi}).\n\n"
                f"Perkiraan tunggu {_eta(e.posisi * PERKIRAAN_PER_JOB)} — terlalu lama. "
                "Silakan coba lagi beberapa menit lagi lewat menu.",
                buttons=kb_kembali())
            await audit(conn, uid, uname, nama, cmd, value_desc, "antre_penuh")
            return
        except (urllib.error.URLError, TimeoutError) as e:
            await tunggu.edit(f"⚠️ Gagal menghubungi server: `{e}`", buttons=kb_kembali())
            return
        finally:
            busy.discard(uid)
            batal_ev.pop(uid, None)

        if hasil.get("state") == "cancelled":
            await audit(conn, uid, uname, nama, cmd, value_desc, "batal")
            await tunggu.edit(format_hasil(hasil, judul), buttons=kb_kembali())
            return

        await audit(conn, uid, uname, nama, cmd, value_desc, hasil.get("status", "?"))

        # Link Google Maps (khusus /track): pakai yang ada / bangun dari koordinat.
        murl_maps = None
        if key == "track":
            f = hasil.get("fields")
            recs = f if isinstance(f, list) else ([f] if isinstance(f, dict) else [])
            for r in recs:
                murl_maps = murl_maps or maps_link(r)

        teks = format_hasil(hasil, judul)
        media = hasil.get("media") or []
        tombol = kb_hasil(murl_maps) if not media else None

        # Hasil panjang (KK banyak anggota) melebihi batas 1 pesan Telegram:
        # dipecah jadi beberapa pesan teks, tombol menempel di pesan terakhir.
        bagian = potong_pesan(teks)
        await tunggu.edit(bagian[0],
                          buttons=tombol if len(bagian) == 1 else None,
                          link_preview=False)
        for i, sisa in enumerate(bagian[1:]):
            akhir = i == len(bagian) - 2
            await client.send_message(uid, sisa, link_preview=False,
                                      buttons=tombol if akhir else None)

        for i, murl in enumerate(media[:10]):
            try:
                blob = await asyncio.to_thread(_fetch_media, murl)
                if blob:
                    await client.send_file(uid, blob, force_document=False,
                                           buttons=kb_kembali() if i == len(media[:10]) - 1 else None)
            except Exception as e:  # noqa: BLE001
                log.warning("gagal kirim media: %s", e)

    # Command tak dikenal (/foo) tidak boleh senyap — dulu /help diabaikan
    # tanpa balasan sehingga terlihat seperti "bot mati". Command yang sah
    # sudah ditangani handler di atas; sisa "/..." dijawab dengan petunjuk.
    @client.on(events.NewMessage(
        pattern=r"^/(?!start$|menu$|help$|whoami$|allow\s|users$|deny\s|stats$)\S+"))
    async def _cmd_asing(ev):
        if not await boleh(ev.sender_id):
            return
        await ev.respond("Perintah tidak dikenal. Ketik /menu untuk membuka "
                         "daftar fitur 📲", buttons=kb_menu())

    @client.on(events.NewMessage)
    async def _msg(ev):
        if ev.raw_text.startswith("/"):
            return
        uid = ev.sender_id
        u = await boleh(uid)
        if not u:
            return
        # Admin sedang menamb/hapus user lewat panel: tangkap ID di sini.
        if u["role"] == "admin" and uid in admin_aksi:
            aksi = admin_aksi.pop(uid)
            t = ev.raw_text.strip()
            if not t.isdigit():
                await ev.respond("⚠️ ID harus angka. Ulangi lewat /admin.")
                return
            target = int(t)
            if aksi == "add":
                await add_user(conn, target, uid)
                await ev.respond(f"✅ User `{target}` ditambahkan.", buttons=kb_admin())
                try:
                    await client.send_message(target, "✅ Akses Anda disetujui admin. "
                                              "Ketik /start untuk mulai.")
                except Exception:  # noqa: BLE001
                    pass
            else:
                ok = await del_user(conn, target)
                await ev.respond(f"🗑️ User `{target}` dihapus." if ok
                                 else f"⚠️ `{target}` tidak ada / admin (tak bisa dihapus).",
                                 buttons=kb_admin())
            return
        key = pending.get(uid)
        if not key:
            # Tidak sedang memilih fitur: coba deteksi nilai yang diketik langsung.
            if ev.photo:
                return
            teks = ev.raw_text.strip()
            hp = _bersih_hp(teks)
            if HP_RE.match(hp):
                tebak[uid] = teks
                await ev.respond(
                    f"📲 Nomor HP `{teks}` terdeteksi. Mau cari apa?",
                    buttons=[[Button.inline("📱 NIK dari Nomor HP", data="go:nikbyphone")],
                             [Button.inline("🛰️ Lacak Nomor HP", data="go:track")],
                             [Button.inline("🏠 Menu", data="home")]])
                return
            if D16_RE.match(teks):
                tebak[uid] = teks
                await ev.respond(
                    f"🔢 16 digit `{teks}` terdeteksi. Ini NIK atau No. KK?",
                    buttons=[[Button.inline("🆔 Data NIK", data="go:nik")],
                             [Button.inline("👨‍👩‍👧 Kartu Keluarga", data="go:kk")],
                             [Button.inline("🏠 Menu", data="home")]])
                return
            await ev.respond("Ketik /menu untuk membuka daftar fitur 📲",
                             buttons=kb_menu())
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
            tolak = await cek_kuota(uid)
            if tolak:
                pending.pop(uid, None)
                await ev.respond(tolak, buttons=kb_kembali())
                return
            pending.pop(uid, None)
            blob = await ev.download_media(file=bytes)
            await proses(ev, key, "foto", lambda: _post_file(cmd, blob, siapa))
        else:
            if ev.photo:
                await ev.respond("Fitur ini butuh teks, bukan foto.")
                return
            value = ev.raw_text.strip()
            salah = validasi(key, value)
            if salah:
                await ev.respond(salah)      # tetap menunggu input yang benar
                await audit(conn, uid, uname, nama, cmd, value, "ditolak_format")
                return
            tolak = await cek_kuota(uid)
            if tolak:
                pending.pop(uid, None)
                await ev.respond(tolak, buttons=kb_kembali())
                return
            pending.pop(uid, None)
            await proses(ev, key, value, lambda: _post_json(cmd, value, siapa))

    log.info("siap menerima pesan")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
