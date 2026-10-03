"""Jembatan HTTP untuk aplikasi Artemis.

Jalankan:
    uvicorn api:app --host 127.0.0.1 --port 8000

Alur dari sisi Artemis:

    POST /search  {"bot":"bot1","cmd":"/nik","value":"327..."}
      -> kalau sudah ada di cache : langsung dapat hasilnya (state "done")
      -> kalau belum              : dapat job_id + posisi antrian
    GET  /search/{job_id}         -> pantau sampai state "done"

Worker antrian ikut hidup bersama API ini (satu proses), memakai satu sesi
Telegram dan memproses job berurutan.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import logging
import os
from contextlib import asynccontextmanager

import psycopg

from fastapi import Depends, FastAPI, Header, HTTPException, Query, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

import appauth
import config
import db
import jobs
import normalize as N
import routes

# Batas ukuran foto yang diterima untuk pencarian berbasis gambar.
MAKS_BERKAS = 8 * 1024 * 1024

# Tanda pengenal berkas gambar, dibaca dari ISI berkas.
#
# Content-type dari klien tidak bisa dipercaya: multipart.CreateFormFile di Go
# memberi "application/octet-stream" secara bawaan, sehingga unggahan foto dari
# ArtemisID ditolak "hanya menerima gambar" padahal isinya JPEG yang sah.
_TANDA_GAMBAR = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def _tipe_gambar(data: bytes, ctype: str | None) -> str | None:
    """Kembalikan content-type gambar, atau None kalau bukan gambar."""
    for tanda, tipe in _TANDA_GAMBAR:
        if data.startswith(tanda):
            return tipe
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    # Isi tidak dikenali: baru percaya pada content-type yang menyebut gambar.
    if ctype and ctype.startswith("image/"):
        return ctype
    return None
from connector import TelegramConnector

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("artemis.api")

API_KEY = os.getenv("API_KEY")          # kosongkan untuk mematikan autentikasi
state: dict = {}


# ------------------------------------------------------------- lifecycle

@asynccontextmanager
async def lifespan(app: FastAPI):
    tg = TelegramConnector()
    await tg.start()
    try:
        conn = await db.connect()
        worker_conn = await db.connect()
    except Exception as exc:
        log.error("GAGAL konek database db_artemis — cek Postgres (pg_isready). Sebab: %s", exc)
        await tg.stop()
        raise

    # DDL user_logs dijalankan SEKALI di sini, bukan di tiap tulis log. Gagal
    # di sini tidak boleh menggagalkan start: flag di db.py tetap belum diset,
    # jadi log_insert berikutnya mencoba lagi sendiri.
    try:
        await db.ensure_user_logs(conn)
    except Exception as exc:
        log.warning("ensure_user_logs saat start gagal (dicoba lagi saat log pertama): %s", exc)

    stop = asyncio.Event()
    task = asyncio.create_task(jobs.run_worker(tg, worker_conn, stop_event=stop))

    state.update(tg=tg, conn=conn, stop=stop, task=task)
    log.info("API siap, worker antrian jalan")
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        # state["conn"] bisa sudah diganti _conn() (reconnect), dan conn lama
        # mungkin sudah ditutup _jebakan_error. Tutup keduanya dengan diam:
        # menutup koneksi yang sudah tertutup/putus jangan sampai menggagalkan
        # shutdown sebelum tg.stop() sempat jalan.
        sekarang = state.get("conn")
        await _tutup_diam(sekarang)
        if conn is not sekarang:
            await _tutup_diam(conn)
        await _tutup_diam(worker_conn)
        await tg.stop()


# ------------------------------------------------- koneksi DB yang pulih sendiri

# Satu koneksi dipakai bersama semua endpoint. Dulu koneksi ini dibuka sekali
# seumur proses: begitu Postgres restart/jaringan berkedip, koneksinya putus
# dan SEMUA endpoint (termasuk POST /auth/login yang dipakai login ArtemisID →
# "Sumber verifikasi (connector) tidak merespons") gagal terus sampai server
# di-restart manual. _conn() memeriksa koneksi tiap kali dipakai dan menyambung
# ulang kalau sudah tertutup/putus.
#
# Lock mencegah banyak request yang datang bersamaan saat DB baru pulih
# masing-masing membuka koneksi baru (yang lalu saling menimpa dan bocor).
_conn_lock = asyncio.Lock()


def _conn_rusak(c) -> bool:
    """True kalau koneksi tidak bisa dipakai lagi (None/tertutup/putus).

    getattr dengan default supaya objek tiruan di test (tanpa atribut
    closed/broken) dianggap sehat.
    """
    return c is None or bool(getattr(c, "closed", False)) or bool(getattr(c, "broken", False))


async def _tutup_diam(c) -> None:
    """Tutup koneksi tanpa melempar error — koneksi putus sering gagal ditutup."""
    if c is None:
        return
    try:
        await c.close()
    except Exception as exc:  # sudah tertutup/putus: tidak ada yang perlu dilakukan
        log.debug("menutup koneksi DB lama gagal (diabaikan): %s", exc)


async def _conn():
    """Koneksi DB untuk endpoint; sambung ulang kalau yang lama rusak."""
    c = state.get("conn")
    if not _conn_rusak(c):
        return c  # jalur cepat: tanpa lock, ini yang terjadi hampir selalu
    async with _conn_lock:
        # Periksa lagi: request lain mungkin sudah menyambung ulang selagi
        # kita menunggu lock.
        c = state.get("conn")
        if not _conn_rusak(c):
            return c
        log.warning("koneksi DB API tertutup/putus — menyambung ulang ke db_artemis")
        await _tutup_diam(c)
        # Kalau connect gagal (DB masih mati), exception naik ke _jebakan_error
        # → 503; request berikutnya akan mencoba lagi dari sini.
        baru = await db.connect()
        state["conn"] = baru
        log.warning("koneksi DB API tersambung kembali")
        return baru


app = FastAPI(title="Artemis Telegram Connector", version="1.0", lifespan=lifespan)


@app.exception_handler(Exception)
async def _jebakan_error(request: Request, exc: Exception):
    """Jangan biarkan error jadi "Internal Server Error" polos tanpa jejak.

    Sebelum ini, kalau Postgres mati, SEMUA endpoint yang menyentuh DB menjawab
    500 dengan body teks 21 byte ("Internal Server Error") dan log kosong —
    mustahil dibedakan dari bug lain. Kini: traceback lengkap dicatat dan klien
    menerima JSON yang menyebut jenis errornya.
    """
    if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
        # DB putus/tidak terjangkau. Tutup koneksi bersama supaya _conn() di
        # request berikutnya menyambung ulang (psycopg tidak selalu menandai
        # `broken` untuk setiap kegagalan jaringan). 503, bukan 500: ini
        # gangguan sementara di hulu, dan ArtemisID memperlakukan selain
        # 401/403 sebagai "sumber tidak merespons" — memang itu yang terjadi.
        log.warning("database bermasalah di %s %s: %s: %s", request.method,
                    request.url.path, type(exc).__name__, exc)
        await _tutup_diam(state.get("conn"))
        return JSONResponse(
            status_code=503,
            content={"ok": False, "detail": "database sementara tidak tersedia"},
        )
    log.exception("error tak tertangani di %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"ok": False, "detail": "internal error: " + type(exc).__name__},
    )


def auth(x_api_key: str | None = Header(default=None)) -> None:
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key tidak valid")


# --------------------------------------------------------------- schemas

class SearchRequest(BaseModel):
    # `bot` ditentukan lewat path /search/{bot}, bukan body. Nama command bisa
    # sama di lebih dari satu bot, jadi command saja tidak cukup untuk
    # menentukan tujuan. Daftar command per bot ada di GET /commands.
    cmd: str = Field(..., examples=["/nik"])
    value: str = Field(..., min_length=1, examples=["3201010101010001"])
    requested_by: str | None = Field(None, description="identitas user/modul di Artemis")
    priority: int = Field(0, description="makin besar makin didahulukan")
    force: bool = Field(False, description="paksa hit Telegram walau ada di cache (dipakai healthcheck)")


class JobResponse(BaseModel):
    job_id: str
    state: str                      # queued | running | done | failed
    status: str | None = None       # found | not_found | queue_without_data | no_response
    queue_position: int | None = None
    from_cache: bool = False
    msg: str | None = None
    # Nama field diseragamkan lewat normalize.rapikan_nama_field() sebelum
    # dikirim, supaya cocok dengan `atribut` di GET /commands dan
    # docs/skema.json. Nilainya tidak diubah.
    fields: object | None = None
    media: list[str] = []
    error: str | None = None


def _to_response(job: dict, posisi: int | None = None) -> JobResponse:
    return JobResponse(
        job_id=str(job["job_id"]),
        state=job["state"],
        status=job.get("status"),
        queue_position=posisi if job["state"] == "queued" else None,
        from_cache=job.get("from_cache", False),
        msg=job.get("msg"),
        fields=N.rapikan_nama_field(job.get("fields")),
        media=job.get("media") or [],
        error=job.get("error"),
    )


# -------------------------------------------------------------- endpoints

@app.get("/monitor", include_in_schema=False)
async def monitor():
    """Halaman pemantauan command (HTML statis, ambil datanya lewat API)."""
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "monitor.html"))


class LoginReq(BaseModel):
    username: str
    password: str


class AppUserReq(BaseModel):
    username: str
    password: str
    role: str = Field("user", pattern="^(admin|user)$")


class PasswordReq(BaseModel):
    password: str


class UserLogReq(BaseModel):
    username: str
    event: str
    detail: dict | None = None


@app.post("/auth/login", dependencies=[Depends(auth)])
async def auth_login(req: LoginReq):
    """Verifikasi login aplikasi ke tabel app_users. Dipanggil server-to-server
    (mis. backend ArtemisID) dengan X-API-Key."""
    u = await appauth.verify_login(await _conn(), req.username, req.password)
    if not u:
        raise HTTPException(status_code=401, detail="username atau kata sandi salah")
    return {"ok": True, **u}


@app.get("/auth/users", dependencies=[Depends(auth)])
async def auth_users():
    return {"ok": True, "users": await appauth.list_users(await _conn())}


@app.post("/auth/users", dependencies=[Depends(auth)])
async def auth_create(req: AppUserReq):
    await appauth.create_user(await _conn(), req.username, req.password, req.role)
    return {"ok": True}


@app.post("/auth/users/{username}/password", dependencies=[Depends(auth)])
async def auth_set_password(username: str, req: PasswordReq):
    ok = await appauth.set_password(await _conn(), username, req.password)
    if not ok:
        raise HTTPException(status_code=404, detail="user tidak ditemukan")
    return {"ok": True}


@app.post("/auth/users/{username}/role", dependencies=[Depends(auth)])
async def auth_set_role(username: str, role: str = Query(..., pattern="^(admin|user)$")):
    ok = await appauth.set_role(await _conn(), username, role)
    if not ok:
        raise HTTPException(status_code=404, detail="user tidak ditemukan")
    return {"ok": True}


@app.delete("/auth/users/{username}", dependencies=[Depends(auth)])
async def auth_delete(username: str):
    ok = await appauth.delete_user(await _conn(), username)
    if not ok:
        raise HTTPException(status_code=404, detail="user tidak ditemukan")
    return {"ok": True}


class SessionUpsertReq(BaseModel):
    id: str
    user: str
    data: dict


@app.post("/app/sessions/upsert", dependencies=[Depends(auth)])
async def app_session_upsert(req: SessionUpsertReq):
    await db.app_session_upsert(await _conn(), req.id, req.user, req.data)
    return {"ok": True}


@app.get("/app/sessions", dependencies=[Depends(auth)])
async def app_session_list(user: str = Query(...)):
    return {"ok": True, "items": await db.app_session_list(await _conn(), user)}


@app.post("/app/logs", dependencies=[Depends(auth)])
async def app_logs_create(req: UserLogReq):
    """Catat satu aktivitas user (login/logout/search/export dsb)."""
    row = await db.log_insert(await _conn(), req.username.strip(), req.event, req.detail)
    return {"ok": True, "id": row}


@app.get("/app/logs", dependencies=[Depends(auth)])
async def app_logs_list(username: str | None = Query(None),
                        limit: int = Query(200, ge=1, le=1000)):
    """Log aktivitas. `username` opsional: kalau diisi filter satu user;
    tanpa username = SEMUA user (dipakai menu Log admin)."""
    items = await db.log_list(await _conn(), username=username, limit=limit)
    return {"ok": True, "items": items}


@app.get("/app/cached", dependencies=[Depends(auth)])
async def app_cached(bot: str = Query(...), cmd: str = Query(...), value: str = Query(...)):
    """Baris cache terbaru untuk (bot, cmd, value) — DB-ONLY, tanpa Telegram.

    `found: true` hanya kalau status 'found' (hasil temuan). Untuk DEBUG,
    status lain (not_found/no_response) ikut dikembalikan + raw_text balasan
    mentah supaya kita bisa lihat apa yang bot balas tanpa hit ulang.
    """
    row = await db.cached_row(await _conn(), bot, cmd, value)
    if not row:
        return {"ok": True, "found": False}
    found = row["status"] == "found"
    media = [f"/media/{i}" for i in (row.get("media") or [])]
    return {
        "ok": True,
        "found": found,
        "status": row["status"],
        "msg": row.get("msg"),
        "fields": N.rapikan_nama_field(row.get("fields")),
        "media": media,
        "raw_text": row.get("raw_text"),
        "tested_at": str(row["tested_at"]),
    }


@app.get("/app/sessions/{sid}", dependencies=[Depends(auth)])
async def app_session_get(sid: str, user: str = Query(...)):
    data = await db.app_session_get(await _conn(), sid, user)
    if data is None:
        raise HTTPException(status_code=404, detail="sesi tidak ditemukan")
    return {"ok": True, "session": data}


@app.delete("/app/sessions", dependencies=[Depends(auth)])
async def app_session_clear(user: str = Query(...)):
    """Hapus semua sesi milik user (kosongkan riwayat)."""
    n = await db.app_session_clear(await _conn(), user)
    return {"ok": True, "deleted": n}


@app.get("/media/{media_id}", dependencies=[Depends(auth)])
async def media(media_id: str):
    """Sajikan gambar (foto E-KTP dll) berdasarkan id."""
    row = await db.get_media(await _conn(), media_id)
    if row is None:
        raise HTTPException(status_code=404, detail="media tidak ditemukan")
    return Response(content=bytes(row["bytes"]), media_type=row["content_type"],
                    headers={"Cache-Control": "private, max-age=86400"})


@app.get("/health")
async def health():
    """Status jujur: selalu 200, tapi `ok` menyatakan apakah layanan benar sehat.

    Sebelumnya endpoint ini 500 saat DB mati, sehingga tidak bisa dibedakan dari
    "aplikasi ikut mati". Sekarang laporan hidup/matinya database tetap terbaca
    di body (dipakai ArtemisID `/api/health` → `connector.ok`).

    Dulu `ok` hanya mencerminkan DB: worker antrian yang sudah mati (task asyncio
    selesai karena exception) atau job yang macet 'running' 20 menit tetap
    dilaporkan sehat. Karena itu kini ikut dilaporkan:
      - worker_task      : 'running' | 'dead: <ExcType>' | 'stopped'
      - worker           : jobs.worker_status() (detak, job berjalan, error)
      - running_oldest_s : umur job 'running' tertua (deteksi macet)
      - queued           : jumlah job mengantre
    `ok` = DB terjangkau DAN task worker tidak mati. Nilai pencarian (`value`,
    data pribadi) TIDAK pernah ikut — endpoint ini tanpa API key.
    """
    db_status = "ok"
    stats = None
    queued = None
    running_oldest_s = None
    conn = None
    try:
        conn = await _conn()
        stats = await jobs.queue_stats(conn)
        queued = int((stats or {}).get("queued", 0))
    except Exception as exc:  # psycopg.OperationalError dsb: DB mati/putus
        db_status = "error: " + type(exc).__name__
        log.warning("health: database tidak terjangkau: %s", exc)
        if isinstance(exc, (psycopg.OperationalError, psycopg.InterfaceError)):
            await _tutup_diam(state.get("conn"))  # paksa reconnect berikutnya
    if db_status == "ok":
        # Terpisah dari probe DB di atas: kalau kueri tambahan ini gagal, DB
        # tetap dianggap terjangkau (queue_stats sudah berhasil) — field ini
        # saja yang kosong.
        try:
            running_oldest_s = await _umur_running_tertua(conn)
        except Exception as exc:
            log.warning("health: gagal membaca umur job running: %s", exc)

    worker_task = _status_task_worker(state.get("task"))
    return {
        "ok": db_status == "ok" and not worker_task.startswith("dead"),
        "db": db_status,
        "antrian": stats,
        "worker": _status_worker(),
        "worker_task": worker_task,
        "running_oldest_s": running_oldest_s,
        "queued": queued,
    }


async def _umur_running_tertua(conn) -> float | None:
    """Detik sejak job 'running' tertua mulai; None kalau tidak ada.

    Dihitung di Postgres (now() - started_at) supaya memakai jam yang sama
    dengan yang menulis started_at.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT EXTRACT(EPOCH FROM now() - min(COALESCE(started_at, created_at))) AS umur "
            "  FROM search_jobs WHERE state = 'running'"
        )
        row = await cur.fetchone()
    umur = row["umur"] if row else None
    return None if umur is None else round(float(umur), 1)


