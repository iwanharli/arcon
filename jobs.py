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
import os
import time
import uuid
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

import db
import routes
import service

log = logging.getLogger("artemis.jobs")

# Jeda antar hit ke Telegram (detik). Jangan terlalu kecil: rate limit bot
# muncul sebagai "Please wait N second(s)".
JEDA_ANTAR_JOB = 10


def _env_detik(nama: str, bawaan: float) -> float:
    """Baca batas waktu (detik) dari env; nilai rusak/<=0 jatuh ke bawaan.

    Salah ketik di .env tidak boleh membuat modul gagal di-import (API mati
    total) atau mematikan watchdog (batas 0 = semua job langsung timeout).
    """
    try:
        nilai = float(os.getenv(nama, ""))
    except ValueError:
        return bawaan
    return nilai if nilai > 0 else bawaan


# Batas waktu satu job (watchdog). service.query() bisa menunggu
# FINAL_TIMEOUT (300 dtk) dua kali ditambah jeda rate limit; tanpa batas, satu
# job yang macet menahan antrian SEMUA pengguna karena worker cuma satu.
JOB_TIMEOUT = _env_detik("JOB_TIMEOUT", 900)
# Job berkas (alur foto /fr) bisa mengklik sampai 10 kandidat @120 dtk, jadi
# butuh batas yang jauh lebih longgar supaya tidak terpotong padahal sehat.
JOB_TIMEOUT_BERKAS = _env_detik("JOB_TIMEOUT_BERKAS", 1800)

# Backoff sambung ulang database: 1, 2, 4, ... maksimal 30 detik. Cukup cepat
# pulih setelah Postgres restart, tapi tidak membanjiri log saat DB mati lama.
RECONNECT_AWAL = 1.0
RECONNECT_MAKS = 30.0

# Error yang berarti koneksi database rusak/putus -> harus sambung ulang.
_DB_ERRORS = (psycopg.OperationalError, psycopg.InterfaceError)


# --------------------------------------------------------------- enqueue

async def enqueue(conn, bot: str, cmd: str, value: str, *,
                  requested_by: str | None = None, priority: int = 0,
                  force: bool = False) -> dict:
    """Masukkan job ke antrian. Kembalikan barisnya.

    Kalau permintaan yang sama persis masih mengantre, job itu yang dipakai
    ulang (prioritasnya dinaikkan bila perlu) alih-alih membuat job kedua.

    force=True memaksa worker menembak Telegram walau nilainya ada di cache
    (dipakai healthcheck).
    """
    async with conn.cursor() as cur:
        # Gabungkan dengan job identik yang MASIH mengantre (index parsial
        # uq_jobs_antre, migrasi 013). Dua permintaan yang sama tidak boleh
        # menembak bot dua kali — kuota harian per fitur terlalu mahal.
        await cur.execute(
            """
            INSERT INTO search_jobs (bot, cmd, value, requested_by, priority, force)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (bot, cmd, value, force) WHERE state = 'queued'
            DO UPDATE SET priority = GREATEST(search_jobs.priority, EXCLUDED.priority)
            RETURNING *
            """,
            (bot, cmd, value, requested_by, priority, force),
        )
        row = await cur.fetchone()
    if row is not None:
        return row
    # Balapan sangat sempit: job-nya baru saja diambil worker antara INSERT
    # dan pembacaan. Masukkan sebagai job baru.
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


async def cancel(conn, job_id: str) -> bool:
    """Batalkan job yang MASIH mengantre. True kalau berhasil dibuang.

    Job yang sudah 'running'/'done' tidak bisa dibatalkan — worker sudah atau
    sedang menembak Telegram, jadi kuotanya sudah terpakai. Dipakai bot untuk
    menolak permintaan saat antrian sudah terlalu panjang, tanpa memboroskan
    kuota harian (job dibuang sebelum sempat menyentuh bot).
    """
    try:
        uuid.UUID(str(job_id))
    except (ValueError, TypeError):
        return False
    async with conn.cursor() as cur:
        await cur.execute(
            "DELETE FROM search_jobs WHERE job_id = %s AND state = 'queued' "
            "RETURNING job_id", (job_id,))
        return await cur.fetchone() is not None


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


