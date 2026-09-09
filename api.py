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

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

import appauth
import config
import db
import jobs
import routes
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
    conn = await db.connect()
    worker_conn = await db.connect()

    stop = asyncio.Event()
    task = asyncio.create_task(jobs.run_worker(tg, worker_conn, stop_event=stop))

    state.update(tg=tg, conn=conn, stop=stop, task=task)
    log.info("API siap, worker antrian jalan")
    try:
        yield
    finally:
        stop.set()
        task.cancel()
        await conn.close()
        await worker_conn.close()
        await tg.stop()


app = FastAPI(title="Artemis Telegram Connector", version="1.0", lifespan=lifespan)


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
        fields=job.get("fields"),
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


@app.post("/auth/login", dependencies=[Depends(auth)])
async def auth_login(req: LoginReq):
    """Verifikasi login aplikasi ke tabel app_users. Dipanggil server-to-server
    (mis. backend ArtemisID) dengan X-API-Key."""
    u = await appauth.verify_login(state["conn"], req.username, req.password)
    if not u:
        raise HTTPException(status_code=401, detail="username atau kata sandi salah")
    return {"ok": True, **u}


@app.get("/auth/users", dependencies=[Depends(auth)])
async def auth_users():
    return {"ok": True, "users": await appauth.list_users(state["conn"])}


@app.post("/auth/users", dependencies=[Depends(auth)])
async def auth_create(req: AppUserReq):
    await appauth.create_user(state["conn"], req.username, req.password, req.role)
    return {"ok": True}


@app.post("/auth/users/{username}/password", dependencies=[Depends(auth)])
async def auth_set_password(username: str, req: PasswordReq):
    ok = await appauth.set_password(state["conn"], username, req.password)
    if not ok:
        raise HTTPException(status_code=404, detail="user tidak ditemukan")
    return {"ok": True}


@app.post("/auth/users/{username}/role", dependencies=[Depends(auth)])
async def auth_set_role(username: str, role: str = Query(..., pattern="^(admin|user)$")):
    ok = await appauth.set_role(state["conn"], username, role)
    if not ok:
        raise HTTPException(status_code=404, detail="user tidak ditemukan")
    return {"ok": True}


@app.delete("/auth/users/{username}", dependencies=[Depends(auth)])
async def auth_delete(username: str):
    ok = await appauth.delete_user(state["conn"], username)
    if not ok:
        raise HTTPException(status_code=404, detail="user tidak ditemukan")
    return {"ok": True}


class SessionUpsertReq(BaseModel):
    id: str
    user: str
    data: dict


@app.post("/app/sessions/upsert", dependencies=[Depends(auth)])
async def app_session_upsert(req: SessionUpsertReq):
    await db.app_session_upsert(state["conn"], req.id, req.user, req.data)
    return {"ok": True}


@app.get("/app/sessions", dependencies=[Depends(auth)])
async def app_session_list(user: str = Query(...)):
    return {"ok": True, "items": await db.app_session_list(state["conn"], user)}


@app.get("/app/cached", dependencies=[Depends(auth)])
async def app_cached(bot: str = Query(...), cmd: str = Query(...), value: str = Query(...)):
    """Baris cache terbaru (status 'found') untuk (bot, cmd, value).

    DB-ONLY — TIDAK menyentuh Telegram. Dipakai Artemis untuk recheck:
    ambil hasil temuan yang sudah pernah tersimpan di bot_query_cache.
    """
    row = await db.cached_row(state["conn"], bot, cmd, value)
    if not row:
        return {"ok": True, "found": False}
    media = [f"/media/{i}" for i in (row.get("media") or [])]
    return {
        "ok": True,
        "found": True,
        "status": row["status"],
        "msg": row.get("msg"),
        "fields": row.get("fields"),
        "media": media,
    }


@app.get("/app/sessions/{sid}", dependencies=[Depends(auth)])
async def app_session_get(sid: str, user: str = Query(...)):
    data = await db.app_session_get(state["conn"], sid, user)
    if data is None:
        raise HTTPException(status_code=404, detail="sesi tidak ditemukan")
    return {"ok": True, "session": data}


@app.delete("/app/sessions", dependencies=[Depends(auth)])
async def app_session_clear(user: str = Query(...)):
    """Hapus semua sesi milik user (kosongkan riwayat)."""
    n = await db.app_session_clear(state["conn"], user)
    return {"ok": True, "deleted": n}


@app.get("/media/{media_id}", dependencies=[Depends(auth)])
async def media(media_id: str):
    """Sajikan gambar (foto E-KTP dll) berdasarkan id."""
    row = await db.get_media(state["conn"], media_id)
    if row is None:
        raise HTTPException(status_code=404, detail="media tidak ditemukan")
    return Response(content=bytes(row["bytes"]), media_type=row["content_type"],
                    headers={"Cache-Control": "private, max-age=86400"})


@app.get("/health")
async def health():
    stats = await jobs.queue_stats(state["conn"])
    return {"ok": True, "antrian": stats}


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
    conn = state["conn"]

    if (err := jobs.validate(bot, req.cmd)):
        raise HTTPException(status_code=400, detail=err)

    if not req.force:
        cached = await db.lookup(conn, bot, req.cmd, req.value)
        if cached:
            media = [f"/media/{i}" for i in (cached.get("media") or [])]
            return JobResponse(
                job_id="", state="done", status=cached["status"],
                from_cache=True, msg=cached["msg"], fields=cached["fields"],
                media=media,
            )

    job = await jobs.enqueue(conn, bot, req.cmd, req.value,
                             requested_by=req.requested_by, priority=req.priority,
                             force=req.force)
    posisi = await jobs.queue_position(conn, str(job["job_id"]))
    return _to_response(job, posisi)


@app.get("/jobs/{job_id}", response_model=JobResponse, dependencies=[Depends(auth)])
async def get_search(job_id: str,
                     wait: float = Query(0, ge=0, le=300,
                                         description="detik menunggu sampai selesai (long-poll)")):
    """Ambil status/hasil job. `wait` > 0 untuk menunggu sampai selesai."""
    conn = state["conn"]
    batas = asyncio.get_event_loop().time() + wait

    while True:
        job = await jobs.get_job(conn, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job tidak ditemukan")
        if job["state"] in ("done", "failed") or asyncio.get_event_loop().time() >= batas:
            posisi = await jobs.queue_position(conn, job_id) if job["state"] == "queued" else None
            return _to_response(job, posisi)
        await asyncio.sleep(1)


@app.get("/queue", dependencies=[Depends(auth)])
async def queue_list(limit: int = Query(20, ge=1, le=200)):
    """Isi antrian saat ini + job yang sedang diproses."""
    conn = state["conn"]
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
    conn = state["conn"]
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

    conn = state["conn"]
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
    return await _detail_profil(state["conn"], "id = %s", (profile_id,))


@app.get("/profiles/{nik}", dependencies=[Depends(auth)])
async def get_profile(nik: str):
    """Ambil profil langsung dari database (tanpa menyentuh Telegram)."""
    return await _detail_profil(state["conn"], "nik = %s", (nik,))


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