def _status_task_worker(task) -> str:
    """'running' | 'dead: <ExcType>' | 'stopped' dari asyncio.Task worker."""
    if task is None:
        return "stopped"
    if not task.done():
        return "running"
    if task.cancelled():
        return "stopped"
    exc = task.exception()
    return f"dead: {type(exc).__name__}" if exc is not None else "stopped"


def _status_worker() -> dict | None:
    """jobs.worker_status() kalau tersedia, tanpa data pribadi.

    worker_status dibuat terpisah di jobs.py; hasattr supaya /health tetap
    jalan di versi jobs.py yang belum memilikinya. `value` dibuang dengan
    sengaja walau bentuk resminya memang tanpa itu — /health terbuka tanpa
    API key, jadi jangan sampai NIK/nomor yang sedang dicari bocor ke sini.
    """
    if not hasattr(jobs, "worker_status"):
        return None
    try:
        ws = jobs.worker_status()
    except Exception as exc:
        log.warning("health: jobs.worker_status() gagal: %s", exc)
        return {"error": type(exc).__name__}
    if not isinstance(ws, dict):
        return None
    ws = dict(ws)
    ws.pop("value", None)
    job = ws.get("current_job")
    if isinstance(job, dict):
        ws["current_job"] = {k: v for k, v in job.items() if k != "value"}
    return ws