async def pulihkan_tersangkut(conn) -> int:
    """Tandai GAGAL job yang mati di tengah jalan (tertinggal 'running').

    _claim_next() hanya mengambil job berstatus 'queued'. Kalau proses mati
    saat sebuah job sedang diproses (restart/deploy), barisnya tertinggal
    'running' SELAMANYA — tidak pernah selesai, dan pemanggilnya menunggu
    tanpa hasil. Terbukti di produksi: dua job tertinggal running setelah
    deploy.

    Dulu baris itu dikembalikan ke 'queued', tapi itu berarti bot DITEMBAK
    LAGI: perintahnya hampir pasti sudah terkirim sebelum proses mati, jadi
    kuota harian (pembatas paling mahal) terpotong dua kali untuk satu
    permintaan. Sekarang ditandai 'failed' dengan pesan jelas; ArtemisID
    melihatnya sebagai kegagalan yang bisa diulang oleh pengguna bila perlu.

    Dipanggil sekali saat worker start; aman karena worker hanya satu.
    """
    async with conn.cursor() as cur:
        await cur.execute(
            """
            UPDATE search_jobs
               SET state = 'failed',
                   error = 'dibatalkan: proses connector restart saat job berjalan',
                   finished_at = now()
             WHERE state = 'running'
            RETURNING job_id
            """)
        rows = await cur.fetchall()
    if rows:
        log.warning("%d job tersangkut 'running' ditandai gagal (tidak diantre "
                    "ulang agar kuota bot tidak terpotong dua kali)", len(rows))
    return len(rows)


# ------------------------------------------------------------- heartbeat

# Status worker untuk /health. Task asyncio yang mati tidak memberi tanda apa
# pun: API tetap melayani, /health tetap "ok", tapi antrian berhenti. Dengan
# detak ini /health bisa tahu worker masih berputar atau sedang macet.
#
# JANGAN pernah menyimpan `value` job di sini — isinya bisa NIK/nomor HP
# (data pribadi) dan /health bisa dibaca tanpa otorisasi khusus.
_status: dict[str, Any] = {
    "running": False,         # task worker sedang di dalam run_worker()
    "poll_interval": 2.0,
    "last_beat": None,        # epoch iterasi loop terakhir
    "current_job": None,      # {"job_id","bot","cmd","started"} atau None
    "last_error": None,
    "last_error_at": None,
    "reconnects": 0,
}


def _beat() -> None:
    _status["last_beat"] = time.time()


def _catat_error(pesan: str, rahasia: str | None = None) -> None:
    """Simpan error terakhir untuk /health, dengan `value` job disensor.

    Pesan exception bisa saja memuat nilai yang dicari (NIK/nomor HP), jadi
    nilainya diganti '***' sebelum disimpan.
    """
    if rahasia:
        pesan = pesan.replace(str(rahasia), "***")
    _status["last_error"] = pesan[:500]
    _status["last_error_at"] = time.time()


def worker_status() -> dict:
    """Ringkasan kesehatan worker antrian untuk /health (tanpa data pribadi).

    alive=True kalau loop berputar dalam max(poll_interval*5, 30) detik
    terakhir, atau sedang memproses job (job panjang dibatasi watchdog, jadi
    tidak bisa "hidup" selamanya tanpa detak).
    """
    sekarang = time.time()
    batas = max(float(_status["poll_interval"]) * 5, 30.0)
    beat = _status["last_beat"]
    cj = _status["current_job"]
    current = None
    if cj is not None:
        current = {
            "job_id": cj["job_id"],
            "bot": cj["bot"],
            "cmd": cj["cmd"],
            "started": cj["started"],
            "age_s": int(sekarang - cj["started"]),
        }
    alive = bool(_status["running"]) and (
        current is not None or (beat is not None and sekarang - beat <= batas))
    return {
        "alive": alive,
        "last_beat": beat,
        "current_job": current,
        "last_error": _status["last_error"],
        "last_error_at": _status["last_error_at"],
        "reconnects": _status["reconnects"],
    }


# ----------------------------------------------------------- loop worker

async def _tidur(detik: float) -> None:
    # Dibungkus supaya test bisa mempercepat jeda tanpa mengganti
    # asyncio.sleep global (yang juga dipakai asyncio.wait_for dkk.).
    await asyncio.sleep(detik)


def _conn_rusak(conn) -> bool:
    """True kalau koneksi psycopg sudah tertutup/putus dan harus diganti."""
    return bool(getattr(conn, "closed", False) or getattr(conn, "broken", False))


async def _tutup_diam(conn) -> None:
    # Koneksi yang sudah putus sering melempar error lagi saat ditutup;
    # itu tidak penting, yang penting worker tidak ikut mati.
    try:
        await conn.close()
    except Exception:                                  # noqa: BLE001
        pass


