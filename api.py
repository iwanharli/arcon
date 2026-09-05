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
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

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
    # `bot` tidak lagi di body — dibedakan lewat path /search/{bot}. Ini perlu
    # karena 7 command (/nik, /kk, /reg, /nama, /nohp, /bpjs, /guru) ada di dua
    # bot sekaligus, jadi command saja tidak cukup untuk menentukan tujuan.
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
        error=job.get("error"),
    )


# -------------------------------------------------------------- endpoints

@app.get("/monitor", include_in_schema=False)
async def monitor():
    """Halaman pemantauan command (HTML statis, ambil datanya lewat API)."""
    return FileResponse(os.path.join(os.path.dirname(__file__), "static", "monitor.html"))


@app.get("/health")
async def health():
    stats = await jobs.queue_stats(state["conn"])
    return {"ok": True, "antrian": stats}


@app.get("/commands", dependencies=[Depends(auth)])
async def list_commands():
    """Daftar command yang bisa dipanggil Artemis, dikelompokkan per bot."""
    out: dict[str, list[dict]] = {}
    for (bot, cmd), route in sorted(routes.ROUTES.items()):
        out.setdefault(bot, []).append({
            "cmd": cmd,
            "target": route.target,
            "kind": route.kind,
            "always_fresh": route.volatile,   # tidak pernah dijawab dari cache
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
            return JobResponse(
                job_id="", state="done", status=cached["status"],
                from_cache=True, msg=cached["msg"], fields=cached["fields"],
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


@app.get("/profiles/{nik}", dependencies=[Depends(auth)])
async def get_profile(nik: str):
    """Ambil profil langsung dari database (tanpa menyentuh Telegram)."""
    conn = state["conn"]
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM profiles WHERE nik = %s", (nik,))
        profil = await cur.fetchone()
        if profil is None:
            raise HTTPException(status_code=404, detail="profil belum ada di database")

        await cur.execute(
            "SELECT msisdn, operator, registered_at FROM profile_phones WHERE profile_id = %s",
            (profil["id"],),
        )
        telepon = await cur.fetchall()
        await cur.execute(
            "SELECT kind, data, created_at FROM profile_records WHERE profile_id = %s",
            (profil["id"],),
        )
        catatan = await cur.fetchall()

    return {"profil": profil, "telepon": telepon, "catatan": catatan}