def _katalog_skema() -> dict:
    """Bentuk data per command dari docs/skema.json (dibuat oleh skema.py).

    Dibaca saat diminta, bukan di-cache, supaya `python skema.py --tulis`
    langsung terlihat tanpa perlu me-restart API. Filenya kecil.
    """
    berkas = pathlib.Path(__file__).parent / "docs" / "skema.json"
    try:
        return json.loads(berkas.read_text(encoding="utf8"))
    except (OSError, ValueError):
        return {}


@app.get("/commands", dependencies=[Depends(auth)])
async def list_commands():
    """Daftar command yang bisa dipanggil Artemis, dikelompokkan per bot.

    Menyertakan BENTUK DATA tiap command (`atribut`) supaya aplikasi tidak
    perlu menebak field apa yang akan diterima. `terverifikasi=false` berarti
    command itu belum pernah menghasilkan data, jadi daftar atributnya belum
    diketahui — bukan berarti kosong.
    """
    katalog = _katalog_skema()
    out: dict[str, list[dict]] = {}
    for (bot, cmd), route in sorted(routes.ROUTES.items()):
        skema = katalog.get(f"{bot}{cmd}", {})
        out.setdefault(bot, []).append({
            "cmd": cmd,
            "target": route.target,
            "kind": route.kind,
            "always_fresh": route.volatile,   # tidak pernah dijawab dari cache
            "menu": route.menu,               # None = dialek command biasa
            "atribut": skema.get("atribut", []),
            "terverifikasi": skema.get("terverifikasi", False),
        })
    return out