async def _sambung_ulang(lama, stop_event: asyncio.Event | None):
    """Tutup koneksi lama lalu buka koneksi baru dengan backoff.

    Mengulang terus sampai berhasil (atau stop_event di-set -> None). Postgres
    yang restart/putus sebentar tidak boleh menghentikan antrian sampai ada
    yang me-restart server secara manual.
    """
    await _tutup_diam(lama)
    jeda = RECONNECT_AWAL
    while not (stop_event and stop_event.is_set()):
        _beat()   # worker masih berputar walau DB mati; error-nya di last_error
        try:
            baru = await db.connect()
        except asyncio.CancelledError:
            raise
        except Exception as exc:                       # noqa: BLE001
            _catat_error(f"sambung ulang DB gagal: {exc!r}")
            log.warning("worker: sambung ulang DB gagal (%s), coba lagi %.0f dtk",
                        type(exc).__name__, jeda)
            await _tidur(jeda)
            jeda = min(jeda * 2, RECONNECT_MAKS)
            continue
        _status["reconnects"] += 1
        log.warning("worker: koneksi DB tersambung ulang (ke-%d)", _status["reconnects"])
        return baru
    return None


def _batas_waktu(bot: str, cmd: str) -> float:
    return JOB_TIMEOUT_BERKAS if routes.butuh_berkas(bot, cmd) else JOB_TIMEOUT


async def _tuntaskan(conn, tertunda: dict) -> None:
    """Tulis hasil akhir job ('done'/'failed') yang belum sempat tersimpan."""
    if tertunda["aksi"] == "finish":
        try:
            await _finish(conn, tertunda["job_id"], tertunda["hasil"])
            return
        except _DB_ERRORS:
            raise              # koneksi putus: ulangi setelah sambung ulang
        except Exception as exc:                       # noqa: BLE001
            # Hasilnya sendiri tidak bisa disimpan (bukan masalah koneksi):
            # tandai gagal saja supaya baris tidak tertinggal 'running'.
            log.warning("job %s: hasil gagal disimpan (%s), ditandai gagal",
                        tertunda["job_id"], type(exc).__name__)
            await _fail(conn, tertunda["job_id"], f"hasil gagal disimpan: {exc!r}")
            return
    await _fail(conn, tertunda["job_id"], tertunda["error"])


