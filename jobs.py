"""Antrian job pencarian + worker yang memprosesnya satu per satu.

Kenapa harus antrian serial: satu akun Telegram cuma bisa melayani satu
percakapan efektif pada satu waktu. Waktu diuji dengan mengirim command
beruntun, antrian di sisi bot menumpuk sampai "urutan ke-9", balasan datang
tidak berurutan, dan sempat terjadi hasil satu command tertukar dengan
command lain. Jadi worker di sini sengaja cuma SATU dan memproses berurutan.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from psycopg.types.json import Jsonb

import db
import routes
import service

log = logging.getLogger("artemis.jobs")

# Jeda antar hit ke Telegram (detik). Jangan terlalu kecil: rate limit bot
# muncul sebagai "Please wait N second(s)".
JEDA_ANTAR_JOB = 10


# --------------------------------------------------------------- enqueue

async def enqueue(conn, bot: str, cmd: str, value: str, *,
                  requested_by: str | None = None, priority: int = 0,
                  force: bool = False) -> dict:
    """Masukkan job ke antrian. Kembalikan barisnya.

    force=True memaksa worker menembak Telegram walau nilainya ada di cache
    (dipakai healthcheck).
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            INSERT INTO search_jobs (bot, cmd, value, requested_by, priority, force)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING *
            """,
            (bot, cmd, value, requested_by, priority, force),
        )
        return await cur.fetchone()


async def get_job(conn, job_id: str) -> dict | None:
    # job_id kolomnya UUID; string non-UUID akan menggagalkan query, jadi
    # divalidasi dulu supaya balasannya "tidak ada" (404), bukan error 500.
    try:
        uuid.UUID(str(job_id))
    except (ValueError, TypeError):
        return None
    async with conn.cursor() as cur:
        await cur.execute("SELECT * FROM search_jobs WHERE job_id = %s", (job_id,))
        return await cur.fetchone()


async def queue_position(conn, job_id: str) -> int | None:
    """Nomor antrian job (1 = berikutnya diproses). None kalau sudah jalan."""
    async with conn.cursor() as cur:
        await cur.execute(
            """
            SELECT count(*) + 1 AS posisi
              FROM search_jobs q
             WHERE q.state = 'queued'
               AND (q.priority, -q.id) > (
                     SELECT j.priority, -j.id FROM search_jobs j WHERE j.job_id = %s
                   )
            """,
            (job_id,),
        )
        row = await cur.fetchone()
    return row["posisi"] if row else None


async def queue_stats(conn) -> dict:
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT state, count(*) AS n FROM search_jobs GROUP BY state"
        )
        rows = await cur.fetchall()
    return {r["state"]: r["n"] for r in rows}


# ---------------------------------------------------------------- worker

async def _claim_next(conn) -> dict | None:
    """Ambil satu job berikutnya secara aman kalau ada >1 worker.

    SKIP LOCKED memastikan dua worker tidak mengambil job yang sama.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE search_jobs
               SET state = 'running', started_at = now(), attempts = attempts + 1
             WHERE id = (
                   SELECT id FROM search_jobs
                    WHERE state = 'queued'
                    ORDER BY priority DESC, id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
             )
            RETURNING *
            """
        )
        return await cur.fetchone()


async def _finish(conn, job_id: str, hasil: dict) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE search_jobs
               SET state = 'done', status = %s, msg = %s, fields = %s,
                   media = %s, from_cache = %s, finished_at = now()
             WHERE job_id = %s
            """,
            (hasil["status"], hasil.get("msg"),
             Jsonb(hasil["fields"]) if hasil.get("fields") is not None else None,
             Jsonb(hasil.get("media")) if hasil.get("media") else None,
             hasil.get("from_cache", False), job_id),
        )


async def _fail(conn, job_id: str, error: str) -> None:
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE search_jobs
               SET state = 'failed', error = %s, finished_at = now()
             WHERE job_id = %s
            """,
            (error, job_id),
        )


async def run_worker(tg, conn, *, poll_interval: float = 2.0,
                     stop_event: asyncio.Event | None = None) -> None:
    """Loop worker: ambil job -> proses -> simpan hasil. Serial, satu-satu."""
    log.info("worker antrian jalan")
    while not (stop_event and stop_event.is_set()):
        job = await _claim_next(conn)
        if job is None:
            await asyncio.sleep(poll_interval)
            continue

        jid = str(job["job_id"])
        log.info("proses job %s: %s %s %s", jid, job["bot"], job["cmd"], job["value"])
        try:
            hasil = await service.query(tg, conn, job["bot"], job["cmd"], job["value"],
                                        force=job.get("force", False))
            await _finish(conn, jid, hasil)
            log.info("job %s selesai: %s (cache=%s)", jid, hasil["status"], hasil["from_cache"])

            # Cache hit tidak menyentuh Telegram, jadi tidak perlu jeda.
            if not hasil["from_cache"]:
                await asyncio.sleep(JEDA_ANTAR_JOB)
        except Exception as exc:                       # noqa: BLE001
            log.exception("job %s gagal", jid)
            await _fail(conn, jid, repr(exc))


# ------------------------------------------------------------- validasi

def validate(bot: str, cmd: str) -> str | None:
    """Kembalikan pesan error kalau kombinasi bot+command tidak dikenal."""
    if routes.get_route(bot, cmd) is None:
        return f"command '{cmd}' tidak tersedia untuk {bot}"
    return None