@app.post("/search/{bot}", response_model=JobResponse, dependencies=[Depends(auth)])
async def search(bot: str, req: SearchRequest):
    """Terima input pencarian dari Artemis untuk bot tertentu (lewat path).

    Contoh: POST /search/bot1  body {"cmd":"/nik","value":"..."}

    Kalau sudah ada di cache, hasilnya langsung dikembalikan (tanpa antrian).
    Kalau belum, job masuk antrian dan diproses worker satu per satu.
    """
    conn = await _conn()

    if (err := jobs.validate(bot, req.cmd)):
        raise HTTPException(status_code=400, detail=err)

    if not req.force:
        cached = await db.lookup(conn, bot, req.cmd, req.value)
        if cached:
            media = [f"/media/{i}" for i in (cached.get("media") or [])]
            return JobResponse(
                job_id="", state="done", status=cached["status"],
                from_cache=True, msg=cached["msg"],
                fields=N.rapikan_nama_field(cached["fields"]),
                media=media,
            )

    job = await jobs.enqueue(conn, bot, req.cmd, req.value,
                             requested_by=req.requested_by, priority=req.priority,
                             force=req.force)
    posisi = await jobs.queue_position(conn, str(job["job_id"]))
    return _to_response(job, posisi)


@app.post("/search/{bot}/file", response_model=JobResponse, dependencies=[Depends(auth)])
async def search_file(bot: str, cmd: str = Form(...), file: UploadFile = File(...),
                      requested_by: str | None = Form(None),
                      priority: int = Form(0)):
    """Pencarian yang masukannya BERKAS (foto), bukan teks.

    Dipakai FR SOCIAL MEDIA: bot meminta "kirim foto wajah yang ingin dicari".
    Fotonya disimpan lebih dulu di media_blobs (dedup lewat sha256), lalu
    id-nya dipakai sebagai `value` job — kolom search_jobs.value bertipe TEXT
    dan tidak bisa menampung gambar.
    """
    if (err := jobs.validate(bot, cmd)):
        raise HTTPException(status_code=400, detail=err)
    if not routes.butuh_berkas(bot, cmd):
        raise HTTPException(status_code=400,
                            detail=f"command '{cmd}' tidak menerima berkas")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="berkas kosong")
    if len(data) > MAKS_BERKAS:
        raise HTTPException(status_code=413,
                            detail=f"berkas melebihi {MAKS_BERKAS // (1024*1024)} MB")
    ctype = _tipe_gambar(data, file.content_type)
    if ctype is None:
        raise HTTPException(status_code=400, detail="hanya menerima gambar")

    conn = await _conn()
    mid = await db.store_media(conn, data, ctype, bot=bot, cmd=cmd, value="(unggahan)")
    job = await jobs.enqueue(conn, bot, cmd, mid, requested_by=requested_by,
                             priority=priority)
    posisi = await jobs.queue_position(conn, str(job["job_id"]))
    return _to_response(job, posisi)