async def run_worker(tg, conn, *, poll_interval: float = 2.0,
                     stop_event: asyncio.Event | None = None) -> None:
    """Loop worker: ambil job -> proses -> simpan hasil. Serial, satu-satu.

    Tahan banting: TIDAK ADA exception yang boleh mematikan loop ini (kecuali
    CancelledError untuk shutdown). Dulu satu error DB di _claim_next() atau
    _fail() membuat task mati diam-diam — API tetap jalan, /health tetap ok,
    tapi antrian tidak bergerak sampai server di-restart manual.

    Koneksi `conn` milik pemanggil (api.py yang menutupnya). Koneksi pengganti
    hasil sambung ulang milik worker dan ditutup di sini saat keluar.
    """
    asli = conn
    _status.update(running=True, poll_interval=poll_interval, current_job=None)
    _beat()
    sudah_pulih = False
    # Hasil akhir job yang belum tersimpan karena koneksi putus; ditulis
    # ulang setelah sambung ulang supaya baris tidak tertinggal 'running'.
    tertunda: dict | None = None
    # Bot sudah tersentuh oleh job sebelumnya -> jeda dulu sebelum job
    # berikutnya (rate limit "Please wait N second(s)").
    perlu_jeda = False
    try:
        while not (stop_event and stop_event.is_set()):
            _beat()
            try:
                if _conn_rusak(conn):
                    raise psycopg.OperationalError("koneksi worker tertutup/rusak")
                if not sudah_pulih:
                    await pulihkan_tersangkut(conn)
                    sudah_pulih = True
                    log.info("worker antrian jalan")
                if tertunda is not None:
                    await _tuntaskan(conn, tertunda)
                    tertunda = None
                if perlu_jeda:
                    perlu_jeda = False
                    await _tidur(JEDA_ANTAR_JOB)
                    continue        # cek stop_event lagi setelah jeda

                job = await _claim_next(conn)
                if job is None:
                    await _tidur(poll_interval)
                    continue

                jid = str(job["job_id"])
                bot, cmd, value = job["bot"], job["cmd"], job["value"]
                batas = _batas_waktu(bot, cmd)
                _status["current_job"] = {"job_id": jid, "bot": bot, "cmd": cmd,
                                          "started": time.time()}
                # `value` sengaja tidak di-log: bisa NIK/nomor HP.
                log.info("proses job %s: %s %s (batas %.0f dtk)", jid, bot, cmd, batas)
                loop = asyncio.get_running_loop()
                mulai = loop.time()
                try:
                    hasil = await asyncio.wait_for(
                        service.query(tg, conn, bot, cmd, value,
                                      force=job.get("force", False)),
                        batas)
                except asyncio.CancelledError:
                    raise
                except TimeoutError as exc:
                    perlu_jeda = True          # bot sudah tersentuh
                    if loop.time() - mulai < batas * 0.99:
                        # TimeoutError dari dalam service, bukan watchdog.
                        _catat_error(f"job {jid} gagal: {exc!r}", value)
                        tertunda = {"aksi": "fail", "job_id": jid, "error": repr(exc)}
                    else:
                        pesan = f"timeout: bot tidak menjawab dalam {batas:g} detik"
                        log.warning("job %s (%s %s) %s", jid, bot, cmd, pesan)
                        _catat_error(f"job {jid}: {pesan}")
                        tertunda = {"aksi": "fail", "job_id": jid, "error": pesan}
                except Exception as exc:               # noqa: BLE001
                    # Tidak tahu apakah perintah sempat terkirim ke bot; anggap
                    # sudah supaya tidak memancing rate limit.
                    perlu_jeda = True
                    log.warning("job %s (%s %s) gagal: %s", jid, bot, cmd,
                                type(exc).__name__)
                    _catat_error(f"job {jid} gagal: {exc!r}", value)
                    tertunda = {"aksi": "fail", "job_id": jid, "error": repr(exc)}
                    if isinstance(exc, _DB_ERRORS):
                        raise      # sambung ulang dulu, lalu tandai gagal
                    if _conn_rusak(conn):
                        raise psycopg.OperationalError(
                            "koneksi rusak setelah job gagal") from exc
                else:
                    if not hasil.get("from_cache"):
                        perlu_jeda = True   # cache hit tidak menyentuh Telegram
                    tertunda = {"aksi": "finish", "job_id": jid, "hasil": hasil}
                    log.info("job %s selesai: %s (cache=%s)", jid,
                             hasil.get("status"), hasil.get("from_cache"))
                finally:
                    _status["current_job"] = None

                # Watchdog membatalkan service.query di tengah jalan; operasi DB
                # yang terpotong bisa meninggalkan koneksi rusak.
                if _conn_rusak(conn):
                    raise psycopg.OperationalError("koneksi rusak setelah job")
                await _tuntaskan(conn, tertunda)
                tertunda = None
                # Jeda langsung setelah hasil tersimpan (seperti dulu). Kalau
                # penyimpanan gagal, perlu_jeda tetap True dan jedanya
                # dijalankan di awal iterasi setelah sambung ulang.
                if perlu_jeda:
                    perlu_jeda = False
                    await _tidur(JEDA_ANTAR_JOB)

            except asyncio.CancelledError:
                raise
            except _DB_ERRORS as exc:
                _catat_error(f"DB error: {exc!r}")
                log.warning("worker: error database (%s), sambung ulang",
                            type(exc).__name__)
                baru = await _sambung_ulang(conn, stop_event)
                if baru is None:
                    break           # stop_event di-set saat menunggu DB
                conn = baru
            except Exception as exc:                   # noqa: BLE001
                _catat_error(f"worker error: {exc!r}")
                log.exception("worker: error tak terduga, loop lanjut")
                if _conn_rusak(conn):
                    baru = await _sambung_ulang(conn, stop_event)
                    if baru is None:
                        break
                    conn = baru
                else:
                    if tertunda is not None and tertunda.get("_coba", 0) >= 3:
                        # Bukan masalah koneksi dan terus gagal: lepaskan agar
                        # loop tidak berputar di job yang sama. Barisnya akan
                        # ditandai gagal oleh pulihkan_tersangkut() saat start.
                        log.error("job %s: hasil akhir tidak bisa disimpan, dilepas",
                                  tertunda["job_id"])
                        tertunda = None
                    elif tertunda is not None:
                        tertunda["_coba"] = tertunda.get("_coba", 0) + 1
                    # Hindari loop panas kalau error-nya berulang terus.
                    await _tidur(poll_interval)
    finally:
        _status["running"] = False
        _status["current_job"] = None
        if conn is not asli:
            await _tutup_diam(conn)


# ------------------------------------------------------------- validasi

def validate(bot: str, cmd: str) -> str | None:
    """Kembalikan pesan error kalau kombinasi bot+command tidak dikenal."""
    if routes.get_route(bot, cmd) is None:
        return f"command '{cmd}' tidak tersedia untuk {bot}"
    return None