@app.get("/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(auth)])
async def get_search(job_id: str,
                     wait: float = Query(0, ge=0, le=300,
                                         description="detik menunggu sampai selesai (long-poll)")):
    """Ambil status/hasil job. `wait` > 0 untuk menunggu sampai selesai."""
    batas = asyncio.get_event_loop().time() + wait

    while True:
        # Ambil koneksi tiap putaran: long-poll bisa berlangsung sampai 300 dtk,
        # dan koneksi yang tersambung ulang di tengahnya harus ikut terpakai.
        conn = await _conn()
        job = await jobs.get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job tidak ditemukan")
        if job["state"] in ("done", "failed") or asyncio.get_event_loop().time() >= batas:
            posisi = await jobs.queue_position(conn, job_id) if job["state"] == "queued" else None
            return _to_response(job, posisi)
        await asyncio.sleep(1)


@app.delete("/jobs/{job_id}", dependencies=[Depends(auth)])
async def cancel_search(job_id: str):
    """Batalkan job yang masih mengantre. Yang sudah jalan tidak bisa dibatalkan."""
    ok = await jobs.cancel(await _conn(), job_id)
    return {"ok": ok}


@app.get("/queue", dependencies=[Depends(auth)])
async def queue_list(limit: int = Query(20, ge=1, le=200)):
    """Isi antrian saat ini + job yang sedang diproses."""
    conn = await _conn()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT job_id, bot, cmd, value, state, priority, requested_by, created_at
              FROM search_jobs
             WHERE state IN ('queued', 'running')
             ORDER BY state DESC, priority DESC, id
             LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()
    return {"total": len(rows), "jobs": rows}


@app.get("/health/commands", dependencies=[Depends(auth)])
async def health_commands(hanya_bermasalah: bool = Query(False)):
    """Hasil pengecekan berkala terakhir (diisi oleh healthcheck.py)."""
    conn = await _conn()
    async with conn.cursor() as cur:
        if hanya_bermasalah:
            await cur.execute("SELECT * FROM command_bermasalah")
        else:
            # LEFT JOIN dari command_probes, bukan dari command_health, supaya
            # command yang belum pernah dicek tetap muncul (ok = NULL). Kalau
            # tidak, dashboard terlihat "semua aman" padahal baru sebagian
            # kecil yang benar-benar diperiksa.
            await cur.execute(
                """
                SELECT p.bot, p.cmd, p.probe_value, p.expect_status, p.enabled,
                       h.last_status, h.ok, h.last_checked_at, h.last_ok_at,
                       h.last_msg,
                       COALESCE(h.consecutive_failures, 0) AS consecutive_failures
                  FROM command_probes p
                  LEFT JOIN command_health h ON h.bot = p.bot AND h.cmd = p.cmd
                 ORDER BY (h.ok IS NULL), h.ok, h.consecutive_failures DESC,
                          p.bot, p.cmd
                """
            )
        rows = await cur.fetchall()

    return {
        "total": len(rows),
        "sehat": sum(1 for r in rows if r.get("ok") is True),
        "bermasalah": sum(1 for r in rows if r.get("ok") is False),
        "belum_dicek": sum(1 for r in rows if r.get("ok") is None),
        "commands": rows,
    }


@app.get("/profiles", dependencies=[Depends(auth)])
async def cari_profil(
    nama: str | None = Query(None, min_length=2, description="cocokkan sebagian nama"),
    limit: int = Query(20, ge=1, le=100),
):
    """Cari profil di database berdasarkan nama (tanpa menyentuh Telegram).

    Perlu karena `profiles.nik` boleh NULL: hasil pencarian by-nama sering
    tidak menyertakan NIK (lihat migrasi 012), sehingga profil seperti itu
    tidak bisa diambil lewat GET /profiles/{nik} sama sekali.

    Mengembalikan ringkasan saja; detail lengkap tetap lewat
    GET /profiles/{nik} untuk yang punya NIK, atau `id` di sini.
    """
    if not nama:
        raise HTTPException(status_code=400, detail="parameter `nama` wajib diisi")

    conn = await _conn()
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT id, nik, nama, tempat_lahir, tanggal_lahir, jenis_kelamin,
                   alamat, kel_desa, kecamatan, kab_kota, provinsi, updated_at
              FROM profiles
             WHERE nama ILIKE %s
             ORDER BY (nik IS NULL), nama
             LIMIT %s
            """,
            (f"%{nama}%", limit),
        )
        rows = await cur.fetchall()
    return {"total": len(rows), "profil": rows}


@app.get("/profiles/id/{profile_id}", dependencies=[Depends(auth)])
async def get_profile_by_id(profile_id: int):
    """Detail profil lewat id — satu-satunya cara untuk profil tanpa NIK."""
    return await _detail_profil(await _conn(), "id = %s", (profile_id,))


@app.get("/profiles/{nik}", dependencies=[Depends(auth)])
async def get_profile(nik: str):
    """Ambil profil langsung dari database (tanpa menyentuh Telegram)."""
    return await _detail_profil(await _conn(), "nik = %s", (nik,))


async def _detail_profil(conn, where: str, params: tuple) -> dict:
    """Profil + nomor HP + kendaraan + catatan, dipakai kedua endpoint detail."""
    async with conn.cursor() as cur:
        await cur.execute(f"SELECT * FROM profiles WHERE {where}", params)
        profil = await cur.fetchone()
        if profil is None:
            raise HTTPException(status_code=404, detail="profil belum ada di database")

        await cur.execute(
            "SELECT msisdn, operator, registered_at FROM profile_phones WHERE profile_id = %s",
            (profil["id"],),
        )
        telepon = await cur.fetchall()
        await cur.execute(
            "SELECT nopol, merk, tipe, tahun, warna FROM profile_vehicles WHERE profile_id = %s",
            (profil["id"],),
        )
        kendaraan = await cur.fetchall()
        await cur.execute(
            "SELECT kind, data, created_at FROM profile_records WHERE profile_id = %s",
            (profil["id"],),
        )
        catatan = await cur.fetchall()

    return {"profil": profil, "telepon": telepon,
            "kendaraan": kendaraan, "catatan": catatan}
